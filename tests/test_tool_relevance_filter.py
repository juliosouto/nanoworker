"""Tests for the tool relevance filter (TOOL_RELEVANCE_FILTER).

When on, the filter is a RAG over the tool catalog: tool name + short
description are embedded with the local embeddings and the top-k tools most
similar to the user's message are kept (plus their module siblings). When off,
every tool is sent. Core contract: FAIL-OPEN — any problem returns the
ORIGINAL tool list unchanged.
"""
import os
import sys
import unittest
from unittest.mock import patch

sys.path.append(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from agent.lc import tools_lc
from agent.lc.tools_lc import filter_tools_by_relevance

# One axis per topic; the fake embedder maps text to these keywords.
_TOPICS = ["web", "file", "mail", "weather", "photo", "browser"]


class KeywordEmbeddings:
    """Deterministic stand-in for HuggingFaceEmbeddings: one dimension per topic."""

    def __init__(self):
        self.documents_calls = 0

    def _vec(self, text):
        t = text.lower()
        vec = [1.0 if k in t else 0.0 for k in _TOPICS]
        return vec + [0.01]  # never a zero vector

    def embed_documents(self, texts):
        self.documents_calls += 1
        return [self._vec(t) for t in texts]

    def embed_query(self, text):
        return self._vec(text)


def _tool(name, doc, module):
    def f():
        return name

    f.__name__ = name
    f.__doc__ = doc
    f.__module__ = module
    return f


search_web = _tool("search_web", "Searches the web.", "tools.web_search")
read_file = _tool("read_file", "Reads a file from disk.", "tools.files")
send_mail = _tool("send_mail", "Sends an e-mail message.", "tools.mail")
get_weather = _tool("get_weather", "Gets the weather forecast.", "tools.weather")
get_photos = _tool("get_photos", "Lists recent photos.", "tools.photos")
browser_navigate = _tool("browser_navigate", "Opens a URL in the browser.", "tools.browser")
browser_snapshot = _tool("browser_snapshot", "Returns the page DOM.", "tools.browser")

ALL_TOOLS = [
    search_web, read_file, send_mail, get_weather, get_photos,
    browser_navigate, browser_snapshot,
]


class TestToolRelevanceFilter(unittest.TestCase):
    def setUp(self):
        tools_lc._TOOL_VECTOR_CACHE.clear()
        self.emb = KeywordEmbeddings()
        patches = [
            patch("agent.lc.settings.tool_relevance_filter", return_value=True),
            patch("agent.lc.settings.tool_relevance_top_k", return_value=2),
            patch("agent.lc.embeddings.get_embeddings", return_value=self.emb),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)

    def test_disabled_sends_all_tools_without_embedding(self):
        with patch("agent.lc.settings.tool_relevance_filter", return_value=False), patch(
            "agent.lc.embeddings.get_embeddings"
        ) as get_emb:
            result = filter_tools_by_relevance(ALL_TOOLS, "what's the weather?")
        self.assertIs(result, ALL_TOOLS)
        get_emb.assert_not_called()

    def test_keeps_most_similar_tools(self):
        result = filter_tools_by_relevance(ALL_TOOLS, "weather and mail please")
        self.assertEqual(result, [send_mail, get_weather])

    def test_module_siblings_are_added(self):
        result = filter_tools_by_relevance(ALL_TOOLS, "open the browser on that web page")
        self.assertEqual(result, [search_web, browser_navigate, browser_snapshot])

    def test_tool_vectors_are_cached(self):
        filter_tools_by_relevance(ALL_TOOLS, "weather")
        filter_tools_by_relevance(ALL_TOOLS, "mail")
        self.assertEqual(self.emb.documents_calls, 1)

    def test_fewer_tools_than_top_k_returns_all(self):
        tools = [search_web, read_file]
        self.assertIs(filter_tools_by_relevance(tools, "weather"), tools)

    def test_empty_message_returns_all(self):
        self.assertIs(filter_tools_by_relevance(ALL_TOOLS, "   "), ALL_TOOLS)

    def test_embeddings_unavailable_returns_all(self):
        with patch("agent.lc.embeddings.get_embeddings", return_value=None):
            self.assertIs(filter_tools_by_relevance(ALL_TOOLS, "weather"), ALL_TOOLS)

    def test_embedding_error_returns_all(self):
        with patch.object(self.emb, "embed_query", side_effect=RuntimeError("boom")):
            self.assertIs(filter_tools_by_relevance(ALL_TOOLS, "weather"), ALL_TOOLS)

    def test_empty_tool_list_returns_empty(self):
        self.assertEqual(filter_tools_by_relevance([], "hello"), [])

    def test_always_keep_adds_tools_whatever_their_score(self):
        result = filter_tools_by_relevance(
            ALL_TOOLS, "weather and mail please",
            always_keep=lambda f: f.__module__ == "tools.photos",
        )
        self.assertEqual(result, [send_mail, get_weather, get_photos])

    def test_multimodal_content_uses_text_parts(self):
        content = [{"type": "image"}, {"type": "text", "text": "weather and mail"}]
        result = filter_tools_by_relevance(ALL_TOOLS, content)
        self.assertEqual(result, [send_mail, get_weather])


if __name__ == "__main__":
    unittest.main()
