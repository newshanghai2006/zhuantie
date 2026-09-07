import json
import unittest
from unittest.mock import patch

import server


class ServerTests(unittest.TestCase):
    def test_post_parser_filters_and_normalizes_fields(self):
        child = {
            "data": {
                "id": "abc123",
                "title": "A useful thread",
                "selftext": "Body",
                "author": "writer",
                "subreddit": "LifeProTips",
                "score": 1530,
                "num_comments": 42,
                "created_utc": 1_700_000_000,
                "permalink": "/r/test/comments/abc123/a_useful_thread/",
                "thumbnail": "self",
                "is_self": True,
                "over_18": False,
            }
        }
        post = server.post_from_child(child)
        self.assertEqual(post["id"], "abc123")
        self.assertEqual(post["permalink"], "https://www.reddit.com/r/test/comments/abc123/a_useful_thread/")
        self.assertEqual(post["thumbnail"], "")
        self.assertFalse(post["nsfw"])

    def test_discovery_filter_blocks_sensitive_topics(self):
        self.assertFalse(server.safe_for_discovery({"title": "A violent shooting story", "body": "", "nsfw": False}))
        self.assertFalse(server.safe_for_discovery({"title": "The UN announced a new policy", "body": "", "nsfw": False}))
        self.assertFalse(server.safe_for_discovery({"title": "Pentagon statement about soldiers in an armed conflict", "body": "", "nsfw": False}))
        self.assertTrue(server.safe_for_discovery({"title": "A useful cooking technique", "body": "", "nsfw": False}))

    @patch.object(server, "_fetch_reddit_posts_uncached")
    def test_reddit_list_uses_short_lived_cache(self, mock_fetch):
        mock_fetch.return_value = [{"id": "cached"}]
        server.REDDIT_CACHE.clear()
        first = server.fetch_reddit_posts("test", "hot", "day", 5)
        second = server.fetch_reddit_posts("test", "hot", "day", 5)
        self.assertEqual(first, second)
        mock_fetch.assert_called_once()

    def test_reddit_url_rejects_untrusted_domain(self):
        with self.assertRaises(server.ApiError):
            server.normalize_reddit_permalink("https://example.com/r/test/comments/abc")

    def test_quora_url_rejects_lookalike_domain(self):
        with self.assertRaises(server.ApiError):
            server.normalize_quora_url("https://quora.com.evil.example/question")

    def test_quora_connector_requires_authorized_endpoint(self):
        with patch.object(server, "QUORA_API_BASE_URL", ""):
            with self.assertRaisesRegex(server.ApiError, "授权"):
                server.quora_connector_url("/posts", {"topic": "technology"})

    def test_quora_connector_post_is_normalized_and_cleaned(self):
        post = server.normalize_quora_connector_post({
            "question": "How can I learn efficiently?",
            "answer": "Use feedback loops.",
            "url": "https://www.quora.com/How-can-I-learn-efficiently?tracking=1",
            "upvotes": 25,
            "views": 300,
            "comments": [
                {"text": "Useful answer", "upvotes": 8},
                {"text": "[deleted]", "upvotes": 100},
            ],
        }, "education")
        self.assertEqual(post["source"], "quora")
        self.assertEqual(post["score"], 25)
        self.assertEqual(post["view_count"], 300)
        self.assertEqual(len(post["comments"]), 1)
        self.assertNotIn("tracking", post["permalink"])

    @patch.object(server, "http_json")
    def test_quora_connector_forwards_sort_and_normalizes_posts(self, mock_http_json):
        mock_http_json.return_value = {"posts": [{
            "title": "Useful technology question",
            "body": "A detailed answer",
            "url": "https://www.quora.com/Useful-technology-question",
            "views": 1200,
        }]}
        server.QUORA_CACHE.clear()
        with patch.object(server, "QUORA_API_BASE_URL", "https://licensed.example/v1"):
            posts = server.fetch_quora_posts("technology", "views", 10)
        self.assertEqual(posts[0]["view_count"], 1200)
        self.assertIn("sort=views", mock_http_json.call_args.args[0])

    @patch.object(server, "http_text")
    def test_reddit_post_uses_rss_entries_for_comments(self, mock_http_text):
        mock_http_text.return_value = """<feed xmlns="http://www.w3.org/2005/Atom">
          <entry><author><name>/u/poster</name></author><content type="html">Post body</content><id>t3_abc</id><link href="https://www.reddit.com/r/test/comments/abc/post/"/><published>2026-09-07T00:00:00Z</published><title>Post title</title></entry>
          <entry><author><name>/u/commenter</name></author><content type="html">Helpful comment</content><id>t1_def</id><link href="https://www.reddit.com/r/test/comments/abc/post/def/"/><published>2026-09-07T01:00:00Z</published><title>Comment</title></entry>
        </feed>"""
        post = server.fetch_reddit_rss_post("https://www.reddit.com/r/test/comments/abc/post/")
        self.assertEqual(post["title"], "Post title")
        self.assertEqual(post["comments"][0]["body"], "Helpful comment")

    def test_cached_post_lookup_matches_permalink_path(self):
        server.REDDIT_CACHE.clear()
        server.REDDIT_CACHE["test"] = (0, [{"id": "abc", "permalink": "https://www.reddit.com/r/test/comments/abc/post/"}])
        post = server.find_cached_reddit_post("https://reddit.com/r/test/comments/abc/post/?utm_source=x")
        self.assertEqual(post["id"], "abc")

    def test_extract_json_accepts_code_fence(self):
        value = {
            "original_summary": "summary",
            "compliance_check": "完全合规",
            "xiaohongshu": {"title": "x", "content": "y"},
            "toutiao": {"title": "a", "content": "b"},
            "image_prompts": [],
        }
        result = server.extract_json_object(f"```json\n{json.dumps(value)}\n```")
        self.assertEqual(result["original_summary"], "summary")
        self.assertEqual(result["image_prompts"], [])

    def test_prompt_cleaning_removes_deleted_links_and_images(self):
        value = "Read [this](/r/test) https://reddit.com/r/test/a image https://a.test/pic.jpg"
        cleaned = server.sanitize_prompt_text(value)
        self.assertNotIn("reddit.com", cleaned)
        self.assertNotIn("pic.jpg", cleaned)
        self.assertEqual(server.sanitize_prompt_text("[deleted]"), "")

    def test_user_prompt_sorts_comments_and_uses_budget(self):
        prompt, meta = server.build_user_prompt({
            "platform": "Quora",
            "community": "technology",
            "title": "Question",
            "body": "Body",
            "comment_sort": "score",
            "comment_limit": 5,
            "comments": [
                {"body": "lower score", "score": 2},
                {"body": "higher score", "score": 20},
                {"body": "[removed]", "score": 100},
            ],
        }, {"input_token_budget": 2000})
        self.assertLess(prompt.index("higher score"), prompt.index("lower score"))
        self.assertIn("小红书", prompt)
        self.assertIn("今日头条", prompt)
        self.assertEqual(meta["comments_used"], 2)

    def test_parse_reddit_atom_feed(self):
        xml = """<?xml version="1.0" encoding="UTF-8"?>
        <feed xmlns="http://www.w3.org/2005/Atom">
          <entry>
            <author><name>/u/writer</name></author>
            <content type="html">&lt;div&gt;&lt;p&gt;Useful body&lt;/p&gt;&lt;/div&gt;</content>
            <id>t3_abc123</id>
            <link href="https://www.reddit.com/r/test/comments/abc123/post/" />
            <published>2026-09-07T00:00:00+00:00</published>
            <title>A useful post</title>
          </entry>
        </feed>"""
        posts = server.parse_reddit_feed(xml, "test")
        self.assertEqual(len(posts), 1)
        self.assertEqual(posts[0]["id"], "abc123")
        self.assertEqual(posts[0]["body"], "Useful body")
        self.assertTrue(posts[0]["feed_fallback"])

    def test_generate_requires_token_for_remote_model(self):
        payload = {
            "source": {"title": "Title", "body": "Body"},
            "config": {"base_url": "https://api.example.com/v1", "model": "test"},
        }
        with self.assertRaisesRegex(server.ApiError, "Token"):
            server.generate_content(payload)

    @patch.object(server.RATE_LIMITER, "acquire")
    @patch.object(server, "http_json")
    def test_generate_builds_structured_result(self, mock_http_json, mock_acquire):
        generated = {
            "original_summary": "核心内容",
            "compliance_check": "完全合规",
            "xiaohongshu": {"title": "标题", "content": "正文"},
            "toutiao": {"title": "头条标题", "content": "头条正文"},
            "image_prompts": [{
                "scene_description": "场景",
                "prompt_en": "Realistic editorial scene",
                "prompt_zh": "写实编辑场景",
            }],
        }
        mock_http_json.return_value = {
            "choices": [{"message": {"content": json.dumps(generated, ensure_ascii=False)}}]
        }
        payload = {
            "source": {"platform": "Reddit", "title": "Title", "body": "Body", "comments": []},
            "config": {
                "base_url": "https://api.example.com/v1",
                "model": "test-model",
                "api_key": "test-token-placeholder",
                "rpm": 5,
                "tpm": 60000,
                "json_mode": "structured",
            },
        }
        result = server.generate_content(payload)
        self.assertEqual(result["xiaohongshu"]["title"], "标题")
        self.assertEqual(result["toutiao"]["title"], "头条标题")
        self.assertEqual(result["image_prompts"][0]["prompt_zh"], "写实编辑场景")
        self.assertEqual(result["meta"]["model"], "test-model")
        request_payload = mock_http_json.call_args.kwargs["data"]
        self.assertIn("同时生成", request_payload["messages"][1]["content"])
        self.assertEqual(request_payload["response_format"]["type"], "json_schema")
        mock_acquire.assert_called_once()

    @patch.object(server.RATE_LIMITER, "acquire")
    @patch.object(server, "http_json")
    def test_openai_structured_output_falls_back_to_json_mode(self, mock_http_json, mock_acquire):
        generated = {
            "original_summary": "summary",
            "compliance_check": "完全合规",
            "xiaohongshu": {"title": "x", "content": "x"},
            "toutiao": {"title": "t", "content": "t"},
            "image_prompts": [],
        }
        mock_http_json.side_effect = [
            server.ApiError(400, "unsupported response format"),
            {"choices": [{"message": {"content": json.dumps(generated)}}]},
        ]
        content, mode = server.call_openai_compatible({
            "base_url": "https://api.example.com/v1",
            "model": "test",
            "api_key": "test-token-placeholder",
            "json_mode": "structured",
        }, "prompt", 1000)
        self.assertEqual(mode, "json_object")
        self.assertIn("summary", content)
        self.assertEqual(mock_http_json.call_count, 2)
        self.assertEqual(mock_acquire.call_count, 2)

    @patch.object(server.RATE_LIMITER, "acquire")
    @patch.object(server, "http_json")
    def test_anthropic_uses_tool_schema(self, mock_http_json, mock_acquire):
        generated = {
            "original_summary": "summary",
            "compliance_check": "完全合规",
            "xiaohongshu": {"title": "x", "content": "x"},
            "toutiao": {"title": "t", "content": "t"},
            "image_prompts": [],
        }
        mock_http_json.return_value = {"content": [{"type": "tool_use", "input": generated}]}
        content, mode = server.call_anthropic({
            "base_url": "https://api.anthropic.com/v1",
            "model": "claude-test",
            "api_key": "test-token-placeholder",
        }, "prompt", 1000)
        self.assertEqual(mode, "tool_schema")
        self.assertEqual(content["original_summary"], "summary")
        self.assertIn("input_schema", mock_http_json.call_args.kwargs["data"]["tools"][0])
        mock_acquire.assert_called_once()


if __name__ == "__main__":
    unittest.main()
