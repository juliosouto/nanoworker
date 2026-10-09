"""Tests for agent.llm_usage — token accounting for Fase 6.

Helpers run against a real temporary SQLite file (database.get_db
monkeypatched to it), so the INSERT/SELECT roundtrip is exercised exactly
as in production. Note: agent.llm_usage imports get_db lazily at call time,
so patching ``database.get_db`` affects it.
"""

import os
import sqlite3
import tempfile
import unittest
from unittest.mock import patch

from agent import llm_usage


def _schema_sql() -> str:
    """The production llm_usage schema (mirrors database.init_db)."""
    return """
        CREATE TABLE llm_usage (
            id INTEGER PRIMARY KEY AUTOINCREMENT,
            session_id TEXT,
            message_in_id TEXT,
            stack TEXT NOT NULL DEFAULT 'legacy',
            model TEXT,
            input_tokens INTEGER,
            output_tokens INTEGER,
            created_at TIMESTAMP DEFAULT CURRENT_TIMESTAMP
        )
        """


class UsageDbTestCase(unittest.TestCase):
    """Base: one tmp sqlite file per test, injected as database.get_db."""

    def setUp(self):
        super().setUp()
        self._tmpdir = tempfile.mkdtemp(prefix="llm_usage_test_")
        self._db_file = os.path.join(self._tmpdir, "usage.sqlite")
        conn = sqlite3.connect(self._db_file)
        conn.execute(_schema_sql())
        conn.commit()
        conn.close()

        def fake_get_db():
            c = sqlite3.connect(self._db_file)
            c.row_factory = sqlite3.Row
            return c

        patcher = patch("database.get_db", side_effect=fake_get_db)
        self.addCleanup(patcher.stop)
        patcher.start()

    def tearDown(self):
        try:
            os.unlink(self._db_file)
            os.rmdir(self._tmpdir)
        except OSError:
            pass


class TestLogLlmUsage(UsageDbTestCase):
    """log_llm_usage writes rows and never raises."""

    def test_roundtrip_writes_row(self):
        ok = llm_usage.log_llm_usage("s1", "m1", "langchain", "gemini-2.5", 120, 30)
        self.assertTrue(ok)
        summary = llm_usage.get_usage_summary()
        self.assertEqual(len(summary), 1)
        self.assertEqual(summary[0]["stack"], "langchain")
        self.assertEqual(summary[0]["turns"], 1)
        self.assertEqual(summary[0]["input_tokens"], 120)
        self.assertEqual(summary[0]["output_tokens"], 30)
        self.assertEqual(summary[0]["total_tokens"], 150)
        self.assertEqual(summary[0]["avg_tokens_per_turn"], 150.0)

    def test_skipped_when_both_counts_none(self):
        self.assertFalse(llm_usage.log_llm_usage("s", "m", "legacy", "m", None, None))
        self.assertEqual(llm_usage.get_usage_summary(), [])

    def test_partial_counts_logged(self):
        # One side None is fine (some providers only report one side).
        self.assertTrue(llm_usage.log_llm_usage("s", "m", "legacy", "m", 50, None))
        summary = llm_usage.get_usage_summary()
        self.assertEqual(summary[0]["input_tokens"], 50)
        self.assertEqual(summary[0]["output_tokens"], 0)

    def test_db_failure_never_raises(self):
        with patch("database.get_db", side_effect=sqlite3.OperationalError("down")):
            self.assertFalse(
                llm_usage.log_llm_usage("s", "m", "legacy", "m", 10, 5)
            )



class TestDaysClamp(unittest.TestCase):
    """_days_since clamps the dashboard window to 1..90 (default 14)."""

    def test_clamp_bounds(self):
        self.assertEqual(llm_usage._days_since(500), 90)
        self.assertEqual(llm_usage._days_since(90), 90)
        self.assertEqual(llm_usage._days_since(1), 1)
        self.assertEqual(llm_usage._days_since(0), 1)
        self.assertEqual(llm_usage._days_since(-5), 1)

    def test_defaults_on_garbage(self):
        self.assertEqual(llm_usage._days_since("abc"), 14)
        self.assertEqual(llm_usage._days_since(None), 14)
        self.assertEqual(llm_usage._days_since(14), 14)


class TestUsageSummary(UsageDbTestCase):
    """Aggregates power the dashboard before/after card."""

    def _seed(self):
        llm_usage.log_llm_usage("s1", "m1", "legacy", "gpt-4o", 100, 20)
        llm_usage.log_llm_usage("s2", "m2", "legacy", "gpt-4o", 200, 40)
        llm_usage.log_llm_usage("s3", "m3", "langchain", "gemini-2.5", 60, 15)

    def test_summary_per_stack(self):
        self._seed()
        summary = {row["stack"]: row for row in llm_usage.get_usage_summary()}
        self.assertEqual(set(summary), {"legacy", "langchain"})
        self.assertEqual(summary["legacy"]["turns"], 2)
        self.assertEqual(summary["legacy"]["input_tokens"], 300)
        self.assertEqual(summary["legacy"]["output_tokens"], 60)
        self.assertEqual(summary["legacy"]["total_tokens"], 360)
        self.assertEqual(summary["legacy"]["avg_tokens_per_turn"], 180.0)
        self.assertEqual(summary["langchain"]["turns"], 1)

    def test_by_model(self):
        self._seed()
        rows = llm_usage.get_usage_by_model()
        self.assertEqual(len(rows), 2)
        # Ordered by total desc (legacy/gpt-4o = 360 first).
        self.assertEqual(rows[0]["model"], "gpt-4o")
        self.assertEqual(rows[0]["stack"], "legacy")
        self.assertEqual(rows[0]["total_tokens"], 360)
        self.assertEqual(rows[1]["model"], "gemini-2.5")

    def test_missing_table_returns_empty(self):
        with patch(
            "database.get_db", side_effect=sqlite3.OperationalError("no table")
        ):
            self.assertEqual(llm_usage.get_usage_summary(), [])
            self.assertEqual(llm_usage.get_usage_by_model(), [])


def _mock_config(key, default=None):
    if key == "AUTONOMOUS_MODE":
        return "1"
    if key == "agent_name":
        return "Agent"
    return default


class TestLegacyOpenAILoopUsage(unittest.TestCase):
    """execute_openai_compatible_llm flushes ONE aggregated legacy row."""

    def _completion(self, content, tool_calls, usage):
        from unittest.mock import MagicMock

        msg = MagicMock()
        msg.content = content
        msg.tool_calls = tool_calls
        choice = MagicMock()
        choice.message = msg
        resp = MagicMock()
        resp.choices = [choice]
        if usage is not None:
            resp.usage.prompt_tokens, resp.usage.completion_tokens = usage
        else:
            # Simulate a provider that reports no usage at all.
            del resp.usage
        return resp

    def _two_turn_client(self, usage1=(100, 20), usage2=(60, 10)):
        from unittest.mock import MagicMock

        tc = MagicMock()
        tc.id = "call_1"
        tc.function.name = "tool_a"
        tc.function.arguments = '{"query": "x"}'
        client = MagicMock()
        client.chat.completions.create.side_effect = [
            self._completion(None, [tc], usage1),
            self._completion("final answer", None, usage2),
        ]
        return client

    def test_success_logs_aggregated_row(self):
        from unittest.mock import MagicMock, patch

        from agent.openai_tools import execute_openai_compatible_llm

        def tool_a(query: str) -> str:
            """A simple dummy tool. Args: query: the search term."""
            return "result a"

        logged = []
        client = self._two_turn_client()
        with patch("agent.openai_tools.get_config", side_effect=_mock_config), \
             patch("agent.openai_tools.insert_feedback", lambda *a, **k: None), \
             patch(
                 "agent.llm_usage.log_llm_usage",
                 side_effect=lambda *a: logged.append(a) or True,
             ):
            result = execute_openai_compatible_llm(
                client,
                "gpt-4o",
                [],
                {"tools": [tool_a]},
                "hello",
                MagicMock(),
                "session-1",
                "msg-1",
                "messages_out",
            )
        self.assertEqual(result, "final answer")
        self.assertEqual(
            logged, [("session-1", "msg-1", "legacy", "gpt-4o", 160, 30)]
        )

    def test_no_usage_no_row(self):
        from unittest.mock import MagicMock, patch

        from agent.openai_tools import execute_openai_compatible_llm

        def tool_a(query: str) -> str:
            """A simple dummy tool. Args: query: the search term."""
            return "result a"

        client = self._two_turn_client(usage1=None, usage2=None)
        with patch("agent.openai_tools.get_config", side_effect=_mock_config), \
             patch("agent.openai_tools.insert_feedback", lambda *a, **k: None), \
             patch("agent.llm_usage.log_llm_usage") as log:
            execute_openai_compatible_llm(
                client,
                "gpt-4o",
                [],
                {"tools": [tool_a]},
                "hello",
                MagicMock(),
                "session-1",
                "msg-1",
                "messages_out",
            )
        log.assert_not_called()



class TestLegacyGeminiLoopUsage(unittest.TestCase):
    """call_gemini_llm flushes ONE aggregated legacy row."""

    def _run_gemini(self, usage1, usage2, logged):
        from unittest.mock import MagicMock, patch

        from agent.llm_providers import call_gemini_llm

        def tool_a(query: str) -> str:
            """A simple dummy tool. Args: query: the search term."""
            return "result a"

        fc = MagicMock()
        fc.name = "tool_a"
        fc.args = {"query": "x"}

        tool_resp = MagicMock()
        tool_resp.usage_metadata.prompt_token_count = usage1[0]
        tool_resp.usage_metadata.candidates_token_count = usage1[1]
        tool_resp.function_calls = [fc]

        final_resp = MagicMock()
        final_resp.usage_metadata.prompt_token_count = usage2[0]
        final_resp.usage_metadata.candidates_token_count = usage2[1]
        final_resp.function_calls = []
        final_resp.text = "done"

        chat = MagicMock()
        chat.send_message.side_effect = [tool_resp, final_resp]
        client = MagicMock()
        client.chats.create = MagicMock(return_value=chat)

        with patch("agent.llm_providers.genai.Client", return_value=client), \
             patch(
                 "agent.llm_providers.get_config",
                 side_effect=lambda k, d=None: (
                     "1" if k == "AUTONOMOUS_MODE" else "Agent" if k == "agent_name"
                     else d
                 ),
             ), \
             patch("agent.llm_providers.insert_feedback", lambda *a, **k: None), \
             patch(
                 "agent.llm_usage.log_llm_usage",
                 side_effect=lambda *a: logged.append(a) or True,
             ):
            return call_gemini_llm(
                "gemini-2.5",
                [],
                {"tools": [tool_a]},
                "hello",
                MagicMock(),
                "session-1",
                "msg-1",
                "messages_out",
                api_key="k",
            )

    def test_success_logs_aggregated_row(self):
        logged = []
        result = self._run_gemini((100, 20), (60, 10), logged)
        self.assertEqual(result, "done")
        self.assertEqual(
            logged, [("session-1", "msg-1", "legacy", "gemini-2.5", 160, 30)]
        )

    def test_missing_usage_metadata_no_row(self):
        from unittest.mock import MagicMock, patch

        from agent.llm_providers import call_gemini_llm

        def tool_a(query: str) -> str:
            """A simple dummy tool. Args: query: the search term."""
            return "result a"

        final_resp = MagicMock()
        final_resp.usage_metadata = None
        final_resp.function_calls = []
        final_resp.text = "done"
        chat = MagicMock()
        chat.send_message.return_value = final_resp
        client = MagicMock()
        client.chats.create = MagicMock(return_value=chat)

        with patch("agent.llm_providers.genai.Client", return_value=client), \
             patch(
                 "agent.llm_providers.get_config",
                 side_effect=lambda k, d=None: (
                     "1" if k == "AUTONOMOUS_MODE" else "Agent" if k == "agent_name"
                     else d
                 ),
             ), \
             patch("agent.llm_providers.insert_feedback", lambda *a, **k: None), \
             patch("agent.llm_usage.log_llm_usage") as log:
            call_gemini_llm(
                "gemini-2.5",
                [],
                {"tools": [tool_a]},
                "hello",
                MagicMock(),
                "session-1",
                "msg-1",
                "messages_out",
                api_key="k",
            )
        log.assert_not_called()


class TestDashboardUsageCard(unittest.TestCase):
    """dashboard_page passes the usage aggregates (?days honored)."""

    def test_page_renders_usage_context(self):
        import routes.views as views_mod
        from unittest.mock import MagicMock

        from app import app

        summary = [{"stack": "legacy", "turns": 2}]
        by_model = [{"stack": "langchain", "model": "m", "turns": 1}]
        # Module-level get_db: must return a working mock connection for the
        # user_memory query (function-local imports patch at their source).
        mock_conn = MagicMock()
        mock_conn.cursor.return_value.fetchall.return_value = []
        with patch.object(views_mod, "get_db", return_value=mock_conn), patch(
            "database.get_ide_config", return_value=None
        ), patch(
            "utils.message_utils.get_default_worker", return_value=None
        ), patch(
            "standard_prompts.apply_standard_rules", return_value=""
        ), patch(
            "tools.get_permitted_tools", return_value=[]
        ), patch(
            "database.get_config", return_value="false"
        ), patch(
            "agent.llm_usage.get_usage_summary", return_value=summary
        ) as get_sum, patch(
            "agent.llm_usage.get_usage_by_model", return_value=by_model
        ) as get_bm, patch(
            "routes.views.render_template", return_value="OK"
        ) as render:
            with app.test_request_context("/dashboard?days=30"):
                self.assertEqual(views_mod.dashboard_page(), "OK")
        get_sum.assert_called_once_with(30)
        get_bm.assert_called_once_with(30)
        kwargs = render.call_args.kwargs
        self.assertEqual(kwargs["usage_days"], 30)
        self.assertEqual(kwargs["usage_summary"], summary)
        self.assertEqual(kwargs["usage_by_model"], by_model)

    def test_days_defaults_and_clamps(self):
        import routes.views as views_mod
        from unittest.mock import MagicMock

        from app import app

        mock_conn = MagicMock()
        mock_conn.cursor.return_value.fetchall.return_value = []
        for query, expected in [("", 14), ("?days=abc", 14)]:
            with patch.object(
                views_mod, "get_db", return_value=mock_conn
            ), patch("database.get_ide_config", return_value=None), patch(
                "utils.message_utils.get_default_worker", return_value=None
            ), patch(
                "standard_prompts.apply_standard_rules", return_value=""
            ), patch(
                "tools.get_permitted_tools", return_value=[]
            ), patch(
                "database.get_config", return_value="false"
            ), patch(
                "agent.llm_usage.get_usage_summary", return_value=[]
            ) as get_sum, patch(
                "agent.llm_usage.get_usage_by_model", return_value=[]
            ), patch(
                "routes.views.render_template", return_value="OK"
            ):
                with app.test_request_context(f"/dashboard{query}"):
                    views_mod.dashboard_page()
            self.assertEqual(get_sum.call_args.args[0], expected)


if __name__ == "__main__":
    unittest.main()
