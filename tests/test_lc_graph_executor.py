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
