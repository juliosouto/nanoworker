"""Answer evaluator (agent flow, phase 2).

A separate LLM call that judges the executor's answer instead of trusting the
executor's own ``is_the_user_request_completely_satisfied`` flag. It returns a
``Verdict`` with one of four statuses, so the flow can tell "keep working"
from "ask the user" and "give up", and pass a concrete next step back to the
executor.

The call goes through ``route_llm_call(..., summarize=True)``: the plain-text
backend that already resolves each model's provider and key from llm_config
and never adds the AgentResponse contract or tools. The verdict JSON is asked
for in the prompt and parsed leniently, so every provider works.
"""

import json
import logging
from typing import List, Literal, Optional

from pydantic import BaseModel, field_validator

from agent.stop_check import StopRequestedError

logger = logging.getLogger(__name__)

VERDICT_STATUSES = ("done", "needs_more_work", "needs_user_input", "failed")

# Tool results are capped so a big page or file never dominates the prompt.
_TOOL_RESULT_CHARS = 1500
_MAX_TOOL_STEPS = 20


class Verdict(BaseModel):
    """The evaluator's judgement of one executor answer."""

    status: Literal["done", "needs_more_work", "needs_user_input", "failed"]
    reason: str = ""
    missing: List[str] = []
    next_instruction: Optional[str] = None

    @field_validator("status", mode="before")
    @classmethod
    def _normalize_status(cls, v):
        return str(v or "").strip().lower()

    @field_validator("missing", mode="before")
    @classmethod
    def _missing_as_list(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            return [v] if v.strip() else []
        return v


EVALUATOR_PROMPT = """You review the work of an AI assistant before its answer is sent to the user.
You get the user's request, the tool calls the assistant made with their results, and the assistant's answer.
Decide which status fits:
- "done": the answer fully addresses the request. Partial answers that honestly say what could not be done also count when nothing more can be tried.
- "needs_more_work": the assistant can still make progress on its own (another tool call, a different approach, a missing part of the request). Say exactly what is missing and what to do next.
- "needs_user_input": the answer asks the user for information only they can give, or the request is ambiguous. This ends the turn; the question goes to the user.
- "failed": a tool or system error that cannot be worked around prevents the request.
When a plan is given, check it step by step: an unfinished step means "needs_more_work", unless it turned out unnecessary or impossible.
Also mark "needs_more_work" when the answer claims an action (sent, saved, scheduled, searched...) that no tool result shows.
Reply with only a JSON object, no markdown:
{"status": "<one of the four>", "reason": "<one short sentence>", "missing": ["<what is still missing>"], "next_instruction": "<concrete next step for the assistant, or null>"}"""


def _format_steps(steps) -> str:
    lines = []
    for action, observation in list(steps or [])[-_MAX_TOOL_STEPS:]:
        tool = getattr(action, "tool", "tool")
        tool_input = getattr(action, "tool_input", "")
        result = str(observation)
        if len(result) > _TOOL_RESULT_CHARS:
            result = result[:_TOOL_RESULT_CHARS] + "... [truncated]"
        lines.append(f"- {tool}({tool_input}) -> {result}")
    return "\n".join(lines) or "(no tool calls)"


def build_evaluation_input(user_request: str, answer: str, steps, plan=None) -> str:
    from agent.lc.planner import format_plan

    plan_block = f"PLAN:\n{format_plan(plan)}\n\n" if plan else ""
    return (
        f"USER REQUEST:\n{user_request}\n\n"
        f"{plan_block}"
        f"TOOL CALLS:\n{_format_steps(steps)}\n\n"
        f"ASSISTANT ANSWER:\n{answer}"
    )


def parse_verdict(raw_text) -> Optional[Verdict]:
    """Parse the evaluator's reply; None when it is not a valid verdict."""
    from agent.autonomous_loop import _parse_json_response

    parsed = _parse_json_response(raw_text or "")
    if not isinstance(parsed, dict):
        return None
    try:
        return Verdict.model_validate(parsed)
    except Exception as exc:
        logger.debug("Verdict validation failed (%s); raw=%r", exc, str(raw_text)[:200])
        return None


def evaluate(user_request, answer, steps, models, cursor, session_id, message_in_id,
             is_ide, plan=None) -> Optional[Verdict]:
    """Ask the evaluator models, in order, for a verdict on ``answer``.

    Returns None when no model produces a valid verdict; the flow then keeps
    the answer instead of looping on an unknown state.
    """
    from agent.llm_router import route_llm_call
    from agent.openai_tools import reset_has_fallback_model, set_has_fallback_model

    eval_input = build_evaluation_input(user_request, answer, steps, plan)
    for i, model_name in enumerate(models):
        # A 503 fails over fast while another model follows (same as the executor).
        fallback_token = set_has_fallback_model(i < len(models) - 1)
        try:
            raw = route_llm_call(
                model_name, [], {"system_instruction": EVALUATOR_PROMPT, "temperature": 0},
                eval_input, cursor, session_id, message_in_id, is_ide, summarize=True,
            )
        except StopRequestedError:
            raise
        except Exception as e:
            logger.warning("Evaluator model %s failed: %s", model_name, e)
            continue
        finally:
            reset_has_fallback_model(fallback_token)
        verdict = parse_verdict(raw)
        if verdict is not None:
            logger.info("Evaluator verdict: %s", json.dumps(verdict.model_dump(), ensure_ascii=False))
            return verdict
        logger.warning("Evaluator model %s returned no valid verdict: %r", model_name, str(raw)[:200])
    return None
