"""Tests for agent.lc.graph_executor — the LangGraph tool-calling executor.

The tool-calling, step-limit and /stop suites of test_lc_runner run again
with AGENT_FLOW=graph, so both executors must behave the same.
"""

import unittest
from unittest.mock import patch

from langchain_core.messages import AIMessage

from agent.lc import graph_executor, runner, settings
import test_lc_runner as base


class _GraphFlow:
    """Mixin: force the graph executor for every test of the class."""

    def setUp(self):
        p = patch.object(runner.lc_settings, "agent_flow", return_value="graph")
        p.start()
        self.addCleanup(p.stop)
        spy = patch.object(
            graph_executor, "GraphAgentExecutor", wraps=graph_executor.GraphAgentExecutor
        )
        self.graph_spy = spy.start()
        self.addCleanup(spy.stop)
        super().setUp()

    def tearDown(self):
        super().tearDown()
        self.assertTrue(self.graph_spy.called, "graph executor was not used")


class TestGraphToolCalling(_GraphFlow, base.TestRunnerToolCalling):
    pass


class TestGraphIterationLimit(_GraphFlow, base.TestRunnerIterationLimit):
    pass


class TestGraphStop(_GraphFlow, base.TestRunnerStop):
    def test_stop_requested_before_tool_start_aborts(self):
        # The base test calls a tool that is not registered: AgentExecutor still
        # fires on_tool_start for it, while the graph's ToolNode answers the
        # model with an error message instead. Use a registered tool here.
        scripted = base.ScriptedToolCallingModel(
            responses=[
                AIMessage(
                    content="",
                    tool_calls=[{"name": "echo_tool", "args": {"x": "go"}, "id": "1"}],
                ),
                AIMessage(content="DONE"),
            ]
        )
        with base._patch_model(scripted), base._patch_config(), patch(
            "agent.db_feedback.insert_feedback", lambda *a, **k: None
        ), patch("agent.lc.runner.is_stop_requested", return_value=True):
            with self.assertRaises(base.StopRequestedError):
                runner.run_langchain_llm(
                    "gpt-4o", [], {"system_instruction": "sys", "tools": [base.echo_tool]},
                    "query", None, "sid", "mid", "messages_out",
                    provider="openai", api_key="k",
                )


class TestGraphExecutorDirect(unittest.TestCase):
    """Output shape seen by the runner."""

    def _executor(self, responses, max_iterations=5):
        model = base.ScriptedToolCallingModel(responses=responses)
        tools = runner.build_lc_tools([base.echo_tool])
        return graph_executor.GraphAgentExecutor(
            model, tools, "sys", max_iterations, runner._STOPPED_OUTPUT
        )

    def _call(self, call_id):
        return AIMessage(
            content="",
            tool_calls=[{"name": "echo_tool", "args": {"x": call_id}, "id": call_id}],
        )

    def test_returns_output_and_steps(self):
        result = self._executor([self._call("1"), AIMessage(content="DONE")]).invoke(
            {"input": "q", "chat_history": []}
        )
        self.assertEqual(result["output"], "DONE")
        [(step, observation)] = result["intermediate_steps"]
        self.assertEqual((step.tool, step.tool_input), ("echo_tool", {"x": "1"}))
        self.assertEqual(observation, "echoed:1")

    def test_limit_returns_stop_sentinel_with_steps(self):
        result = self._executor(
            [self._call("1"), self._call("2"), AIMessage(content="never")], max_iterations=2
        ).invoke({"input": "q"})
        self.assertEqual(result["output"], runner._STOPPED_OUTPUT)
        self.assertEqual(len(result["intermediate_steps"]), 2)
        self.assertIn("echoed:2", runner._steps_to_text(result["intermediate_steps"]))


class TestGraphToolErrors(unittest.TestCase):
    def test_tool_error_goes_back_to_the_model(self):
        def broken_tool(x: str) -> str:
            """Always fails."""
            raise RuntimeError("SMTP down")

        model = base.ScriptedToolCallingModel(responses=[
            AIMessage(content="", tool_calls=[{"name": "broken_tool", "args": {"x": "a"}, "id": "1"}]),
            AIMessage(content="Could not send: SMTP down."),
        ])
        executor = graph_executor.GraphAgentExecutor(
            model, runner.build_lc_tools([broken_tool]), "sys", 5, runner._STOPPED_OUTPUT
        )
        result = executor.invoke({"input": "send it"})
        self.assertEqual(result["output"], "Could not send: SMTP down.")
        [(step, observation)] = result["intermediate_steps"]
        self.assertEqual(observation, "Error executing broken_tool: SMTP down")

    def test_tool_feedback_shows_only_the_result(self):
        feedback = []
        handler = runner.FeedbackCallbackHandler(None, "t", "s", "m", True)
        handler._feedback = feedback.append
        from langchain_core.messages import ToolMessage

        handler.on_tool_end(ToolMessage(content="31°C", tool_call_id="1"), name="get_weather")
        self.assertEqual(feedback, ["⚙️ Executed tools: get_weather\nResults:\n- 31°C"])


class TestAgentFlowSetting(unittest.TestCase):
    def _flow(self, value):
        with patch.dict("os.environ", {"AGENT_FLOW": value}):
            return settings.agent_flow()

    def test_values(self):
        self.assertEqual(self._flow("graph"), "graph")
        self.assertEqual(self._flow(" GRAPH "), "graph")
        self.assertEqual(self._flow("legacy"), "legacy")
        self.assertEqual(self._flow("bogus"), "legacy")


if __name__ == "__main__":
    unittest.main()


class TestGraphExecutorSqliteThreads(unittest.TestCase):
    """The graph's tool node runs tools in a worker thread: the feedback
    callback and the /stop check must not use the caller's sqlite cursor there."""

    def setUp(self):
        import os
        import sqlite3
        import tempfile

        import database

        fd, self.db_path = tempfile.mkstemp(suffix=".db")
        os.close(fd)
        self.addCleanup(os.unlink, self.db_path)
        p = patch.object(database, "DB_PATH", self.db_path)
        p.start()
        self.addCleanup(p.stop)
        self.conn = sqlite3.connect(self.db_path)
        self.conn.execute(
            "CREATE TABLE messages_out (id TEXT, session_id TEXT, in_reply_to TEXT, content TEXT)"
        )
        self.conn.commit()
        self.addCleanup(self.conn.close)

    def test_tool_feedback_written_from_the_tool_thread(self):
        scripted = base.ScriptedToolCallingModel(
            responses=[
                AIMessage(content="", tool_calls=[{"name": "echo_tool", "args": {"x": "hi"}, "id": "1"}]),
                AIMessage(content="DONE"),
            ]
        )
        from agent.db_feedback import thread_safe_cursor

        # Mirrors execute_autonomous_loop, which wraps the cursor its /stop check uses.
        stop_cursor = thread_safe_cursor(self.conn.cursor())

        def stop_check():
            stop_cursor.execute("SELECT 1 FROM messages_out WHERE content = '/stop'")
            return stop_cursor.fetchone() is not None

        from agent.stop_check import reset_stop_check, set_stop_check

        token = set_stop_check(stop_check)
        try:
            with base._patch_model(scripted), base._patch_config(), \
                    patch.object(runner.lc_settings, "agent_flow", return_value="graph"):
                out = runner.run_langchain_llm(
                    "gpt-4o", [], {"system_instruction": "sys", "tools": [base.echo_tool]},
                    "query", self.conn.cursor(), "sid", "mid", "messages_out",
                    provider="openai", api_key="k",
                )
        finally:
            reset_stop_check(token)
        self.assertEqual(out, "DONE")
        rows = [r[0] for r in self.conn.execute("SELECT content FROM messages_out")]
        self.assertIn("⚙️ Executing local tool: echo_tool...", rows)
