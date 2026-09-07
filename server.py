from __future__ import annotations

import argparse
import hashlib
import math
import html
import json
import mimetypes
import os
import re
import threading
import time
import urllib.error
import urllib.parse
import urllib.request
from collections import defaultdict, deque
from datetime import datetime, timezone
from html.parser import HTMLParser
from http import HTTPStatus
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
from typing import Any
from xml.etree import ElementTree


ROOT = Path(__file__).resolve().parent
STATIC_DIR = ROOT / "static"
USER_AGENT = "ChinaContentStudio/1.0 (local editorial tool)"
MAX_BODY_BYTES = 2 * 1024 * 1024
DISCOVERY_BLOCKLIST = re.compile(
    r"\b(?:porn|nude|rape|sexual assault|murder|homicide|suicide|killed?|death|dead body|died|"
    r"shooting|stabbing|weapon|gun violence|terroris(?:m|t)|war crimes?|armed conflict|"
    r"religious conflict|soldiers?|military|pentagon|election|president|prime minister|congress|"
    r"senate|geopolitic|politic(?:s|al)|united nations|UN|trump|biden|putin|lawsuit|"
    r"wrongful death|thieves?|theft)\b",
    re.IGNORECASE,
)


CATEGORIES = [
    {"id": "popular", "name": "全站热门", "community": "popular", "description": "综合热帖"},
    {"id": "askreddit", "name": "热门问答", "community": "AskReddit", "description": "经历与观点"},
    {"id": "todayilearned", "name": "冷知识", "community": "todayilearned", "description": "新鲜知识"},
    {"id": "lifeprotips", "name": "生活技巧", "community": "LifeProTips", "description": "实用经验"},
    {"id": "explainlikeimfive", "name": "通俗科普", "community": "explainlikeimfive", "description": "复杂问题简单讲"},
    {"id": "productivity", "name": "效率成长", "community": "productivity", "description": "习惯与工具"},
    {"id": "personalfinance", "name": "个人理财", "community": "personalfinance", "description": "财务常识"},
    {"id": "technology", "name": "科技趋势", "community": "technology", "description": "产品与行业"},
    {"id": "science", "name": "科学发现", "community": "science", "description": "研究与发现"},
    {"id": "books", "name": "读书文化", "community": "books", "description": "阅读与作品"},
    {"id": "movies", "name": "影视讨论", "community": "movies", "description": "电影与创作"},
    {"id": "travel", "name": "旅行见闻", "community": "travel", "description": "目的地与经验"},
    {"id": "cooking", "name": "美食烹饪", "community": "Cooking", "description": "菜谱与厨房"},
]

QUORA_CATEGORIES = [
    {"id": "popular", "name": "综合问答", "topic": "popular", "query": "popular questions", "description": "综合话题"},
    {"id": "life-advice", "name": "生活经验", "topic": "life-advice", "query": "life advice", "description": "生活与选择"},
    {"id": "technology", "name": "科技趋势", "topic": "technology", "query": "technology", "description": "技术与产品"},
    {"id": "careers", "name": "职场发展", "topic": "careers", "query": "career advice", "description": "职业与成长"},
    {"id": "psychology", "name": "心理认知", "topic": "psychology", "query": "psychology", "description": "行为与思维"},
    {"id": "education", "name": "教育学习", "topic": "education", "query": "education learning", "description": "学习与教育"},
    {"id": "business", "name": "商业观察", "topic": "business", "query": "business entrepreneurship", "description": "商业与创业"},
    {"id": "science", "name": "科学知识", "topic": "science", "query": "science", "description": "科学与发现"},
    {"id": "travel", "name": "旅行见闻", "topic": "travel", "query": "travel experiences", "description": "旅行与文化"},
    {"id": "relationships", "name": "人际关系", "topic": "relationships", "query": "relationships communication", "description": "沟通与相处"},
]


SYSTEM_PROMPT = """你是一位精通跨文化传播、中国主流内容平台内容规律与合规审查的资深内容总监。

任务：将提供的海外论坛帖子（标题、正文、热门评论）提炼、翻译并深度改编为适合中国读者的原创中文内容，同时生成配套 AI 绘图提示词。

必须遵守：
1. 准确提取核心观点、情绪价值、故事或实用信息；不得虚构事实、人物经历、数据、机构背书或评论共识。
2. 不是逐句翻译。删除只在英文语境成立的梗、重复内容与无信息量评论，使用自然中文重组。
3. 涉及政治、宗教冲突、违法犯罪、色情暴力、仇恨、隐私或未成年人风险时，转化为普适的生活、职场、社交、消费或科技讨论；无法安全转化时，在 compliance_check 中说明并避免展开。
4. 海外单位换算为中国常用单位；AITA、TL;DR、OP 等术语改写为国内读者熟悉的说法。保留海外故事背景，不得把真实发生地或身份伪装成国内事件。
5. 明确区分帖主陈述、网友意见与可验证事实；健康、法律、金融内容不得给出确定性专业结论。
6. 小红书：短段落、自然使用 Emoji 作为视觉锚点，真诚有共鸣；标题带 2-3 个 Emoji；文末给 5-8 个精准标签。禁止低俗标题党和夸大承诺。
7. 今日头条：完整段落、故事或观点递进、语言平实，开头有吸引力，结尾有思考与互动问题。
8. 每个平台文章结尾都要有适合该平台的真实互动话题。
9. 生成 3-5 组中英双语图片提示词。英文 prompt_en 可直接用于 Midjourney、Flux 或 ChatGPT，中文 prompt_zh 可直接用于豆包。画面应与文章段落匹配、高画质、有视觉冲击力、细节明确，并避免品牌商标、平台 UI、水印和画面内文字。

只输出一个合法 JSON 对象，不得使用 Markdown 代码围栏，不得在 JSON 外添加说明。固定结构：
{
  "original_summary": "原帖核心内容一句话总结",
  "compliance_check": "合规修改说明；无调整则写完全合规",
  "xiaohongshu": {"title": "标题或空字符串", "content": "正文或空字符串"},
  "toutiao": {"title": "标题或空字符串", "content": "正文或空字符串"},
  "image_prompts": [
    {"scene_description": "中文应用场景", "prompt_en": "Detailed English prompt...", "prompt_zh": "可直接用于豆包的详细中文提示词"}
  ]
}
"""

OUTPUT_SCHEMA = {
    "type": "object",
    "additionalProperties": False,
    "required": ["original_summary", "compliance_check", "xiaohongshu", "toutiao", "image_prompts"],
    "properties": {
        "original_summary": {"type": "string"},
        "compliance_check": {"type": "string"},
        "xiaohongshu": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "content"],
            "properties": {"title": {"type": "string"}, "content": {"type": "string"}},
        },
        "toutiao": {
            "type": "object",
            "additionalProperties": False,
            "required": ["title", "content"],
            "properties": {"title": {"type": "string"}, "content": {"type": "string"}},
        },
        "image_prompts": {
            "type": "array",
            "minItems": 3,
            "maxItems": 5,
            "items": {
                "type": "object",
                "additionalProperties": False,
                "required": ["scene_description", "prompt_en", "prompt_zh"],
                "properties": {
                    "scene_description": {"type": "string"},
                    "prompt_en": {"type": "string"},
                    "prompt_zh": {"type": "string"},
                },
            },
        },
    },
}


class ApiError(Exception):
    def __init__(self, status: int, message: str, detail: str | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail


class RateLimiter:
    def __init__(self) -> None:
        self._calls: dict[str, deque[tuple[float, int]]] = defaultdict(deque)
        self._last_call: dict[str, float] = {}
        self._lock = threading.Lock()

    def acquire(self, key: str, rpm: int, tpm: int, token_cost: int) -> None:
        rpm = max(1, min(rpm, 600))
        tpm = max(1000, min(tpm, 10_000_000))
        if token_cost > tpm:
            raise ApiError(HTTPStatus.BAD_REQUEST, f"单次请求预算约 {token_cost} Token，超过 TPM 限额 {tpm}")
        minimum_interval = 60.0 / rpm
        while True:
            with self._lock:
                now = time.monotonic()
                calls = self._calls[key]
                while calls and now - calls[0][0] >= 60:
                    calls.popleft()
                used_tokens = sum(item[1] for item in calls)
                spacing_wait = max(0.0, minimum_interval - (now - self._last_call.get(key, 0.0)))
                rpm_wait = max(0.0, 60 - (now - calls[0][0])) if len(calls) >= rpm else 0.0
                tpm_wait = max(0.0, 60 - (now - calls[0][0])) if calls and used_tokens + token_cost > tpm else 0.0
                wait_for = max(spacing_wait, rpm_wait, tpm_wait)
                if wait_for <= 0:
                    calls.append((now, token_cost))
                    self._last_call[key] = now
                    return
            time.sleep(min(wait_for, 1.0))


RATE_LIMITER = RateLimiter()
REDDIT_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
REDDIT_CACHE_LOCK = threading.Lock()
REDDIT_CACHE_SECONDS = 300
QUORA_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
QUORA_CACHE_LOCK = threading.Lock()
QUORA_CACHE_SECONDS = 600
QUORA_API_BASE_URL = os.environ.get("QUORA_API_BASE_URL", "").strip().rstrip("/")
QUORA_API_TOKEN = os.environ.get("QUORA_API_TOKEN", "").strip()


def http_json(url: str, *, headers: dict[str, str] | None = None, data: dict[str, Any] | None = None,
              timeout: int = 25) -> Any:
    request_headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    if headers:
        request_headers.update(headers)
    encoded = None
    if data is not None:
        encoded = json.dumps(data, ensure_ascii=False).encode("utf-8")
        request_headers["Content-Type"] = "application/json"
    request = urllib.request.Request(url, data=encoded, headers=request_headers, method="POST" if data is not None else "GET")
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_BODY_BYTES + 1)
            if len(raw) > MAX_BODY_BYTES:
                raise ApiError(HTTPStatus.BAD_GATEWAY, "上游服务响应超过 2 MB")
            raw = raw.decode("utf-8")
            return json.loads(raw)
    except urllib.error.HTTPError as exc:
        detail = exc.read().decode("utf-8", errors="replace")[:800]
        raise ApiError(exc.code, "上游服务请求失败", detail) from exc
    except urllib.error.URLError as exc:
        raise ApiError(HTTPStatus.BAD_GATEWAY, "无法连接上游服务", str(exc.reason)) from exc
    except json.JSONDecodeError as exc:
        raise ApiError(HTTPStatus.BAD_GATEWAY, "上游服务返回了无效 JSON") from exc


def http_text(url: str, *, timeout: int = 25, source_name: str = "上游页面",
              accept: str = "text/html, application/xhtml+xml, application/atom+xml, application/xml;q=0.9") -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": accept,
            "Accept-Language": "en-US,en;q=0.9",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_BODY_BYTES + 1)
            if len(raw) > MAX_BODY_BYTES:
                raise ApiError(HTTPStatus.BAD_GATEWAY, f"{source_name}响应超过 2 MB")
            return raw.decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise ApiError(exc.code, f"{source_name}请求失败") from exc
    except urllib.error.URLError as exc:
        raise ApiError(HTTPStatus.BAD_GATEWAY, f"无法连接{source_name}", str(exc.reason)) from exc
    except UnicodeDecodeError as exc:
        raise ApiError(HTTPStatus.BAD_GATEWAY, f"{source_name}编码异常") from exc


def reddit_url(path: str, params: dict[str, Any] | None = None) -> str:
    query = urllib.parse.urlencode(params or {})
    suffix = f"?{query}" if query else ""
    return f"https://www.reddit.com{path}{suffix}"


def clean_text(value: Any, max_length: int = 20000) -> str:
    text = str(value or "").replace("\x00", "").strip()
    return text[:max_length]


def safe_for_discovery(post: dict[str, Any]) -> bool:
    searchable = f"{post.get('title', '')}\n{post.get('body', '')[:1200]}"
    return not bool(post.get("nsfw")) and not DISCOVERY_BLOCKLIST.search(searchable)


def post_from_child(child: dict[str, Any]) -> dict[str, Any]:
    data = child.get("data", {})
    thumbnail = clean_text(data.get("thumbnail"), 1000)
    if not thumbnail.startswith("http"):
        preview = data.get("preview", {}).get("images", [])
        thumbnail = clean_text(preview[0].get("source", {}).get("url"), 1000) if preview else ""
    thumbnail = thumbnail.replace("&amp;", "&")
    permalink = clean_text(data.get("permalink"), 2000)
    created = data.get("created_utc")
    created_iso = ""
    if isinstance(created, (int, float)):
        created_iso = datetime.fromtimestamp(created, tz=timezone.utc).isoformat()
    return {
        "id": clean_text(data.get("id"), 50),
        "source": "reddit",
        "title": clean_text(data.get("title"), 600),
        "body": clean_text(data.get("selftext")),
        "author": clean_text(data.get("author"), 100),
        "community": clean_text(data.get("subreddit"), 100),
        "score": int(data.get("score") or 0),
        "comments_count": int(data.get("num_comments") or 0),
        "view_count": 0,
        "created_at": created_iso,
        "permalink": f"https://www.reddit.com{permalink}" if permalink.startswith("/") else permalink,
        "external_url": clean_text(data.get("url_overridden_by_dest") or data.get("url"), 2000),
        "thumbnail": thumbnail,
        "is_text": bool(data.get("is_self")),
        "nsfw": bool(data.get("over_18")),
    }


class _HtmlSummaryParser(HTMLParser):
    def __init__(self) -> None:
        super().__init__(convert_charrefs=True)
        self.text_parts: list[str] = []
        self.first_image = ""

    def handle_starttag(self, tag: str, attrs: list[tuple[str, str | None]]) -> None:
        if tag == "img" and not self.first_image:
            source = dict(attrs).get("src") or ""
            if source.startswith("https://"):
                self.first_image = source
        if tag in {"p", "div", "br", "li"}:
            self.text_parts.append("\n")

    def handle_data(self, data: str) -> None:
        self.text_parts.append(data)

    def summary(self) -> str:
        value = html.unescape("".join(self.text_parts))
        value = re.sub(r"\s+submitted by\s+.*?\[link\]\s*\[comments\]\s*$", "", value, flags=re.IGNORECASE | re.DOTALL)
        value = re.sub(r"[ \t]+", " ", value)
        value = re.sub(r"\n\s*\n+", "\n\n", value)
        return clean_text(value, 20000)


def strip_markup(value: Any, max_length: int = 30000) -> str:
    raw = html.unescape(clean_text(value, max_length * 2))
    parser = _HtmlSummaryParser()
    try:
        parser.feed(raw)
        result = parser.summary()
    except Exception:
        result = re.sub(r"<[^>]+>", " ", raw)
    return clean_text(result, max_length)


def normalize_quora_url(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    host = (parsed.hostname or "").lower()
    if parsed.scheme != "https" or not (host == "quora.com" or host.endswith(".quora.com")):
        raise ApiError(HTTPStatus.BAD_REQUEST, "请输入有效的 HTTPS Quora 帖子链接")
    if parsed.username or parsed.password or parsed.port:
        raise ApiError(HTTPStatus.BAD_REQUEST, "Quora 链接不能包含账户信息或自定义端口")
    if not parsed.path or parsed.path == "/":
        raise ApiError(HTTPStatus.BAD_REQUEST, "请输入具体的 Quora 问题链接")
    return urllib.parse.urlunparse(("https", "www.quora.com", parsed.path, "", "", ""))


def _quora_category(topic: str) -> dict[str, str]:
    for category in QUORA_CATEGORIES:
        if category["topic"] == topic:
            return category
    return QUORA_CATEGORIES[0]


def quora_connector_url(path: str, params: dict[str, Any]) -> str:
    if not QUORA_API_BASE_URL:
        raise ApiError(
            HTTPStatus.SERVICE_UNAVAILABLE,
            "Quora 自动发现需要已获授权的内容连接器",
            "请设置 QUORA_API_BASE_URL；项目不会绕过 Quora 的访问控制或机器人规则。",
        )
    parsed = urllib.parse.urlparse(QUORA_API_BASE_URL)
    if parsed.scheme not in {"http", "https"} or not parsed.hostname:
        raise ApiError(HTTPStatus.INTERNAL_SERVER_ERROR, "QUORA_API_BASE_URL 配置无效")
    return f"{QUORA_API_BASE_URL}{path}?{urllib.parse.urlencode(params)}"


def normalize_quora_connector_post(value: dict[str, Any], topic: str = "Quora") -> dict[str, Any]:
    url = normalize_quora_url(clean_text(value.get("permalink") or value.get("url"), 2000))
    comments = []
    for item in value.get("comments", []) if isinstance(value.get("comments"), list) else []:
        if not isinstance(item, dict):
            continue
        body = sanitize_prompt_text(item.get("body") or item.get("text"), 12000)
        if body:
            comments.append({
                "author": clean_text(item.get("author"), 100),
                "body": body,
                "score": int(item.get("score") or item.get("upvotes") or 0),
            })
    return {
        "id": clean_text(value.get("id"), 100) or hashlib.sha256(url.encode("utf-8")).hexdigest()[:16],
        "source": "quora",
        "title": sanitize_prompt_text(value.get("title") or value.get("question"), 800),
        "body": sanitize_prompt_text(value.get("body") or value.get("content") or value.get("answer"), 120000),
        "author": clean_text(value.get("author"), 100),
        "community": clean_text(value.get("community") or value.get("topic"), 100) or topic,
        "score": int(value.get("score") or value.get("upvotes") or 0),
        "comments_count": int(value.get("comments_count") or value.get("answer_count") or len(comments)),
        "view_count": int(value.get("view_count") or value.get("views") or 0),
        "created_at": clean_text(value.get("created_at") or value.get("published_at"), 100),
        "permalink": url,
        "external_url": url,
        "thumbnail": clean_text(value.get("thumbnail") or value.get("image"), 2000),
        "is_text": True,
        "nsfw": bool(value.get("nsfw")),
        "comments": comments[:10],
        "authorized_connector": True,
    }


def fetch_quora_posts(topic: str, sort: str, limit: int, force: bool = False) -> list[dict[str, Any]]:
    category = _quora_category(re.sub(r"[^a-z0-9-]+", "", topic.lower()))
    sort = sort if sort in {"hot", "upvotes", "comments", "views", "new"} else "hot"
    limit = max(5, min(limit, 30))
    key = f"{category['topic']}|{sort}|{limit}"
    with QUORA_CACHE_LOCK:
        cached = QUORA_CACHE.get(key)
        now = time.monotonic()
        if cached and not force and now - cached[0] < QUORA_CACHE_SECONDS:
            return cached[1]
        try:
            headers = {"Authorization": f"Bearer {QUORA_API_TOKEN}"} if QUORA_API_TOKEN else {}
            response = http_json(
                quora_connector_url("/posts", {"topic": category["topic"], "sort": sort, "limit": limit}),
                headers=headers,
            )
            raw_posts = response.get("posts", []) if isinstance(response, dict) else response
            if not isinstance(raw_posts, list):
                raise ApiError(HTTPStatus.BAD_GATEWAY, "Quora 连接器返回的 posts 格式无效")
            posts = [normalize_quora_connector_post(item, category["topic"]) for item in raw_posts if isinstance(item, dict)]
            posts = [post for post in posts if post["title"] and safe_for_discovery(post)]
        except ApiError:
            if cached:
                return cached[1]
            raise
        posts = posts[:limit]
        QUORA_CACHE[key] = (now, posts)
        return posts


def find_cached_quora_post(url: str) -> dict[str, Any] | None:
    target = normalize_quora_url(url).lower()
    with QUORA_CACHE_LOCK:
        for _, posts in QUORA_CACHE.values():
            for post in posts:
                if post.get("permalink", "").lower() == target:
                    return dict(post)
    return None


def fetch_quora_post(url: str) -> dict[str, Any]:
    normalized = normalize_quora_url(url)
    try:
        headers = {"Authorization": f"Bearer {QUORA_API_TOKEN}"} if QUORA_API_TOKEN else {}
        response = http_json(quora_connector_url("/post", {"url": normalized}), headers=headers)
        raw_post = response.get("post", response) if isinstance(response, dict) else response
        if not isinstance(raw_post, dict):
            raise ApiError(HTTPStatus.BAD_GATEWAY, "Quora 连接器返回的 post 格式无效")
        return normalize_quora_connector_post(raw_post)
    except ApiError:
        cached = find_cached_quora_post(normalized)
        if cached:
            cached["detail_fallback"] = True
            return cached
        raise


def _atom_text(entry: ElementTree.Element, name: str) -> str:
    node = entry.find(f"{{http://www.w3.org/2005/Atom}}{name}")
    return clean_text(node.text if node is not None else "")


def parse_reddit_feed(xml_text: str, community: str) -> list[dict[str, Any]]:
    if "<!DOCTYPE" in xml_text.upper() or "<!ENTITY" in xml_text.upper():
        raise ApiError(HTTPStatus.BAD_GATEWAY, "Reddit RSS 包含不受支持的 XML 声明")
    try:
        root = ElementTree.fromstring(xml_text)
    except ElementTree.ParseError as exc:
        raise ApiError(HTTPStatus.BAD_GATEWAY, "Reddit RSS 格式异常") from exc
    namespace = "{http://www.w3.org/2005/Atom}"
    posts: list[dict[str, Any]] = []
    for entry in root.findall(f"{namespace}entry"):
        title = _atom_text(entry, "title")
        post_id = _atom_text(entry, "id").removeprefix("t3_")
        link_node = entry.find(f"{namespace}link")
        permalink = clean_text(link_node.get("href") if link_node is not None else "", 2000)
        author_node = entry.find(f"{namespace}author/{namespace}name")
        author = clean_text(author_node.text if author_node is not None else "", 100).removeprefix("/u/")
        content_node = entry.find(f"{namespace}content")
        parser = _HtmlSummaryParser()
        parser.feed(content_node.text or "" if content_node is not None else "")
        body = parser.summary()
        published = _atom_text(entry, "published") or _atom_text(entry, "updated")
        if not title or not permalink:
            continue
        posts.append({
            "id": post_id or permalink.rstrip("/").split("/")[-2],
            "source": "reddit",
            "title": title,
            "body": body,
            "author": author,
            "community": community,
            "score": 0,
            "comments_count": 0,
            "view_count": 0,
            "created_at": published,
            "permalink": permalink,
            "external_url": permalink,
            "thumbnail": parser.first_image,
            "is_text": bool(body),
            "nsfw": False,
            "feed_fallback": True,
        })
    return posts


def fetch_reddit_rss_posts(community: str, sort: str, period: str, limit: int) -> list[dict[str, Any]]:
    path = f"/r/{community}/.rss" if sort in {"hot", "rising"} else f"/r/{community}/{sort}/.rss"
    feed = http_text(reddit_url(path, {"t": period}))
    return [post for post in parse_reddit_feed(feed, community) if safe_for_discovery(post)][:limit]


def _fetch_reddit_posts_uncached(community: str, sort: str, period: str, limit: int) -> list[dict[str, Any]]:
    community = re.sub(r"[^A-Za-z0-9_]+", "", community) or "popular"
    sort = sort if sort in {"hot", "top", "comments", "new", "rising"} else "hot"
    period = period if period in {"hour", "day", "week", "month", "year", "all"} else "day"
    limit = max(5, min(limit, 50))
    try:
        upstream_sort = "hot" if sort == "comments" else sort
        payload = http_json(reddit_url(f"/r/{community}/{upstream_sort}.json", {"limit": limit, "t": period, "raw_json": 1}))
        children = payload.get("data", {}).get("children", [])
        posts = [post for child in children if safe_for_discovery(post := post_from_child(child))]
        if sort == "comments":
            posts.sort(key=lambda item: item["comments_count"], reverse=True)
        return posts
    except ApiError as exc:
        if exc.status not in {HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND, HTTPStatus.TOO_MANY_REQUESTS}:
            raise
        return fetch_reddit_rss_posts(community, "hot" if sort == "comments" else sort, period, limit)


def fetch_reddit_posts(community: str, sort: str, period: str, limit: int, force: bool = False) -> list[dict[str, Any]]:
    community = re.sub(r"[^A-Za-z0-9_]+", "", community) or "popular"
    sort = sort if sort in {"hot", "top", "comments", "new", "rising"} else "hot"
    period = period if period in {"hour", "day", "week", "month", "year", "all"} else "day"
    limit = max(5, min(limit, 50))
    key = f"{community.lower()}|{sort}|{period}|{limit}"
    with REDDIT_CACHE_LOCK:
        cached = REDDIT_CACHE.get(key)
        now = time.monotonic()
        if cached and not force and now - cached[0] < REDDIT_CACHE_SECONDS:
            return cached[1]
        try:
            posts = _fetch_reddit_posts_uncached(community, sort, period, limit)
        except ApiError:
            if cached:
                return cached[1]
            raise
        REDDIT_CACHE[key] = (now, posts)
        return posts


def normalize_reddit_permalink(url: str) -> str:
    parsed = urllib.parse.urlparse(url)
    if parsed.netloc.lower() not in {"reddit.com", "www.reddit.com", "old.reddit.com", "redd.it"}:
        raise ApiError(HTTPStatus.BAD_REQUEST, "请输入有效的 Reddit 帖子链接")
    path = parsed.path.rstrip("/")
    if parsed.netloc.lower() == "redd.it":
        post_id = path.strip("/")
        if not re.fullmatch(r"[A-Za-z0-9]+", post_id):
            raise ApiError(HTTPStatus.BAD_REQUEST, "Reddit 短链接格式无效")
        path = f"/comments/{post_id}"
    if not path.endswith(".json"):
        path += ".json"
    return reddit_url(path, {"limit": 12, "sort": "top", "raw_json": 1})


def fetch_reddit_post(url: str) -> dict[str, Any]:
    normalized_url = normalize_reddit_permalink(url)
    try:
        payload = http_json(normalized_url)
    except ApiError as exc:
        if exc.status not in {HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND, HTTPStatus.TOO_MANY_REQUESTS}:
            raise
        try:
            return fetch_reddit_rss_post(url)
        except ApiError:
            cached = find_cached_reddit_post(url)
            if cached:
                cached["comments"] = []
                cached["detail_fallback"] = True
                return cached
            raise
    if not isinstance(payload, list) or not payload:
        raise ApiError(HTTPStatus.BAD_GATEWAY, "Reddit 帖子数据格式异常")
    post_children = payload[0].get("data", {}).get("children", [])
    if not post_children:
        raise ApiError(HTTPStatus.NOT_FOUND, "没有找到该帖子")
    post = post_from_child(post_children[0])
    comments: list[dict[str, Any]] = []
    if len(payload) > 1:
        for child in payload[1].get("data", {}).get("children", []):
            data = child.get("data", {})
            body = clean_text(data.get("body"), 3000)
            author = clean_text(data.get("author"), 100)
            if child.get("kind") != "t1" or not body or body in {"[deleted]", "[removed]"} or author == "AutoModerator":
                continue
            comments.append({"author": author, "body": body, "score": int(data.get("score") or 0)})
    post["comments"] = comments[:10]
    return post


def find_cached_reddit_post(url: str) -> dict[str, Any] | None:
    target_path = urllib.parse.urlparse(url).path.rstrip("/").lower()
    with REDDIT_CACHE_LOCK:
        for _, posts in REDDIT_CACHE.values():
            for post in posts:
                post_path = urllib.parse.urlparse(post.get("permalink", "")).path.rstrip("/").lower()
                if post_path and post_path == target_path:
                    return dict(post)
    return None


def fetch_reddit_rss_post(url: str) -> dict[str, Any]:
    parsed = urllib.parse.urlparse(url)
    normalize_reddit_permalink(url)  # Validate the host and path before requesting it.
    path = parsed.path.rstrip("/")
    segments = [part for part in path.split("/") if part]
    community = segments[1] if len(segments) > 1 and segments[0].lower() == "r" else "reddit"
    feed_url = reddit_url(f"{path}/.rss", {"sort": "top", "limit": 12})
    feed_posts = parse_reddit_feed(http_text(feed_url), community)
    if not feed_posts:
        raise ApiError(HTTPStatus.NOT_FOUND, "没有找到该帖子的 RSS 内容")
    post = feed_posts[0]
    comments = []
    for item in feed_posts[1:]:
        if item["body"]:
            comments.append({"author": item["author"], "body": item["body"], "score": 0})
    post["comments"] = comments[:10]
    return post


def completion_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise ApiError(HTTPStatus.BAD_REQUEST, "模型接口地址必须以 http:// 或 https:// 开头")
    if value.endswith("/chat/completions"):
        return value
    return f"{value}/chat/completions"


def anthropic_url(base_url: str) -> str:
    value = base_url.strip().rstrip("/")
    if not value.startswith(("http://", "https://")):
        raise ApiError(HTTPStatus.BAD_REQUEST, "模型接口地址必须以 http:// 或 https:// 开头")
    if value.endswith("/messages"):
        return value
    return f"{value}/messages"


def estimate_tokens(value: str) -> int:
    ascii_count = sum(1 for character in value if ord(character) < 128)
    non_ascii_count = len(value) - ascii_count
    return max(1, math.ceil(ascii_count / 4 + non_ascii_count))


def truncate_to_tokens(value: str, token_budget: int) -> str:
    value = clean_text(value, 200000)
    if estimate_tokens(value) <= token_budget:
        return value
    used = 0.0
    output: list[str] = []
    for character in value:
        used += 0.25 if ord(character) < 128 else 1.0
        if used > token_budget:
            break
        output.append(character)
    return "".join(output).rstrip() + "\n[内容因输入预算已截断]"


def sanitize_prompt_text(value: Any, max_length: int = 100000) -> str:
    text = html.unescape(clean_text(value, max_length))
    if text.strip().lower() in {"[deleted]", "[removed]", "deleted", "removed"}:
        return ""
    text = re.sub(r"!\[[^\]]*\]\([^)]*\)", "", text)
    text = re.sub(
        r"\[([^\]]+)\]\((?:https?://(?:www\.|old\.)?reddit\.com|https?://redd\.it|/r/|/u/)[^)]*\)",
        r"\1",
        text,
        flags=re.IGNORECASE,
    )
    text = re.sub(r"https?://\S+\.(?:png|jpe?g|gif|webp|svg)(?:\?\S*)?", "", text, flags=re.IGNORECASE)
    text = re.sub(r"https?://(?:www\.|old\.)?reddit\.com/\S+|https?://redd\.it/\S+", "", text, flags=re.IGNORECASE)
    text = re.sub(r"(?<!\w)/(?:r|u)/[A-Za-z0-9_-]+", "", text)
    if "<" in text and ">" in text:
        text = strip_markup(text, max_length)
    text = re.sub(r"[ \t]+", " ", text)
    text = re.sub(r"\n\s*\n+", "\n\n", text)
    return clean_text(text, max_length)


def prepare_comments(comments: Any, sort: str, limit: int, token_budget: int) -> list[dict[str, Any]]:
    cleaned: list[dict[str, Any]] = []
    if not isinstance(comments, list):
        return cleaned
    for item in comments:
        if not isinstance(item, dict):
            continue
        body = sanitize_prompt_text(item.get("body"), 12000)
        author = clean_text(item.get("author"), 100)
        if not body or author == "AutoModerator":
            continue
        cleaned.append({"body": body, "author": author, "score": int(item.get("score") or 0)})
    if sort == "score":
        cleaned.sort(key=lambda item: item["score"], reverse=True)
    elif sort == "longest":
        cleaned.sort(key=lambda item: len(item["body"]), reverse=True)
    limit = max(5, min(limit, 10))
    selected = cleaned[:limit]
    if not selected:
        return selected
    per_comment = max(80, token_budget // len(selected))
    for item in selected:
        item["body"] = truncate_to_tokens(item["body"], per_comment)
    return selected


def build_user_prompt(source: dict[str, Any], config: dict[str, Any]) -> tuple[str, dict[str, Any]]:
    platform = sanitize_prompt_text(source.get("platform"), 100) or "海外论坛"
    community = sanitize_prompt_text(source.get("community") or source.get("subreddit"), 200) or "未提供"
    title = sanitize_prompt_text(source.get("title"), 1000)
    input_budget = max(1500, min(int(config.get("input_token_budget") or 12000), 64000))
    fixed_prompt = (
        f"请处理以下 {platform} 抓取到的热帖数据，并按照系统指定的 JSON 格式输出改编后的文章及绘图提示词：\n\n"
        "【源贴信息】\n\n"
        f"- 信息源: {platform}\n"
        f"- 所属版块 (Subreddit) / 主题: {community}\n"
        f"- 帖子原标题: {title}\n"
        "- 帖子正文: \n"
        "- 高赞评论精选:\n\n"
        "【特别要求】\n\n"
        "1. 请同时生成【小红书】和【今日头条】两个版本的改编文案。\n\n"
        "2. 配图提示词需贴合文本意境，风格偏向高画质、具有视觉冲击力。每张图同时提供可直接复制到 Midjourney、Flux 或 ChatGPT 使用的英文 Prompt，以及可直接复制到豆包使用的中文 Prompt。\n\n"
        "3. 信息不足时请明确收缩表述，不得补造原帖未提供的事实。"
    )
    system_tokens = estimate_tokens(SYSTEM_PROMPT)
    fixed_tokens = estimate_tokens(fixed_prompt)
    content_budget = max(500, input_budget - system_tokens - fixed_tokens)
    body_budget = max(300, int(content_budget * 0.62))
    comment_budget = max(200, content_budget - body_budget)
    body = truncate_to_tokens(sanitize_prompt_text(source.get("body"), 120000), body_budget)
    if not body:
        body = "原帖无正文，请仅根据标题与评论谨慎提炼。"
    comment_sort = clean_text(source.get("comment_sort"), 20) or "score"
    comment_limit = int(source.get("comment_limit") or 8)
    comments = prepare_comments(source.get("comments"), comment_sort, comment_limit, comment_budget)
    comment_lines = []
    for index, item in enumerate(comments):
        score_label = f"（点赞 {item['score']}）" if item["score"] else ""
        comment_lines.append(f"评论 {index + 1}{score_label}: {item['body']}")
    comment_text = "\n\n".join(comment_lines) or "未获取到可用评论。"
    prompt = (
        f"请处理以下 {platform} 抓取到的热帖数据，并按照系统指定的 JSON 格式输出改编后的文章及绘图提示词：\n\n"
        "【源贴信息】\n\n"
        f"- 信息源: {platform}\n"
        f"- 所属版块 (Subreddit) / 主题: {community}\n"
        f"- 帖子原标题: {title}\n"
        f"- 帖子正文:\n{body}\n"
        f"- 高赞评论精选:\n{comment_text}\n\n"
        "【特别要求】\n\n"
        "1. 请同时生成【小红书】和【今日头条】两个版本的改编文案。\n\n"
        "2. 配图提示词需贴合文本意境，风格偏向高画质、具有视觉冲击力。每张图同时提供可直接复制到 Midjourney、Flux 或 ChatGPT 使用的英文 Prompt，以及可直接复制到豆包使用的中文 Prompt。\n\n"
        "3. 信息不足时请明确收缩表述，不得补造原帖未提供的事实。"
    )
    return prompt, {
        "input_budget": input_budget,
        "estimated_input_tokens": estimate_tokens(SYSTEM_PROMPT) + estimate_tokens(prompt),
        "comments_used": len(comments),
        "body_truncated": "[内容因输入预算已截断]" in body,
    }


def extract_json_object(text: str) -> dict[str, Any]:
    value = text.strip()
    if value.startswith("```"):
        value = re.sub(r"^```(?:json)?\s*", "", value, flags=re.IGNORECASE)
        value = re.sub(r"\s*```$", "", value)
    try:
        parsed = json.loads(value)
    except json.JSONDecodeError:
        start, end = value.find("{"), value.rfind("}")
        if start < 0 or end <= start:
            raise ApiError(HTTPStatus.BAD_GATEWAY, "模型没有返回可解析的 JSON")
        try:
            parsed = json.loads(value[start:end + 1])
        except json.JSONDecodeError as exc:
            raise ApiError(HTTPStatus.BAD_GATEWAY, "模型返回的 JSON 格式不完整", str(exc)) from exc
    if not isinstance(parsed, dict):
        raise ApiError(HTTPStatus.BAD_GATEWAY, "模型返回结果不是 JSON 对象")
    required = {"original_summary", "compliance_check", "xiaohongshu", "toutiao", "image_prompts"}
    if not required.issubset(parsed):
        raise ApiError(HTTPStatus.BAD_GATEWAY, "模型返回结果缺少必要字段")
    if not isinstance(parsed["image_prompts"], list):
        raise ApiError(HTTPStatus.BAD_GATEWAY, "模型返回的图片提示词格式无效")
    for prompt in parsed["image_prompts"]:
        if not isinstance(prompt, dict):
            raise ApiError(HTTPStatus.BAD_GATEWAY, "模型返回的单条图片提示词格式无效")
        prompt.setdefault("scene_description", "配图")
        prompt.setdefault("prompt_en", "")
        prompt.setdefault("prompt_zh", "")
    return parsed


def call_openai_compatible(config: dict[str, Any], user_prompt: str, token_cost: int) -> tuple[str, str]:
    base_url = clean_text(config.get("base_url"), 2000) or "https://api.openai.com/v1"
    endpoint = completion_url(base_url)
    model = clean_text(config.get("model"), 200) or "gpt-4.1-mini"
    api_key = clean_text(config.get("api_key"), 2000)
    rpm = int(config.get("rpm") or 10)
    tpm = int(config.get("tpm") or 60000)
    output_tokens = max(512, min(int(config.get("output_token_budget") or 5000), 16000))
    temperature = max(0.0, min(float(config.get("temperature", 0.7)), 1.5))
    json_mode = clean_text(config.get("json_mode"), 30) or "structured"
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    modes = [json_mode]
    if json_mode == "structured":
        modes.extend(["json_object", "prompt"])
    elif json_mode == "json_object":
        modes.append("prompt")
    last_error: ApiError | None = None
    for mode in dict.fromkeys(modes):
        request_body: dict[str, Any] = {
            "model": model,
            "messages": [
                {"role": "system", "content": SYSTEM_PROMPT},
                {"role": "user", "content": user_prompt},
            ],
        }
        reasoning_model = bool(re.match(r"^(?:o[1-9]|gpt-5)", model, flags=re.IGNORECASE))
        request_body["max_completion_tokens" if reasoning_model else "max_tokens"] = output_tokens
        if not reasoning_model:
            request_body["temperature"] = temperature
        if mode == "structured":
            request_body["response_format"] = {
                "type": "json_schema",
                "json_schema": {"name": "localized_articles", "strict": True, "schema": OUTPUT_SCHEMA},
            }
        elif mode == "json_object":
            request_body["response_format"] = {"type": "json_object"}
        RATE_LIMITER.acquire(f"openai|{endpoint}|{model}", rpm, tpm, token_cost)
        try:
            response = http_json(endpoint, headers=headers, data=request_body, timeout=120)
            content = response["choices"][0]["message"]["content"]
            return clean_text(content, 500000), mode
        except ApiError as exc:
            last_error = exc
            if exc.status not in {HTTPStatus.BAD_REQUEST, HTTPStatus.UNPROCESSABLE_ENTITY} or mode == "prompt":
                raise
        except (KeyError, IndexError, TypeError) as exc:
            raise ApiError(HTTPStatus.BAD_GATEWAY, "模型响应中没有找到生成内容") from exc
    raise last_error or ApiError(HTTPStatus.BAD_GATEWAY, "模型调用失败")


def call_anthropic(config: dict[str, Any], user_prompt: str, token_cost: int) -> tuple[str | dict[str, Any], str]:
    base_url = clean_text(config.get("base_url"), 2000) or "https://api.anthropic.com/v1"
    endpoint = anthropic_url(base_url)
    model = clean_text(config.get("model"), 200) or "claude-sonnet-4-5"
    api_key = clean_text(config.get("api_key"), 2000)
    rpm = int(config.get("rpm") or 10)
    tpm = int(config.get("tpm") or 60000)
    output_tokens = max(512, min(int(config.get("output_token_budget") or 5000), 16000))
    temperature = max(0.0, min(float(config.get("temperature", 0.7)), 1.0))
    headers = {"x-api-key": api_key, "anthropic-version": "2023-06-01"}
    request_body = {
        "model": model,
        "system": SYSTEM_PROMPT,
        "messages": [{"role": "user", "content": user_prompt}],
        "temperature": temperature,
        "max_tokens": output_tokens,
        "tools": [{"name": "publish_content", "description": "Return localized article JSON", "input_schema": OUTPUT_SCHEMA}],
        "tool_choice": {"type": "tool", "name": "publish_content"},
    }
    RATE_LIMITER.acquire(f"anthropic|{endpoint}|{model}", rpm, tpm, token_cost)
    response = http_json(endpoint, headers=headers, data=request_body, timeout=120)
    for block in response.get("content", []):
        if isinstance(block, dict) and block.get("type") == "tool_use" and isinstance(block.get("input"), dict):
            return block["input"], "tool_schema"
    for block in response.get("content", []):
        if isinstance(block, dict) and block.get("type") == "text":
            return clean_text(block.get("text"), 500000), "prompt"
    raise ApiError(HTTPStatus.BAD_GATEWAY, "Claude 响应中没有找到生成内容")


def generate_content(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") or {}
    config = payload.get("config") or {}
    title = sanitize_prompt_text(source.get("title"), 1000)
    body = sanitize_prompt_text(source.get("body"), 120000)
    if not title and not body:
        raise ApiError(HTTPStatus.BAD_REQUEST, "请先选择帖子或填写待改编内容")

    api_key = clean_text(config.get("api_key"), 1000)
    base_url = clean_text(config.get("base_url"), 2000) or "https://api.openai.com/v1"
    model = clean_text(config.get("model"), 200) or "gpt-4.1-mini"
    if not api_key and "localhost" not in base_url and "127.0.0.1" not in base_url:
        raise ApiError(HTTPStatus.BAD_REQUEST, "请输入模型 API Token")
    source = {**source, "title": title, "body": body}
    source_text, budget_meta = build_user_prompt(source, config)
    output_budget = max(512, min(int(config.get("output_token_budget") or 5000), 16000))
    token_cost = budget_meta["estimated_input_tokens"] + output_budget
    provider = clean_text(config.get("provider"), 50) or "openai_compatible"
    if provider == "anthropic":
        content, output_mode = call_anthropic(config, source_text, token_cost)
    else:
        content, output_mode = call_openai_compatible(config, source_text, token_cost)
    result = content if isinstance(content, dict) else extract_json_object(content)
    if isinstance(content, dict):
        result = extract_json_object(json.dumps(content, ensure_ascii=False))
    result["meta"] = {
        "model": model,
        "provider": provider,
        "output_mode": output_mode,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_url": clean_text(source.get("url"), 2000),
        **budget_meta,
    }
    return result


class AppServer(ThreadingHTTPServer):
    static_dir: Path = STATIC_DIR


class Handler(BaseHTTPRequestHandler):
    server_version = "ChinaContentStudio/1.0"

    def log_message(self, fmt: str, *args: Any) -> None:
        print(f"[{self.log_date_time_string()}] {fmt % args}")

    def send_json(self, data: Any, status: int = HTTPStatus.OK) -> None:
        raw = json.dumps(data, ensure_ascii=False).encode("utf-8")
        try:
            self.send_response(status)
            self.send_header("Content-Type", "application/json; charset=utf-8")
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-store")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return

    def handle_error(self, exc: Exception) -> None:
        if isinstance(exc, ApiError):
            self.send_json({"error": exc.message, "detail": exc.detail}, exc.status)
        else:
            print(f"Unhandled error: {exc!r}")
            self.send_json({"error": "服务器处理请求时发生错误"}, HTTPStatus.INTERNAL_SERVER_ERROR)

    def do_GET(self) -> None:
        try:
            parsed = urllib.parse.urlparse(self.path)
            if parsed.path == "/api/health":
                self.send_json({"status": "ok", "version": "1.1.0", "quora_connector": bool(QUORA_API_BASE_URL)})
                return
            if parsed.path == "/api/categories":
                params = urllib.parse.parse_qs(parsed.query)
                source = params.get("source", ["reddit"])[0]
                categories = QUORA_CATEGORIES if source == "quora" else CATEGORIES
                self.send_json({
                    "source": source,
                    "available": source != "quora" or bool(QUORA_API_BASE_URL),
                    "categories": categories,
                    "sorts": (
                        [
                            {"id": "hot", "name": "热度排序"},
                            {"id": "upvotes", "name": "点赞最多"},
                            {"id": "comments", "name": "评论最多"},
                            {"id": "views", "name": "浏览最多"},
                            {"id": "new", "name": "最新发布"},
                        ] if source == "quora" else [
                            {"id": "hot", "name": "热度排序"},
                            {"id": "top", "name": "高赞排序"},
                            {"id": "comments", "name": "评论最多"},
                            {"id": "new", "name": "最新发布"},
                            {"id": "rising", "name": "正在上升"},
                            {"id": "views", "name": "浏览最多", "disabled": True, "reason": "Reddit 列表接口不提供浏览量"},
                        ]
                    ),
                })
                return
            if parsed.path == "/api/reddit/posts":
                params = urllib.parse.parse_qs(parsed.query)
                posts = fetch_reddit_posts(
                    params.get("community", ["popular"])[0],
                    params.get("sort", ["hot"])[0],
                    params.get("period", ["day"])[0],
                    int(params.get("limit", [20])[0]),
                    params.get("refresh", ["0"])[0] == "1",
                )
                self.send_json({"posts": posts})
                return
            if parsed.path == "/api/quora/posts":
                params = urllib.parse.parse_qs(parsed.query)
                posts = fetch_quora_posts(
                    params.get("topic", ["popular"])[0],
                    params.get("sort", ["relevance"])[0],
                    int(params.get("limit", [20])[0]),
                    params.get("refresh", ["0"])[0] == "1",
                )
                self.send_json({"posts": posts, "discovery": "authorized_connector", "metrics_available": True})
                return
            if parsed.path == "/api/reddit/post":
                params = urllib.parse.parse_qs(parsed.query)
                url = params.get("url", [""])[0]
                self.send_json({"post": fetch_reddit_post(url)})
                return
            if parsed.path == "/api/source/post":
                params = urllib.parse.parse_qs(parsed.query)
                source = params.get("source", [""])[0].lower()
                url = params.get("url", [""])[0]
                if source == "reddit":
                    post = fetch_reddit_post(url)
                elif source == "quora":
                    post = fetch_quora_post(url)
                else:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "当前仅支持自动读取 Reddit 和 Quora 链接")
                self.send_json({"post": post})
                return
            if parsed.path == "/api/source/import":
                params = urllib.parse.parse_qs(parsed.query)
                url = params.get("url", [""])[0]
                host = (urllib.parse.urlparse(url).hostname or "").lower()
                if host in {"reddit.com", "www.reddit.com", "old.reddit.com", "redd.it"}:
                    post = fetch_reddit_post(url)
                elif host == "quora.com" or host.endswith(".quora.com"):
                    post = fetch_quora_post(url)
                else:
                    raise ApiError(HTTPStatus.BAD_REQUEST, "该链接暂不支持自动读取，请使用 Reddit 或 Quora 帖子链接")
                self.send_json({"post": post})
                return
            self.serve_static(parsed.path)
        except (ValueError, TypeError):
            self.send_json({"error": "请求参数格式错误"}, HTTPStatus.BAD_REQUEST)
        except Exception as exc:
            self.handle_error(exc)

    def do_POST(self) -> None:
        try:
            if self.path != "/api/generate":
                raise ApiError(HTTPStatus.NOT_FOUND, "接口不存在")
            length = int(self.headers.get("Content-Length") or 0)
            if length <= 0 or length > MAX_BODY_BYTES:
                raise ApiError(HTTPStatus.REQUEST_ENTITY_TOO_LARGE, "请求内容为空或超过 2 MB")
            try:
                payload = json.loads(self.rfile.read(length).decode("utf-8"))
            except (UnicodeDecodeError, json.JSONDecodeError) as exc:
                raise ApiError(HTTPStatus.BAD_REQUEST, "请求 JSON 格式无效") from exc
            if not isinstance(payload, dict):
                raise ApiError(HTTPStatus.BAD_REQUEST, "请求内容必须是 JSON 对象")
            self.send_json(generate_content(payload))
        except Exception as exc:
            self.handle_error(exc)

    def serve_static(self, url_path: str) -> None:
        relative = "index.html" if url_path in {"", "/"} else urllib.parse.unquote(url_path.lstrip("/"))
        candidate = (STATIC_DIR / relative).resolve()
        if STATIC_DIR.resolve() not in candidate.parents and candidate != STATIC_DIR.resolve():
            raise ApiError(HTTPStatus.FORBIDDEN, "禁止访问该路径")
        if not candidate.is_file():
            raise ApiError(HTTPStatus.NOT_FOUND, "页面不存在")
        raw = candidate.read_bytes()
        content_type = mimetypes.guess_type(candidate.name)[0] or "application/octet-stream"
        try:
            self.send_response(HTTPStatus.OK)
            self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
            self.send_header("Content-Length", str(len(raw)))
            self.send_header("Cache-Control", "no-cache")
            self.send_header("X-Content-Type-Options", "nosniff")
            self.send_header("Referrer-Policy", "no-referrer")
            self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' https://unpkg.com; img-src 'self' data: https:; style-src 'self'; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'")
            self.end_headers()
            self.wfile.write(raw)
        except (BrokenPipeError, ConnectionResetError, ConnectionAbortedError):
            return


def main() -> None:
    parser = argparse.ArgumentParser(description="海外热帖本土化内容工作台")
    parser.add_argument("--host", default="127.0.0.1")
    parser.add_argument("--port", type=int, default=8765)
    args = parser.parse_args()
    server = AppServer((args.host, args.port), Handler)
    print(f"内容工作台已启动：http://{args.host}:{args.port}")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\n正在停止服务...")
    finally:
        server.server_close()


if __name__ == "__main__":
    main()
