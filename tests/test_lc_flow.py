"""Tests for the phase-2 agent flow: executor → evaluator → retry/finalize."""

import json
import unittest
from unittest.mock import MagicMock, patch

from google.genai import types as gt

from agent.autonomous_loop import execute_autonomous_loop
from agent.lc import evaluator, flow, runner
from agent.lc.evaluator import Verdict
from agent.lc.graph_executor import ToolStep
from agent.stop_check import StopRequestedError


def _verdict(status, **kw):
    return json.dumps({"status": status, **kw})


class _FlowCase(unittest.TestCase):
    """Runs execute_autonomous_loop with AGENT_FLOW=graph and scripted models."""

    def setUp(self):
        self.answers = []
        self.verdicts = []
        self.exec_calls = []
        self.eval_inputs = []
        self.feedback = []
        self.tool_steps = {}  # executor round -> steps reported by the runner

        def fake_invoke(history, config_kwargs, content, models, *a, **k):
            self.exec_calls.append(list(content))
            steps = self.tool_steps.get(len(self.exec_calls))
            sink = runner._tool_steps_sink.get()
            if steps and sink is not None:
                sink.extend(steps)
            return self.answers.pop(0)

        def fake_route(model_name, history, cfg, content, *a, summarize=False, **k):
            assert summarize, "the evaluator must use the plain-text backend"
            self.eval_inputs.append((model_name, cfg["system_instruction"], content))
            item = self.verdicts.pop(0)
            if isinstance(item, Exception):
                raise item
            return item

        patches = [
            patch("agent.lc.settings.graph_flow_enabled", return_value=True),
            patch("agent.lc.settings.evaluator_model", return_value=""),
            patch("agent.llm_router.invoke_llm_with_fallback", side_effect=fake_invoke),
            patch("agent.llm_router.route_llm_call", side_effect=fake_route),
            patch("agent.lc.flow.insert_feedback",
                  side_effect=lambda c, t, s, m, text: self.feedback.append(text)),
        ]
        for p in patches:
            p.start()
            self.addCleanup(p.stop)
        self.cursor = MagicMock()
        self.cursor.fetchone.return_value = None  # no /stop
        self.history = []

    def run_flow(self, limit, content="what is the weather?", models=("m1", "m2")):
        with patch("agent.autonomous_loop.get_config", return_value=str(limit)):
            return execute_autonomous_loop(
                self.history, {"system_instruction": "sys"}, [content], list(models),
                self.cursor, "sid", "mid", is_ide=False,
            )


class TestAgentFlow(_FlowCase):
    def test_limit_one_skips_the_evaluator(self):
        self.answers = ["sunny"]
        self.assertEqual(self.run_flow(1), "sunny")
        self.assertEqual(self.eval_inputs, [])

    def test_done_ends_after_one_round(self):
        self.answers = ["sunny"]
        self.verdicts = [_verdict("done", reason="answered")]
        self.assertEqual(self.run_flow(3), "sunny")
        self.assertEqual(len(self.exec_calls), 1)
        model, prompt, eval_input = self.eval_inputs[0]
        self.assertEqual(model, "m1")
        self.assertIn("needs_more_work", prompt)
        self.assertIn("what is the weather?", eval_input)
        self.assertIn("sunny", eval_input)

    def test_needs_more_work_retries_with_the_reviewer_instruction(self):
        self.answers = ["I will check.", "Sunny, 25°C."]
        self.verdicts = [
            _verdict("needs_more_work", reason="no forecast given",
                     missing=["temperature"], next_instruction="call the weather tool"),
            _verdict("done"),
        ]
        self.assertEqual(self.run_flow(3), "Sunny, 25°C.")
        retry_text = self.exec_calls[1][0].text
        self.assertIn("no forecast given", retry_text)
        self.assertIn("- temperature", retry_text)
        self.assertIn("call the weather tool", retry_text)
        # The first round moved into the history (user turn + model answer).
        self.assertEqual([c.role for c in self.history], ["user", "model"])
        self.assertEqual(self.history[1].parts[0].text, "I will check.")
        self.assertTrue(any(f.startswith("🔄 Agent reflecting (Iteration 1/3): no forecast")
                            for f in self.feedback))

    def test_needs_user_input_and_failed_end_the_turn(self):
        for status in ("needs_user_input", "failed"):
            with self.subTest(status=status):
                self.exec_calls.clear()
                self.answers = ["Which city?"]
                self.verdicts = [_verdict(status)]
                self.assertEqual(self.run_flow(5), "Which city?")
                self.assertEqual(len(self.exec_calls), 1)

    def test_limit_stops_the_loop_with_the_last_answer(self):
        self.answers = ["a1", "a2", "a3"]
        self.verdicts = [_verdict("needs_more_work"), _verdict("needs_more_work")]
        self.assertEqual(self.run_flow(3), "a3")
        self.assertEqual(len(self.exec_calls), 3)
        self.assertEqual(len(self.eval_inputs), 2)  # no verdict after the last round

    def test_invalid_verdict_falls_back_to_next_model_then_keeps_answer(self):
        self.answers = ["sunny"]
        self.verdicts = [RuntimeError("down"), "not json"]
        self.assertEqual(self.run_flow(3), "sunny")
        self.assertEqual([m for m, _, _ in self.eval_inputs], ["m1", "m2"])
        self.assertEqual(len(self.exec_calls), 1)

    def test_evaluator_model_setting_is_used(self):
        self.answers = ["sunny"]
        self.verdicts = [_verdict("done")]
        with patch("agent.lc.settings.evaluator_model", return_value="cheap"):
            self.run_flow(3)
        self.assertEqual(self.eval_inputs[0][0], "cheap")

    def test_tool_results_reach_the_evaluator(self):
        step = ToolStep("weather", {"city": "Rio"}, "1")
        self.tool_steps = {1: [(step, "25°C")]}
        self.answers = ["Sunny, 25°C."]
        self.verdicts = [_verdict("done")]
        self.run_flow(3)
        self.assertIn("weather({'city': 'Rio'}) -> 25°C", self.eval_inputs[0][2])

    def test_legacy_json_answer_is_unwrapped(self):
        self.answers = [json.dumps({
            "user_prompt": "q", "llm_response": "plain answer",
            "is_the_user_request_completely_satisfied": True,
        })]
        self.assertEqual(self.run_flow(1), "plain answer")

    def test_stop_between_rounds_returns_the_stop_message(self):
        self.answers = ["a1", "a2"]
        self.verdicts = [_verdict("needs_more_work")]
        self.cursor.fetchone.side_effect = [None, {"id": "stop"}]  # polled once per round
        out = self.run_flow(3)
        self.assertIn("/stop", out)
        self.assertEqual(len(self.exec_calls), 1)

    def test_stop_inside_executor_returns_the_stop_message(self):
        with patch("agent.llm_router.invoke_llm_with_fallback", side_effect=StopRequestedError()):
            self.assertIn("/stop", self.run_flow(3))


class TestVerdict(unittest.TestCase):
    def test_parse_variants(self):
        v = evaluator.parse_verdict('```json\n{"status": " DONE ", "missing": "x"}\n```')
        self.assertEqual((v.status, v.missing), ("done", ["x"]))
        self.assertIsNone(evaluator.parse_verdict('{"status": "maybe"}'))
        self.assertIsNone(evaluator.parse_verdict("no json"))

    def test_retry_instruction_without_details(self):
        text = flow.retry_instruction(Verdict(status="needs_more_work"))
        self.assertIn("does not fully address", text)
        self.assertNotIn("Still missing", text)


class TestNoContractInGraphFlow(unittest.TestCase):
    def test_prompt_has_no_json_contract(self):
        from agent.lc import prompts

        cursor = MagicMock()
        cursor.fetchall.return_value = []
        with patch("agent.lc.settings.graph_flow_enabled", return_value=True):
            text = prompts.build_system_prompt(cursor=cursor, worker={"worker_instructions": "Be nice"})
        self.assertIn("Be nice", text)
        self.assertNotIn("is_the_user_request_completely_satisfied", text)

    def test_router_skips_structured_output(self):
        from agent import llm_router

        conn = MagicMock()
        conn.cursor.return_value.fetchone.return_value = None
        seen = {}

        def fake_runner(model_name, history, kwargs, *a, **k):
            seen.update(kwargs)
            return "ok"

        with patch("agent.lc.settings.graph_flow_enabled", return_value=True), \
                patch("agent.lc.settings.stack_enabled", return_value=True), \
                patch("database.get_db", return_value=conn), \
                patch("agent.lc.runner.run_langchain_llm", side_effect=fake_runner):
            llm_router.route_llm_call("gpt-4o", [], {"system_instruction": "sys"}, "hi",
                                      MagicMock(), "sid", "mid", False)
        self.assertEqual(seen["system_instruction"], "sys")
        self.assertNotIn("lc_openai_response_format", seen)


if __name__ == "__main__":
    unittest.main()
