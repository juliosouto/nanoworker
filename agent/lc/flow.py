"""Agent flow graph: plan → execute → evaluate → retry or finalize.

Replaces the JSON self-assessment loop of ``autonomous_loop`` when
AGENT_FLOW=graph. The executor (the existing model fallback chain with tools)
answers in plain text; a separate evaluator returns a ``Verdict`` and the
graph routes on it:

    (plan) ──▶ execute ──▶ evaluate ──▶ finalize
                  ▲            │
                  └── retry ◀──┘  (needs_more_work, rounds left)

The optional plan node (AGENT_PLANNER, phase 3) runs once before the first
round; its steps go to the chat, the executor and the evaluator.

``done``, ``needs_user_input`` and ``failed`` all end the turn with the
executor's answer; only ``needs_more_work`` loops, carrying the evaluator's
``missing`` / ``next_instruction`` back to the executor. AUTONOMOUS_MODE is
the number of executor rounds; with 1 the evaluator is skipped entirely.
"""

import logging
import time
from contextlib import contextmanager
from typing import Any, List, Optional, TypedDict

from google.genai import types

from agent.db_feedback import insert_feedback
from agent.llm_usage import usage_stage
from agent.stop_check import StopRequestedError, is_stop_requested

logger = logging.getLogger(__name__)


@contextmanager
def _stage(name: str):
    """Usage tagging plus a duration log line for one flow node."""
    started = time.monotonic()
    try:
        with usage_stage(name):
            yield
    finally:
        logger.info("Agent flow %s took %.1fs", name, time.monotonic() - started)


class FlowState(TypedDict, total=False):
    plan: List[str]           # planner steps ([] = no plan)
    iteration: int            # executor rounds done
    send_content: list        # what the executor gets next
    answer: str               # last executor answer
    steps: list               # tool calls of the last executor round
    verdict: Optional[Any]    # evaluator.Verdict of the last answer


def _answer_text(raw) -> str:
    """The executor answers in plain text; a model that still emits the old
    AgentResponse JSON (e.g. a custom worker prompt) is unwrapped."""
    from agent.lc import outputs as lc_outputs

    parsed = lc_outputs.parse_agent_response(raw)
    if parsed is not None:
        return parsed.llm_response
    return raw or ""


def _user_request(initial_content) -> str:
    from agent.lc.runner import _content_to_text

    return _content_to_text(initial_content, sep="\n\n")


# Requests up to this many words count as simple: no planner in 'auto' mode,
# and no evaluator for a round that called no tool. Each of those is a full
# extra model call, which doubled or tripled the wait for a plain "oi".
_SIMPLE_REQUEST_WORDS = 15


def is_simple_request(user_request: str) -> bool:
    return len((user_request or "").split()) <= _SIMPLE_REQUEST_WORDS


def retry_instruction(verdict) -> str:
    """The message sent back to the executor for another round."""
    lines = ["Your previous answer does not fully address the request yet."]
    if verdict.reason:
        lines.append(f"Reviewer: {verdict.reason}")
    if verdict.missing:
        lines.append("Still missing:")
        lines.extend(f"- {item}" for item in verdict.missing)
    if verdict.next_instruction:
        lines.append(f"Next step: {verdict.next_instruction}")
    lines.append("Continue the work and reply with the complete answer for the user.")
    return "\n".join(lines)


def plan_message(steps) -> str:
    """The plan as the executor sees it, after the user's message."""
    from agent.lc.planner import format_plan

    return (
        "Plan for this request (follow it; adapt if a step turns out wrong or unnecessary):\n"
        f"{format_plan(steps)}"
    )


def build_flow(*, history, config_kwargs, models_to_try, evaluator_models, cursor,
               session_id, message_in_id, is_ide, limit, user_request, emit,
               planner_mode="off", planner_models=(), show_plan=True):
    """Compile the flow graph for one incoming message."""
    from langgraph.graph import END, START, StateGraph

    from agent.lc import evaluator, planner
    from agent.lc import runner as lc_runner
    from agent.llm_router import invoke_llm_with_fallback
    from agent.autonomous_loop import _strip_media_parts

    tool_funcs = config_kwargs.get("tools") or []
    simple = is_simple_request(user_request)
    use_planner = planner_mode == "always" or (
        planner_mode == "auto" and bool(tool_funcs) and not simple
    )

    def plan(state: FlowState) -> FlowState:
        with _stage("planner"):
            steps = planner.make_plan(
                user_request, tool_funcs, planner_mode, planner_models,
                cursor, session_id, message_in_id, is_ide,
            )
        if not steps:
            return {"plan": []}
        text = planner.format_plan(steps)
        if show_plan:
            emit(f"📋 Execution Plan:\n{text}")
        else:
            logger.info("Execution plan (hidden from chat):\n%s", text)
        return {
            "plan": steps,
            "send_content": list(state["send_content"]) + [plan_message(steps)],
        }

    def execute(state: FlowState) -> FlowState:
        # /stop between rounds (inside a round the runner checks it per tool).
        if is_stop_requested():
            raise StopRequestedError()
        steps: List = []
        token = lc_runner.set_tool_steps_sink(steps)
        try:
            with _stage("executor"):
                raw = invoke_llm_with_fallback(
                    history, config_kwargs, state["send_content"], models_to_try,
                    cursor, session_id, message_in_id, is_ide=is_ide, on_complete=emit.callback,
                )
        finally:
            lc_runner.reset_tool_steps_sink(token)
        return {
            "iteration": state.get("iteration", 0) + 1,
            "answer": _answer_text(raw),
            "steps": steps,
            "verdict": None,
        }

    def evaluate(state: FlowState) -> FlowState:
        with _stage("evaluator"):
            verdict = evaluator.evaluate(
                user_request, state["answer"], state.get("steps"), evaluator_models,
                cursor, session_id, message_in_id, is_ide, plan=state.get("plan"),
            )
        return {"verdict": verdict}

    def retry(state: FlowState) -> FlowState:
        verdict = state["verdict"]
        # The reviewer's reason is internal (English, about tools): log it and
        # keep the chat message the same as the legacy loop's.
        logger.info("Agent reflecting (%d/%d): %s", state["iteration"], limit, verdict.reason)
        emit(f"🔄 Agent reflecting (Iteration {state['iteration']}/{limit})...")
        # Media already seen by the model is not re-sent (same as the legacy loop).
        parts = [
            types.Part.from_text(text=p) if isinstance(p, str) else p
            for p in _strip_media_parts(state["send_content"])
        ]
        history.append(types.Content(role="user", parts=parts))
        history.append(types.Content(role="model", parts=[types.Part.from_text(text=state["answer"])]))
        return {"send_content": [types.Part.from_text(text=retry_instruction(verdict))]}

    def after_execute(state: FlowState) -> str:
        if state["iteration"] >= limit:
            return END
        # A short request answered without tools on the first round (greeting,
        # quick question): nothing for the evaluator to check, skip the call.
        # Once the evaluator asked for another round, it keeps checking.
        if simple and not state.get("steps") and state["iteration"] == 1:
            return END
        return "evaluate"

    def after_evaluate(state: FlowState) -> str:
        verdict = state.get("verdict")
        if verdict is not None and verdict.status == "needs_more_work":
            return "retry"
        return END

    graph = StateGraph(FlowState)
    graph.add_node("plan", plan)
    graph.add_node("execute", execute)
    graph.add_node("evaluate", evaluate)
    graph.add_node("retry", retry)
    graph.add_edge(START, "plan" if use_planner else "execute")
    graph.add_edge("plan", "execute")
    graph.add_conditional_edges("execute", after_execute, ["evaluate", END])
    graph.add_conditional_edges("evaluate", after_evaluate, ["retry", END])
    graph.add_edge("retry", "execute")
    return graph.compile()


class _Emitter:
    """Feedback to the chat: a DB row plus the optional realtime callback."""

    def __init__(self, cursor, table, session_id, message_in_id, on_complete):
        self._args = (cursor, table, session_id, message_in_id)
        self.callback = on_complete

    def __call__(self, text):
        try:
            insert_feedback(*self._args, text)
        except Exception:
            pass
        if self.callback:
            try:
                self.callback(text)
            except Exception as e:
                logger.warning("Failed to call on_complete: %s", e)


def run_agent_flow(history, config_kwargs, initial_content, models_to_try, cursor,
                   session_id, message_in_id, is_ide, limit, on_complete=None,
                   show_plan_in_chat=True) -> str:
    """Run the flow for one message and return the answer for the user.

    ``StopRequestedError`` propagates; the caller turns it into the /stop reply.
    """
    from agent.lc import settings as lc_settings

    table = "ide_messages_out" if is_ide else "messages_out"
    emit = _Emitter(cursor, table, session_id, message_in_id, on_complete)
    evaluator_model = lc_settings.evaluator_model()
    planner_model = lc_settings.planner_model()
    flow = build_flow(
        history=history,
        config_kwargs=config_kwargs,
        models_to_try=models_to_try,
        evaluator_models=[evaluator_model] if evaluator_model else list(models_to_try),
        cursor=cursor,
        session_id=session_id,
        message_in_id=message_in_id,
        is_ide=is_ide,
        limit=limit,
        user_request=_user_request(initial_content),
        emit=emit,
        planner_mode=lc_settings.planner_mode(),
        planner_models=[planner_model] if planner_model else list(models_to_try),
        show_plan=show_plan_in_chat,
    )
    send_content = list(initial_content) if isinstance(initial_content, list) else [initial_content]
    # plan once, then execute + evaluate + retry per round, plus slack.
    state = flow.invoke({"send_content": send_content}, config={"recursion_limit": 3 * limit + 5})
    verdict = state.get("verdict")
    if verdict is not None:
        logger.info("Agent flow finished after %d round(s): %s", state["iteration"], verdict.status)
    return state.get("answer", "")
