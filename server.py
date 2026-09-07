from __future__ import annotations

import argparse
import html
import json
import mimetypes
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
9. 生成 3-5 个英文图片提示词。画面应与文章段落匹配、写实、细节明确，避免品牌商标、平台 UI、水印和画面内文字。

只输出一个合法 JSON 对象，不得使用 Markdown 代码围栏，不得在 JSON 外添加说明。固定结构：
{
  "original_summary": "原帖核心内容一句话总结",
  "compliance_check": "合规修改说明；无调整则写完全合规",
  "xiaohongshu": {"title": "标题或空字符串", "content": "正文或空字符串"},
  "toutiao": {"title": "标题或空字符串", "content": "正文或空字符串"},
  "image_prompts": [
    {"scene_description": "中文应用场景", "prompt_en": "Detailed English prompt..."}
  ]
}
"""


class ApiError(Exception):
    def __init__(self, status: int, message: str, detail: str | None = None):
        super().__init__(message)
        self.status = status
        self.message = message
        self.detail = detail


class RateLimiter:
    def __init__(self) -> None:
        self._calls: dict[str, deque[float]] = defaultdict(deque)
        self._lock = threading.Lock()

    def acquire(self, key: str, rpm: int) -> None:
        rpm = max(1, min(rpm, 120))
        while True:
            with self._lock:
                now = time.monotonic()
                calls = self._calls[key]
                while calls and now - calls[0] >= 60:
                    calls.popleft()
                if len(calls) < rpm:
                    calls.append(now)
                    return
                wait_for = max(0.05, 60 - (now - calls[0]))
            time.sleep(min(wait_for, 1.0))


RATE_LIMITER = RateLimiter()
REDDIT_CACHE: dict[str, tuple[float, list[dict[str, Any]]]] = {}
REDDIT_CACHE_LOCK = threading.Lock()
REDDIT_CACHE_SECONDS = 300


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


def http_text(url: str, *, timeout: int = 25) -> str:
    request = urllib.request.Request(
        url,
        headers={
            "User-Agent": USER_AGENT,
            "Accept": "application/atom+xml, application/xml;q=0.9, text/xml;q=0.8",
        },
    )
    try:
        with urllib.request.urlopen(request, timeout=timeout) as response:
            raw = response.read(MAX_BODY_BYTES + 1)
            if len(raw) > MAX_BODY_BYTES:
                raise ApiError(HTTPStatus.BAD_GATEWAY, "Reddit RSS 响应超过 2 MB")
            return raw.decode("utf-8")
    except urllib.error.HTTPError as exc:
        raise ApiError(exc.code, "Reddit RSS 请求失败") from exc
    except urllib.error.URLError as exc:
        raise ApiError(HTTPStatus.BAD_GATEWAY, "无法连接 Reddit RSS", str(exc.reason)) from exc
    except UnicodeDecodeError as exc:
        raise ApiError(HTTPStatus.BAD_GATEWAY, "Reddit RSS 编码异常") from exc


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
        "title": clean_text(data.get("title"), 600),
        "body": clean_text(data.get("selftext")),
        "author": clean_text(data.get("author"), 100),
        "community": clean_text(data.get("subreddit"), 100),
        "score": int(data.get("score") or 0),
        "comments_count": int(data.get("num_comments") or 0),
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
            "title": title,
            "body": body,
            "author": author,
            "community": community,
            "score": 0,
            "comments_count": 0,
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
    sort = sort if sort in {"hot", "top", "new", "rising"} else "hot"
    period = period if period in {"hour", "day", "week", "month", "year", "all"} else "day"
    limit = max(5, min(limit, 50))
    try:
        payload = http_json(reddit_url(f"/r/{community}/{sort}.json", {"limit": limit, "t": period, "raw_json": 1}))
        children = payload.get("data", {}).get("children", [])
        return [post for child in children if safe_for_discovery(post := post_from_child(child))]
    except ApiError as exc:
        if exc.status not in {HTTPStatus.FORBIDDEN, HTTPStatus.NOT_FOUND, HTTPStatus.TOO_MANY_REQUESTS}:
            raise
        return fetch_reddit_rss_posts(community, sort, period, limit)


def fetch_reddit_posts(community: str, sort: str, period: str, limit: int) -> list[dict[str, Any]]:
    community = re.sub(r"[^A-Za-z0-9_]+", "", community) or "popular"
    sort = sort if sort in {"hot", "top", "new", "rising"} else "hot"
    period = period if period in {"hour", "day", "week", "month", "year", "all"} else "day"
    limit = max(5, min(limit, 50))
    key = f"{community.lower()}|{sort}|{period}|{limit}"
    with REDDIT_CACHE_LOCK:
        cached = REDDIT_CACHE.get(key)
        now = time.monotonic()
        if cached and now - cached[0] < REDDIT_CACHE_SECONDS:
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
    return parsed


def generate_content(payload: dict[str, Any]) -> dict[str, Any]:
    source = payload.get("source") or {}
    config = payload.get("config") or {}
    title = clean_text(source.get("title"), 800)
    body = clean_text(source.get("body"), 24000)
    comments = source.get("comments") if isinstance(source.get("comments"), list) else []
    if not title and not body:
        raise ApiError(HTTPStatus.BAD_REQUEST, "请先选择帖子或填写待改编内容")

    api_key = clean_text(config.get("api_key"), 1000)
    base_url = clean_text(config.get("base_url"), 2000) or "https://api.openai.com/v1"
    model = clean_text(config.get("model"), 200) or "gpt-4.1-mini"
    rpm = int(config.get("rpm") or 10)
    temperature = float(config.get("temperature") if config.get("temperature") is not None else 0.7)
    temperature = max(0.0, min(temperature, 1.5))
    if not api_key and "localhost" not in base_url and "127.0.0.1" not in base_url:
        raise ApiError(HTTPStatus.BAD_REQUEST, "请输入模型 API Token")

    targets = payload.get("targets") or ["xiaohongshu", "toutiao"]
    target_label = {"xiaohongshu": "小红书", "toutiao": "今日头条"}
    selected = [target_label[item] for item in targets if item in target_label]
    if not selected:
        raise ApiError(HTTPStatus.BAD_REQUEST, "请至少选择一个发布平台")

    comment_text = "\n\n".join(
        f"热门评论 {index + 1}（点赞 {int(item.get('score') or 0)}）：{clean_text(item.get('body'), 3000)}"
        for index, item in enumerate(comments[:10]) if isinstance(item, dict) and clean_text(item.get("body"))
    )
    source_text = (
        f"来源平台：{clean_text(source.get('platform'), 100) or '海外论坛'}\n"
        f"来源链接：{clean_text(source.get('url'), 2000) or '未提供'}\n"
        f"目标平台：{'、'.join(selected)}。未选择的平台请将 title 和 content 输出为空字符串。\n"
        f"标题：{title}\n\n正文：\n{body or '原帖无正文，请仅根据标题与评论谨慎提炼，不得补造情节。'}\n\n"
        f"热门评论：\n{comment_text or '未提供热门评论。'}"
    )

    endpoint = completion_url(base_url)
    RATE_LIMITER.acquire(f"{endpoint}|{model}", rpm)
    headers = {"Authorization": f"Bearer {api_key}"} if api_key else {}
    request_body = {
        "model": model,
        "messages": [
            {"role": "system", "content": SYSTEM_PROMPT},
            {"role": "user", "content": source_text},
        ],
        "temperature": temperature,
    }
    response = http_json(endpoint, headers=headers, data=request_body, timeout=120)
    try:
        content = response["choices"][0]["message"]["content"]
    except (KeyError, IndexError, TypeError) as exc:
        detail = json.dumps(response, ensure_ascii=False)[:800]
        raise ApiError(HTTPStatus.BAD_GATEWAY, "模型响应中没有找到生成内容", detail) from exc
    result = extract_json_object(content)
    result["meta"] = {
        "model": model,
        "generated_at": datetime.now(timezone.utc).isoformat(),
        "source_url": clean_text(source.get("url"), 2000),
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
        self.send_response(status)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("Cache-Control", "no-store")
        self.send_header("X-Content-Type-Options", "nosniff")
        self.end_headers()
        self.wfile.write(raw)

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
                self.send_json({"status": "ok", "version": "1.0.0"})
                return
            if parsed.path == "/api/categories":
                self.send_json({"categories": CATEGORIES})
                return
            if parsed.path == "/api/reddit/posts":
                params = urllib.parse.parse_qs(parsed.query)
                posts = fetch_reddit_posts(
                    params.get("community", ["popular"])[0],
                    params.get("sort", ["hot"])[0],
                    params.get("period", ["day"])[0],
                    int(params.get("limit", [20])[0]),
                )
                self.send_json({"posts": posts})
                return
            if parsed.path == "/api/reddit/post":
                params = urllib.parse.parse_qs(parsed.query)
                url = params.get("url", [""])[0]
                self.send_json({"post": fetch_reddit_post(url)})
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
        self.send_response(HTTPStatus.OK)
        self.send_header("Content-Type", f"{content_type}; charset=utf-8" if content_type.startswith("text/") else content_type)
        self.send_header("Content-Length", str(len(raw)))
        self.send_header("X-Content-Type-Options", "nosniff")
        self.send_header("Referrer-Policy", "no-referrer")
        self.send_header("Content-Security-Policy", "default-src 'self'; script-src 'self' https://unpkg.com; img-src 'self' data: https:; style-src 'self'; connect-src 'self'; font-src 'self'; object-src 'none'; base-uri 'none'")
        self.end_headers()
        self.wfile.write(raw)


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
