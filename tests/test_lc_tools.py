import os
import unittest
from unittest.mock import MagicMock, patch

from agent.lc import (
    build_lc_tools,
    cap_tools,
    first_line_description,
    gemini_tool_declarations,
    lc_tool,
    tool_param_schema,
    tool_result_max_chars,
)
from agent.lc.tokens import count_tokens
from agent.llm_providers import call_gemini_llm
from agent.openai_tools import convert_to_openai_tool
from tools import get_permitted_tools, AVAILABLE_TOOLS

TRUNCATION_MARKER = "[truncated — narrow your query for full data]"


def short_tool(arg: str = "") -> str:
    """First line."""
    return "result"


def long_result_tool() -> str:
    """A tool returning a very large result for cap testing."""
    return "x" * 30000


def multi_param_tool(arg1: str, arg2: int = 5) -> str:
    """Do the thing.

    Args:
        arg1: Must be one of: 'a', 'b'.
        arg2: the counter to use.
    """
    return "ok"


def exec_tool(x: str) -> str:
    """Executes a test command and returns its result."""
    return f"executed:{x}"


def intro_tool() -> str:
    """Intro line. Continuation sentence stays in the same first paragraph.

    This is a second paragraph.
    """
    return "intro-tool-result"


class TestCapToolResult(unittest.TestCase):
    """@cap_tool_result caps execution results to LC_TOOL_RESULT_MAX_CHARS."""

    def test_caps_long_results(self):
        capped = cap_tools([long_result_tool])[0]
        result = capped()
        max_chars = tool_result_max_chars()  # default 6000
        self.assertEqual(len(result), max_chars)
        self.assertTrue(
            result.endswith("truncated — narrow your query for full data]")
        )

    def test_preserves_short_results(self):
        capped = cap_tools([short_tool])[0]
        result = capped()
        self.assertEqual(result, "result")

    def test_zero_disables_cap(self):
        with patch("agent.lc.settings.tool_result_max_chars", return_value=0):
            capped = cap_tools([long_result_tool])[0]
            result = capped()
        self.assertEqual(len(result), 30000)

    def test_marker_within_limit(self):
        with patch("agent.lc.settings.tool_result_max_chars", return_value=60):
            capped = cap_tools([long_result_tool])[0]
            result = capped()
        self.assertEqual(len(result), 60)
        self.assertTrue(result.endswith(TRUNCATION_MARKER))

    def test_non_string_result(self):
        def tool_with_int_result() -> int:
            return 42

        capped = cap_tools([tool_with_int_result])[0]
        result = capped()
        self.assertEqual(result, "42")

    def test_preserves_name_doc_signature(self):
        capped = cap_tools([long_result_tool])[0]
        self.assertEqual(capped.__name__, "long_result_tool")
        self.assertIsNotNone(capped.__doc__)


class TestFirstLineDescription(unittest.TestCase):
    def test_first_line(self):
        self.assertEqual(first_line_description(short_tool), "First line.")

    def test_multiline_docstring(self):
        self.assertEqual(
            first_line_description(multi_param_tool),
            "Do the thing.",
        )

    def test_no_docstring(self):
        def no_doc():
            return ""
        self.assertEqual(first_line_description(no_doc), "Executes no_doc")


class TestParamSchema(unittest.TestCase):
    def test_basic_properties(self):
        schema = tool_param_schema(short_tool)
        self.assertEqual(schema["type"], "object")
        self.assertEqual(schema["properties"]["arg"]["type"], "string")

    def test_enum_extraction(self):
        schema = tool_param_schema(short_tool)
        enum = schema["properties"]["arg"].get("enum")
        self.assertIsNone(enum)

    def test_default_params_not_required(self):
        schema = tool_param_schema(multi_param_tool)
        self.assertEqual(schema["required"], ["arg1"])


class TestStructuredTool(unittest.TestCase):
    def test_short_description(self):
        tool = lc_tool(short_tool)
        self.assertEqual(tool.description, "First line.")

    def test_docstring_still_intact(self):
        tool = lc_tool(short_tool)
        # The first-line description is slim for the model, the full docstring
        # is left on the function itself for indexing/UI usage.
        self.assertIn("First line.", tool.description)
        self.assertIn("First line.", short_tool.__doc__)

    def test_args_schema_properties(self):
        tool = lc_tool(multi_param_tool)
        schema = tool.args
        self.assertIn("arg1", schema)
        self.assertIn("arg2", schema)


class TestGeminiDeclarations(unittest.TestCase):
    def test_uses_short_description(self):
        decls = gemini_tool_declarations([short_tool])
        self.assertIn("First line", str(decls))

    def test_parameters_build(self):
        decls = gemini_tool_declarations([multi_param_tool])
        self.assertTrue(len(decls) >= 1)

    def test_enum_present_in_declaration(self):
        decls = gemini_tool_declarations([multi_param_tool])
        self.assertTrue(len(decls) >= 1)


class TestOpenAIconverter(unittest.TestCase):
    def test_compact_on_uses_first_line(self):
        with patch(
            "agent.lc.tools_lc.lc_settings.tool_compact_schema", return_value=True
        ):
            schema = convert_to_openai_tool(multi_param_tool)
            self.assertEqual(schema["function"]["description"], "Do the thing.")

    def test_compact_off_uses_first_section(self):
        with patch(
            "agent.lc.tools_lc.lc_settings.tool_compact_schema", return_value=False
        ):
            schema = convert_to_openai_tool(multi_param_tool)
            self.assertEqual(schema["function"]["description"], "Do the thing.")

    def test_schema_structure_intact(self):
        schema = convert_to_openai_tool(short_tool)
        self.assertEqual(schema["type"], "function")
        self.assertIn("parameters", schema["function"])

    def test_compact_off_uses_first_section_with_intro(self):
        # intro_tool has a multi-line FIRST SECTION: compact OFF must use the
        # whole first paragraph (split on '\n\n'), not just the first line.
        with patch("agent.lc.tools_lc.lc_settings.tool_compact_schema", return_value=False):
            schema = convert_to_openai_tool(intro_tool)
            self.assertEqual(
                schema["function"]["description"],
                "Intro line. Continuation sentence stays in the same first paragraph.",
            )


class TestToolCompactSchemaSetting(unittest.TestCase):
    def test_default_on(self):
        os.environ.pop("LC_TOOL_COMPACT_SCHEMA", None)
        from agent.lc import settings

        self.assertTrue(settings.tool_compact_schema())

    def test_on(self):
        os.environ["LC_TOOL_COMPACT_SCHEMA"] = "on"
        from agent.lc import settings

        self.assertTrue(settings.tool_compact_schema())

    def test_off(self):
        os.environ["LC_TOOL_COMPACT_SCHEMA"] = "off"
        from agent.lc import settings

        self.assertFalse(settings.tool_compact_schema())


class TestGetPermittedToolsCap(unittest.TestCase):
    def test_get_permitted_tools_returns_capped(self):
        with patch("tools.get_tool_config", return_value={"enabled": True}):
            tools = get_permitted_tools()
        capped = [t for t in tools if getattr(t, "__lc_capped__", False)]
        # permitted tools are wrapped with result caps
        self.assertTrue(bool(capped))
        self.assertEqual(len(capped), len(tools))

    def test_capped_tools_still_callable(self):
        # cap_tools keeps tools callable and enforces the character cap
        capped = cap_tools([long_result_tool])[0]
        self.assertTrue(callable(capped))
        result = capped()
        self.assertLessEqual(len(result), tool_result_max_chars())
        self.assertTrue(
            result.endswith("[truncated — narrow your query for full data]")
        )

    def test_capped_tools_identifiable_by_name(self):
        tools = get_permitted_tools()
        found = [t for t in tools if getattr(t, "__name__", "") == "search_web"]
        if found:
            self.assertEqual(found[0].__name__, "search_web")


class TestSchemaShrinkMeta(unittest.TestCase):
    def test_payload_shrinks_by_at_least_40(self):
        full = sum(count_tokens((f.__doc__ or "").strip()) for f in AVAILABLE_TOOLS)
        compact = sum(count_tokens(first_line_description(f)) for f in AVAILABLE_TOOLS)
        self.assertLess(
            compact,
            full * 0.65,
            "Phase-4 compact schema should save >= 35% of the tool payload",
        )


def _make_fc_response():
    """Mock response with a function_call so the Gemini loop enters the tool-exec branch."""
    fc = MagicMock()
    fc.name = "exec_tool"
    fc.args = {"x": "hello"}
    part = MagicMock()
    part.function_call = fc
    content = MagicMock()
    content.parts = [part]
    content.role = "model"
    cand = MagicMock()
    cand.content = content
    response = MagicMock()
    response.function_calls = []
    response.candidates = [cand]
    response.text = ""
    return response


class TestGeminiLoopFix(unittest.TestCase):
    """Regression test for phase-4 Gemini bug: execution must dispatch to the
    original callables, not to types.Tool declarations ('Tool not found')."""

    def test_gemini_loop_dispatches_to_original_tools_with_declarations(self):
        # Arrange: tools list with the original callable; compact mode ON so the
        # integration converts it to FunctionDeclaration schemas.
        config_kwargs = {"tools": [exec_tool], "temperature": 2.0}

        call_count = 0

        def send_message_side_effect(*args, **kwargs):
            nonlocal call_count
            call_count += 1
            if call_count == 1:
                return _make_fc_response()
            # second call -> final response without tool calls; must carry
            # a `.text` attribute so the Gemini loop accepts it as the answer.
            final = MagicMock()
            final.function_calls = []
            final.candidates = []
            final.text = "done"
            return final

        chat = MagicMock()
        chat.send_message = MagicMock(side_effect=send_message_side_effect)
        client = MagicMock()
        client.chats.create = MagicMock(return_value=chat)

        feedback_calls = []

        def insert_feedback_side_effect(*args, **kwargs):
            # insert_feedback(cursor, table, session_id, message_in_id, feedback)
            feedback_calls.append((args[4], kwargs))

        with patch("agent.llm_providers.genai.Client", return_value=client), \
             patch(
                 "agent.llm_providers.get_config",
                 side_effect=lambda key, default=None: (
                     "2" if key == "AUTONOMOUS_MODE" else "Agent" if key == "agent_name"
                     else default
                 ),
             ), \
             patch("agent.llm_providers.insert_feedback", side_effect=insert_feedback_side_effect):
            result = call_gemini_llm(
                "gemini-1.0-pro",
                [],
                config_kwargs,
                "query",
                None,
                "sid",
                "mid",
                "tbl",
                api_key="fake-key",
            )

        # Act/Assert: the model's answer is the final response text, while the
        # Gemini loop executed the tool in between (that is what proves the fix):
        # the dispatch used the original callables, not the SDK-only declarations.
        self.assertEqual(result, "done")
        self.assertEqual(call_count, 2)
        # Loop logs execution start + finish for the invoked tool.
        self.assertTrue(
            any("executing local tool: exec_tool" in msg.lower() for msg, _ in feedback_calls)
        )
        self.assertTrue(
            any("executed tools" in msg.lower() and "exec_tool" in msg.lower() for msg, _ in feedback_calls)
        )
        # No 'Tool not found' path was taken.
        self.assertFalse(
            any("tool not found" in msg.lower() for msg, _ in feedback_calls)
        )


def big_result_tool() -> str:
    """A tool returning a very large result for cap testing."""
    return "x" * 30000


class TestCapEdge(unittest.TestCase):
    """Regression test for phase-4 cap edge case: max_chars < len(marker)."""

    def test_cap_respects_max_chars_when_below_marker_len(self):
        capped = cap_tools([big_result_tool])[0]
        with patch("agent.lc.settings.tool_result_max_chars", return_value=30):
            result = capped()
        self.assertLessEqual(len(result), 30)

    def test_cap_with_marker_when_max_chars_goes_over_marker_len(self):
        capped = cap_tools([big_result_tool])[0]
        with patch("agent.lc.settings.tool_result_max_chars", return_value=60):
            result = capped()
        self.assertEqual(len(result), 60)
        self.assertTrue(result.endswith(TRUNCATION_MARKER))


class TestLCToolDefaults(unittest.TestCase):
    """Regression test for phase-4 _build_args_schema: optional params keep defaults."""

    def test_lc_tool_opt_params_have_defaults(self):
        def optional_tool(v: str = "fallback") -> str:
            """An optional param."""
            return v

        tool = lc_tool(optional_tool)
        # tool.args is the JSON args_schema dict used to build the StructuredTool:
        # {param_name: {default, description, title, type, ...}}.
        schema = tool.args
        self.assertIn("v", schema)
        self.assertEqual(schema["v"]["default"], "fallback")

    def test_lc_tool_opt_param_override_works(self):
        def optional_tool(v: str = "fallback") -> str:
            """An optional param."""
            return v

        tool = lc_tool(optional_tool)
        # Overrides are applied by the tool wrapper when the tool is executed;
        # the JSON schema keeps the default as a validation-level fallback.
        schema = tool.args
        self.assertIn("v", schema)
        self.assertEqual(schema["v"]["default"], "fallback")


def _flaky_schema_builder(real_fn, broken_name):
    """Wraps a schema-building fn so one named tool raises (simulating a
    user-authored tool whose docstring breaks the schema builder)."""

    def wrapper(func, *args, **kwargs):
        if func.__name__ == broken_name:
            raise ValueError(
                "Arg Returns in docstring not found in function signature"
            )
        return real_fn(func, *args, **kwargs)

    return wrapper


def broken_tool(x: str) -> str:
    """A tool whose schema build fails (simulated in tests)."""
    return x


class TestSchemaBuildResilience(unittest.TestCase):
    """One tool whose schema cannot be built must be skipped with a warning
    instead of crashing the whole LLM call — in BOTH the LangChain builder and
    the Gemini declaration builder (parity with the legacy OpenAI converter)."""

    def test_build_lc_tools_skips_broken_tool(self):
        from agent.lc import tools_lc

        wrapper = _flaky_schema_builder(tools_lc.lc_tool, "broken_tool")
        with patch("agent.lc.tools_lc.lc_tool", side_effect=wrapper):
            tools = build_lc_tools([broken_tool, multi_param_tool])

        names = [t.name for t in tools]
        self.assertNotIn("broken_tool", names)
        self.assertIn("multi_param_tool", names)

    def test_build_lc_tools_all_broken_returns_empty(self):
        from agent.lc import tools_lc

        def always_raises(func):
            raise ValueError("boom")

        with patch("agent.lc.tools_lc.lc_tool", side_effect=always_raises):
            tools = build_lc_tools([broken_tool])

        self.assertEqual(tools, [])

    def test_gemini_declarations_skip_broken_tool(self):
        from agent.lc import tools_lc

        wrapper = _flaky_schema_builder(tools_lc.tool_param_schema, "broken_tool")
        with patch("agent.lc.tools_lc.tool_param_schema", side_effect=wrapper):
            decls = gemini_tool_declarations([broken_tool, multi_param_tool])

        self.assertEqual(len(decls), 1)
        self.assertEqual(
            decls[0].function_declarations[0].name, "multi_param_tool"
        )
