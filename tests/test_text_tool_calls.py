"""Tool calls written as text by the model (e.g. Qwen) are executed, not sent."""

import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage
from langchain_core.tools import StructuredTool

from agent.lc import runner
from agent.lc.text_tool_calls import recover_text_tool_calls
from test_lc_runner import (
    ScriptedToolCallingModel,
    _collect_feedback,
    _history,
    _patch_config,
    _patch_model,
)

# Exactly what Qwen sent to WhatsApp instead of searching.
QWEN_TEXT = """<tool_call>
<function=web_search>
<parameter=country>
US
</parameter>
<parameter=language>
en
</parameter>
<parameter=query>
Arena Breakout Infinite PC single player multiplayer modes
</parameter>
</function>
</tool_call>"""


def web_search(query: str, country: str = "", language: str = "") -> str:
    """Search the web."""
    return f"results for {query} ({country}/{language})"


def set_volume(level: int) -> str:
    """Set the volume."""
    return f"volume {level}"


TOOLS = [
    StructuredTool.from_function(web_search),
    StructuredTool.from_function(set_volume),
]


class TestRecoverTextToolCalls(unittest.TestCase):
    def test_qwen_xml_block_becomes_tool_call(self):
        fixed = recover_text_tool_calls(AIMessage(content=QWEN_TEXT), TOOLS)
        self.assertEqual(fixed.content, "")
        self.assertEqual(len(fixed.tool_calls), 1)
        call = fixed.tool_calls[0]
        self.assertEqual(call["name"], "web_search")
        self.assertEqual(call["args"], {
            "country": "US",
            "language": "en",
            "query": "Arena Breakout Infinite PC single player multiplayer modes",
        })

    def test_hermes_json_block_becomes_tool_call(self):
        text = 'Vou buscar.\n<tool_call>{"name": "web_search", "arguments": {"query": "x"}}</tool_call>'
        fixed = recover_text_tool_calls(AIMessage(content=text), TOOLS)
        self.assertEqual(fixed.content, "Vou buscar.")
        self.assertEqual(fixed.tool_calls[0]["args"], {"query": "x"})

    def test_non_string_parameter_is_decoded_from_schema(self):
        text = "<tool_call><function=set_volume><parameter=level>7</parameter></function></tool_call>"
        fixed = recover_text_tool_calls(AIMessage(content=text), TOOLS)
        self.assertEqual(fixed.tool_calls[0]["args"], {"level": 7})

    def test_string_parameter_that_looks_numeric_stays_string(self):
        text = "<tool_call><function=web_search><parameter=query>2026</parameter></function></tool_call>"
        fixed = recover_text_tool_calls(AIMessage(content=text), TOOLS)
        self.assertEqual(fixed.tool_calls[0]["args"], {"query": "2026"})

    def test_missing_closing_tag_is_tolerated(self):
        truncated = QWEN_TEXT.replace("</tool_call>", "")
        fixed = recover_text_tool_calls(AIMessage(content=truncated), TOOLS)
        self.assertEqual(fixed.tool_calls[0]["name"], "web_search")

    def test_unknown_tool_leaves_message_unchanged(self):
        msg = AIMessage(content=QWEN_TEXT.replace("web_search", "rm_rf"))
        self.assertIs(recover_text_tool_calls(msg, TOOLS), msg)

    def test_plain_text_and_structured_calls_are_untouched(self):
        plain = AIMessage(content="Olá")
        self.assertIs(recover_text_tool_calls(plain, TOOLS), plain)
        structured = AIMessage(
            content=QWEN_TEXT,
            tool_calls=[{"name": "web_search", "args": {"query": "a"}, "id": "1"}],
        )
        self.assertIs(recover_text_tool_calls(structured, TOOLS), structured)


class TestRunnerExecutesTextToolCalls(unittest.TestCase):
    """End to end: the search runs and the user gets the final answer."""

    def _run(self, flow):
        scripted = ScriptedToolCallingModel(
            responses=[AIMessage(content=QWEN_TEXT), AIMessage(content="DONE")]
        )
        feedback, fb_side = _collect_feedback()
        with _patch_model(scripted), _patch_config(), patch(
            "agent.db_feedback.insert_feedback", side_effect=fb_side
        ), patch.object(runner.lc_settings, "agent_flow", return_value=flow):
            out = runner.run_langchain_llm(
                "qwen3.8-27b",
                _history([("user", "hi")]),
                {"system_instruction": "sys", "tools": [web_search], "show_tools_results": True},
                "query",
                None,
                "sid",
                "mid",
                "messages_out",
                provider="openai",
                api_key="k",
            )
        return out, feedback

    def test_legacy_flow(self):
        out, feedback = self._run("legacy")
        self.assertEqual(out, "DONE")
        self.assertTrue(any("results for Arena Breakout" in f for f in feedback))

    def test_graph_flow(self):
        out, feedback = self._run("graph")
        self.assertEqual(out, "DONE")
        self.assertTrue(any("results for Arena Breakout" in f for f in feedback))


if __name__ == "__main__":
    unittest.main()
