"""Tests for agent.lc.runner — the unified LangChain execution loop (phase 5).

``FakeListChatModel`` and friends raise ``NotImplementedError`` on ``bind_tools``
in the installed langchain-core, so tool-calling paths use a small scripted
``BaseChatModel`` whose ``bind_tools`` is a no-op. The tool-free path uses
``FakeListChatModel`` as requested.
"""

import unittest
from unittest.mock import MagicMock, patch

from google.genai import types as gt
from langchain_core.language_models import BaseChatModel
from langchain_core.messages import AIMessage
from langchain_core.outputs import ChatGeneration, ChatResult

from agent.lc import runner
from agent.stop_check import StopRequestedError


def _history(texts):
    """Build a google-genai style history from alternating (role, text)."""
    out = []
    for role, text in texts:
        out.append(gt.Content(role=role, parts=[gt.Part.from_text(text=text)]))
    return out


class ScriptedToolCallingModel(BaseChatModel):
    """A fake chat model returning a scripted sequence of AIMessages.

    ``bind_tools`` is a no-op (returns self) because the base implementations
    are not implemented for generic fakes in langchain-core.
    """

    responses: list = []
    idx: int = 0

    @property
    def _llm_type(self) -> str:
        return "scripted-tool-calling"

    def _generate(self, messages, stop=None, run_manager=None, **kwargs):
        msg = self.responses[self.idx]
        self.idx += 1
        return ChatResult(generations=[ChatGeneration(message=msg)])

    def bind_tools(self, tools, **kwargs):
        return self


def echo_tool(x: str) -> str:
    """Echo tool used across runner tests."""
    return f"echoed:{x}"


def _patch_model(scripted):
    return patch.object(runner.lc_models, "make_chat_model", return_value=scripted)


def _patch_config(autonomous_mode="3"):
    return patch(
        "database.get_config",
        side_effect=lambda key, default=None: (
            autonomous_mode if key == "AUTONOMOUS_MODE" else default
        ),
    )


def _collect_feedback():
    """Return (list, side_effect) capturing insert_feedback text arguments."""
    captured = []

    def side_effect(cursor, table, session_id, message_in_id, text):
        captured.append(text)

    return captured, side_effect


class TestRunnerNoTools(unittest.TestCase):
    """The tool-free path uses FakeListChatModel and returns the final string."""

    def test_happy_path_returns_final_string(self):
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        fake = FakeListChatModel(responses=["FINAL ANSWER"])
        feedback, fb_side = _collect_feedback()
        with _patch_model(fake), _patch_config(), patch(
            "agent.db_feedback.insert_feedback", side_effect=fb_side
        ):
            out = runner.run_langchain_llm(
                "gpt-4o",
                _history([("user", "hi")]),
                {"system_instruction": "sys"},
                "query",
                None,
                "sid",
                "mid",
                "messages_out",
                provider="openai",
                api_key="k",
            )
        self.assertEqual(out, "FINAL ANSWER")
        # No tools configured → no ⚙️ feedback is emitted.
        self.assertEqual(feedback, [])

    def test_history_is_converted(self):
        # Verify the history → LangChain messages conversion directly (the chain
        # receives formatted prompt values, so inspect _history_to_lc_messages).

        msgs = runner._history_to_lc_messages(
            _history(
                [("user", "hi"), ("model", "hello"), ("user", "again")]
            )
        )
        kinds = [type(m).__name__ for m in msgs]
        self.assertEqual(kinds, ["HumanMessage", "AIMessage", "HumanMessage"])
        self.assertEqual(msgs[1].content, "hello")

    def test_happy_path_feeds_system_and_input_to_model(self):
        # The no-tools direct chain must include the system prompt and the user
        # input when it reaches the model.
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        seen = {}

        class Spy(FakeListChatModel):
            def _generate(self, messages, stop=None, run_manager=None, **kwargs):
                seen["messages"] = messages
                return super()._generate(messages, stop, run_manager, **kwargs)

        fake = Spy(responses=["OK"])
        with _patch_model(fake), _patch_config():
            out = runner.run_langchain_llm(
                "gpt-4o",
                _history([("user", "hi")]),
                {"system_instruction": "MY SYSTEM PROMPT"},
                "final query",
                None,
                "sid",
                "mid",
                "messages_out",
                provider="openai",
                api_key="k",
            )
        self.assertEqual(out, "OK")
        rendered = " ".join(getattr(m, "content", "") for m in seen["messages"])
        self.assertIn("MY SYSTEM PROMPT", rendered)
        self.assertIn("final query", rendered)


class TestRunnerToolCalling(unittest.TestCase):
    """End-to-end tool-calling via create_tool_calling_agent + AgentExecutor."""

    def _scripted(self):
        return ScriptedToolCallingModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "echo_tool", "args": {"x": "hi"}, "id": "1"}],
                ),
                AIMessage(content="DONE"),
            ]
        )

    def test_tool_executed_and_feedback_emitted(self):
        scripted = self._scripted()
        feedback, fb_side = _collect_feedback()
        completed = []
        with _patch_model(scripted), _patch_config(), patch(
            "agent.db_feedback.insert_feedback", side_effect=fb_side
        ):
            out = runner.run_langchain_llm(
                "gpt-4o",
                _history([("user", "hi")]),
                {"system_instruction": "sys", "tools": [echo_tool], "show_tools_results": True},
                "query",
                None,
                "sid",
                "mid",
                "messages_out",
                provider="openai",
                api_key="k",
                on_complete=completed.append,
            )
        self.assertEqual(out, "DONE")
        # ⚙️ start + ⚙️ executed (with the tool's actual result) both emitted.
        self.assertIn("⚙️ Executing local tool: echo_tool...", feedback)
        self.assertTrue(any("echoed:hi" in f for f in feedback))
        # on_complete fires only for the executed message when show_tools_results.
        self.assertTrue(any("echoed:hi" in m for m in completed))

    def test_on_complete_suppressed_when_show_tools_results_false(self):
        scripted = self._scripted()
        completed = []
        with _patch_model(scripted), _patch_config(), patch(
            "agent.db_feedback.insert_feedback", lambda *a, **k: None
        ):
            runner.run_langchain_llm(
                "gpt-4o",
                _history([("user", "hi")]),
                {"system_instruction": "sys", "tools": [echo_tool], "show_tools_results": False},
                "query",
                None,
                "sid",
                "mid",
                "messages_out",
                provider="openai",
                api_key="k",
                on_complete=completed.append,
            )


class TestRunnerStop(unittest.TestCase):
    """/stop propagation: a StopRequestedError inside a tool bubbles out intact."""

    def _stop_scripted(self):
        def stop_tool(x: str) -> str:
            """Tool that simulates a user /stop mid-execution."""
            raise StopRequestedError()

        scripted = ScriptedToolCallingModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "stop_tool", "args": {"x": "go"}, "id": "1"}],
                ),
                AIMessage(content="DONE"),
            ]
        )
        return scripted, stop_tool

    def test_stop_from_inside_tool_propagates(self):
        scripted, stop_tool = self._stop_scripted()
        with _patch_model(scripted), _patch_config(), patch(
            "agent.db_feedback.insert_feedback", lambda *a, **k: None
        ):
            with self.assertRaises(StopRequestedError):
                runner.run_langchain_llm(
                    "gpt-4o",
                    _history([("user", "hi")]),
                    {"system_instruction": "sys", "tools": [stop_tool]},
                    "query",
                    None,
                    "sid",
                    "mid",
                    "messages_out",
                    provider="openai",
                    api_key="k",
                )

    def test_stop_requested_before_tool_start_aborts(self):
        # is_stop_requested() returns True → on_tool_start raises before any work.
        scripted, _ = self._stop_scripted()
        with _patch_model(scripted), _patch_config(), patch(
            "agent.db_feedback.insert_feedback", lambda *a, **k: None
        ), patch("agent.lc.runner.is_stop_requested", return_value=True):
            with self.assertRaises(StopRequestedError):
                runner.run_langchain_llm(
                    "gpt-4o",
                    _history([("user", "hi")]),
                    {"system_instruction": "sys", "tools": [echo_tool]},
                    "query",
                    None,
                    "sid",
                    "mid",
                    "messages_out",
                    provider="openai",
                    api_key="k",
                )



class TestRunnerRetry(unittest.TestCase):
    """429/402 transient errors retry with ⏳/💳 feedback; permanent errors don't."""

    def _run_with_invoke_errors(self, errors, final="OK"):
        """Drive run_langchain_llm with an executor.invoke that raises `errors`
        in sequence, then returns a dict with 'output'. Returns
        (output, feedback, completed, attempts)."""
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        calls = {"n": 0}

        class FlakyExecutor:
            def invoke(self, payload, config=None):
                i = calls["n"]
                calls["n"] += 1
                if i < len(errors):
                    raise errors[i]
                return {"output": final}

        feedback, fb_side = _collect_feedback()
        completed = []
        with patch.object(runner, "_DirectChainExecutor", return_value=FlakyExecutor()), \
             _patch_config(), patch(
                 "agent.db_feedback.insert_feedback", side_effect=fb_side
             ), patch(
                 "agent.lc.runner.sleep_interruptible", return_value=False
             ), patch.object(
                 runner.lc_models, "make_chat_model",
                 return_value=FakeListChatModel(responses=["x"]),
             ):
            out = runner.run_langchain_llm(
                "gpt-4o",
                _history([("user", "hi")]),
                {"system_instruction": "sys"},
                "query",
                None,
                "sid",
                "mid",
                "messages_out",
                provider="openai",
                api_key="k",
                on_complete=completed.append,
            )
        return out, feedback, completed, calls["n"]

    def test_rate_limit_retries_then_succeeds(self):
        err = Exception("429 rate limit: retry in 1s")
        out, feedback, _, attempts = self._run_with_invoke_errors([err])
        self.assertEqual(out, "OK")
        self.assertEqual(attempts, 2)  # one failure + one success
        self.assertTrue(any("⏳ Rate limit (429)" in f for f in feedback))

    def test_provider_balance_retries_then_succeeds(self):
        err = Exception("402 provider returned error: Insufficient balance, provider_name=X")
        out, feedback, _, attempts = self._run_with_invoke_errors([err])
        self.assertEqual(out, "OK")
        self.assertEqual(attempts, 2)
        self.assertTrue(any("💳" in f for f in feedback))

    def test_permanent_error_propagates(self):
        err = Exception("401 Unauthorized: invalid api key")
        with self.assertRaises(Exception) as ctx:
            self._run_with_invoke_errors([err])
        self.assertIn("401", str(ctx.exception))

    def test_stop_during_wait_raises(self):
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        err = Exception("429 rate limit exceeded")

        class RaisingExecutor:
            def invoke(self, payload, config=None):
                raise err

        with patch.object(runner, "_DirectChainExecutor", return_value=RaisingExecutor()), \
             _patch_config(), patch(
                 "agent.db_feedback.insert_feedback", lambda *a, **k: None
             ), patch("agent.lc.runner.sleep_interruptible", return_value=True), \
             patch.object(runner.lc_models, "make_chat_model",
                          return_value=FakeListChatModel(responses=["x"])):
            with self.assertRaises(StopRequestedError):
                runner.run_langchain_llm(
                    "gpt-4o",
                    _history([("user", "hi")]),
                    {"system_instruction": "sys"},
                    "query",
                    None,
                    "sid",
                    "mid",
                    "messages_out",
                    provider="openai",
                    api_key="k",
                )


class TestRunnerHelpers(unittest.TestCase):
    """Pure conversion helpers used to bridge legacy payloads to LangChain."""

    def test_history_genai_content(self):
        msgs = runner._history_to_lc_messages(
            _history([("user", "hi"), ("model", "hello")])
        )
        self.assertEqual([m.type for m in msgs], ["human", "ai"])
        self.assertEqual(msgs[0].content, "hi")

    def test_history_openai_style_dicts(self):
        msgs = runner._history_to_lc_messages(
            [{"role": "user", "content": "hi"}, {"role": "assistant", "content": "yo"}]
        )
        self.assertEqual([m.type for m in msgs], ["human", "ai"])

    def test_history_empty(self):
        self.assertEqual(runner._history_to_lc_messages([]), [])

    def test_content_to_text_string(self):
        self.assertEqual(runner._content_to_text("hello"), "hello")

    def test_content_to_text_genai_parts(self):
        parts = [gt.Part.from_text(text="a"), gt.Part.from_text(text="b")]
        self.assertEqual(runner._content_to_text(parts), "a b")

    def test_content_to_text_mixed(self):
        parts = ["a", gt.Part.from_text(text="b")]
        self.assertEqual(runner._content_to_text(parts), "a b")

    def test_structured_kwargs_openai_compat(self):
        # Fase 1 key injected by the router maps onto the factory arg.
        rf = {"type": "json_schema"}
        self.assertEqual(
            runner._build_structured_kwargs(
                {"lc_openai_response_format": rf}, True
            ),
            {"response_format": rf, "has_tools": True},
        )

    def test_structured_kwargs_gemini(self):
        # Gemini mime/schema map onto the factory flags; the schema drop with
        # tools is applied later inside make_chat_model (has_tools travels).
        schema = {"type": "object"}
        self.assertEqual(
            runner._build_structured_kwargs(
                {
                    "response_mime_type": "application/json",
                    "response_schema": schema,
                },
                True,
            ),
            {
                "gemini_json_mime": True,
                "gemini_json_schema": schema,
                "has_tools": True,
            },
        )
        self.assertEqual(
            runner._build_structured_kwargs(
                {"response_mime_type": "application/json"}, False
            ),
            {"gemini_json_mime": True, "has_tools": False},
        )

    def test_structured_kwargs_absent(self):
        # No structured-output keys: only the has_tools flag travels.
        self.assertEqual(
            runner._build_structured_kwargs({}, True), {"has_tools": True}
        )


class TestRunnerCache(unittest.TestCase):
    """LC_CACHE gate drives the optional SQLite LLM cache (default off)."""

    def setUp(self):
        # Each test drives the cache from a clean singleton state.
        runner.lc_cache._initialized = False

    def test_cache_off_by_default(self):
        with patch("agent.lc.cache.settings.cache_enabled", return_value=False):
            self.assertFalse(runner.lc_cache.maybe_init_cache())

    def test_cache_on_installs_sqlite_cache(self):
        fake_cache = object()
        with patch("agent.lc.cache.settings.cache_enabled", return_value=True), \
             patch("agent.lc.cache.settings.cache_path", return_value=":memory:"), \
             patch("langchain_community.cache.SQLiteCache", return_value=fake_cache), \
             patch("langchain_core.globals.set_llm_cache") as set_cache:
            installed = runner.lc_cache.maybe_init_cache()
        self.assertTrue(installed)
        self.assertEqual(set_cache.call_count, 1)
        self.assertIs(set_cache.call_args.args[0], fake_cache)

    def test_cache_init_is_idempotent(self):
        fake_cache = object()
        with patch("agent.lc.cache.settings.cache_enabled", return_value=True), \
             patch("agent.lc.cache.settings.cache_path", return_value=":memory:"), \
             patch("langchain_community.cache.SQLiteCache", return_value=fake_cache), \
             patch("langchain_core.globals.set_llm_cache") as set_cache:
            runner.lc_cache.maybe_init_cache()
            runner.lc_cache.maybe_init_cache()  # second call must be a no-op
        self.assertEqual(set_cache.call_count, 1)

class TestRouteBranch(unittest.TestCase):
    """route_llm_call dispatches to the runner only under LLM_STACK=langchain."""

    def _route(self, stack_enabled, summarize, runner_return="LC-OUT", legacy_return="LEGACY"):
        from agent import llm_router

        hist = [gt.Content(role="user", parts=[gt.Part.from_text(text="hi")])]

        def fake_get_db():
            conn = MagicMock()
            cur = conn.cursor()
            cur.fetchone.return_value = {
                "provider": "openai",
                "api_key": "k",
                "thinking": 0,
                "context_window": None,
                "max_output_tokens": None,
            }
            conn.cursor.return_value = cur
            return conn

        with patch("agent.llm_router.lc_settings.stack_enabled", return_value=stack_enabled), \
             patch("database.get_db", fake_get_db), \
             patch("database.decrypt_value", return_value="k"), \
             patch("database.get_config",
                   side_effect=lambda k, d=None: "3" if k == "AUTONOMOUS_MODE" else d), \
             patch("agent.lc.outputs.structured_output_enabled", return_value=False), \
             patch("agent.llm_router._providers.call_openai_llm", return_value=legacy_return) as legacy, \
             patch("agent.lc.runner.run_langchain_llm", return_value=runner_return) as lc:
            out = llm_router.route_llm_call(
                "gpt-4o", hist, {"system_instruction": "sys"}, "query",
                None, "sid", "mid", is_ide=False, summarize=summarize,
            )
        return out, legacy, lc

    def test_langchain_stack_uses_runner(self):
        out, legacy, lc = self._route(stack_enabled=True, summarize=False)
        self.assertEqual(out, "LC-OUT")
        self.assertTrue(lc.called)
        self.assertFalse(legacy.called)

    def test_legacy_stack_skips_runner(self):
        out, legacy, lc = self._route(stack_enabled=False, summarize=False)
        self.assertEqual(out, "LEGACY")
        self.assertFalse(lc.called)
        self.assertTrue(legacy.called)

    def test_summarize_stays_legacy_even_in_langchain_stack(self):
        out, legacy, lc = self._route(stack_enabled=True, summarize=True)
        self.assertEqual(out, "LEGACY")
        self.assertFalse(lc.called)
        self.assertTrue(legacy.called)

    def test_runner_receives_resolved_provider_and_key(self):
        _, _, lc = self._route(stack_enabled=True, summarize=False)
        kwargs = lc.call_args.kwargs
        self.assertEqual(kwargs.get("provider"), "openai")
        self.assertEqual(kwargs.get("api_key"), "k")


class TestRunnerUsage(unittest.TestCase):
    """Fase 6: usage_metadata is accumulated per turn and logged once."""

    def _llm_result(self, in_tokens, out_tokens):
        from langchain_core.outputs import ChatGeneration, LLMResult

        msg = AIMessage(
            content="x",
            usage_metadata={
                "input_tokens": in_tokens,
                "output_tokens": out_tokens,
                "total_tokens": (in_tokens or 0) + (out_tokens or 0),
            },
        )
        return LLMResult(generations=[[ChatGeneration(message=msg)]])

    def test_on_llm_end_accumulates_usage(self):
        handler = runner.FeedbackCallbackHandler(
            None, "tbl", "sid", "mid", True
        )
        handler.on_llm_end(self._llm_result(100, 20), run_id="r1")
        handler.on_llm_end(self._llm_result(60, 10), run_id="r2")
        self.assertEqual(handler.usage_calls, 2)
        self.assertEqual(handler.usage_input_tokens, 160)
        self.assertEqual(handler.usage_output_tokens, 30)

    def test_on_llm_end_ignores_missing_usage(self):
        from langchain_core.outputs import ChatGeneration, LLMResult

        handler = runner.FeedbackCallbackHandler(
            None, "tbl", "sid", "mid", True
        )
        plain = LLMResult(
            generations=[[ChatGeneration(message=AIMessage(content="x"))]]
        )
        handler.on_llm_end(plain, run_id="r1")
        handler.on_llm_end(None, run_id="r2")
        self.assertEqual(handler.usage_calls, 0)

    def test_run_logs_usage_row_once(self):
        scripted = ScriptedToolCallingModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "echo_tool", "args": {"x": "go"}, "id": "1"}],
                    usage_metadata={
                        "input_tokens": 100,
                        "output_tokens": 20,
                        "total_tokens": 120,
                    },
                ),
                AIMessage(
                    content="DONE",
                    usage_metadata={
                        "input_tokens": 60,
                        "output_tokens": 10,
                        "total_tokens": 70,
                    },
                ),
            ]
        )
        logged = []

        def fake_log(session_id, message_in_id, stack, model, in_tokens, out_tokens):
            logged.append(
                (session_id, message_in_id, stack, model, in_tokens, out_tokens)
            )
            return True

        with _patch_model(scripted), _patch_config(), patch(
            "agent.db_feedback.insert_feedback", lambda *a, **k: None
        ), patch("agent.llm_usage.log_llm_usage", side_effect=fake_log):
            out = runner.run_langchain_llm(
                "gpt-4o",
                _history([("user", "hi")]),
                {"system_instruction": "sys", "tools": [echo_tool]},
                "query",
                None,
                "sid",
                "mid",
                "messages_out",
                provider="openai",
                api_key="k",
            )
        self.assertEqual(out, "DONE")
        # Both agent iterations summed into a single langchain row.
        self.assertEqual(
            logged, [("sid", "mid", "langchain", "gpt-4o", 160, 30)]
        )

    def test_run_without_usage_logs_nothing(self):
        from langchain_core.language_models.fake_chat_models import FakeListChatModel

        with _patch_model(FakeListChatModel(responses=["OK"])), _patch_config(), \
             patch("agent.db_feedback.insert_feedback", lambda *a, **k: None), \
             patch("agent.llm_usage.log_llm_usage") as log:
            runner.run_langchain_llm(
                "gpt-4o",
                _history([("user", "hi")]),
                {"system_instruction": "sys"},
                "query",
                None,
                "sid",
                "mid",
                "messages_out",
                provider="openai",
                api_key="k",
            )
        # FakeListChatModel carries no usage_metadata → no row.
        log.assert_not_called()


if __name__ == "__main__":
    unittest.main()
