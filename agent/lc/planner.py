"""Planner (agent flow, phase 3).

An optional LLM call before the first executor round that turns the request
into a short list of steps. The plan is shown in the chat (📋 Execution Plan),
given to the executor as the steps to follow, and to the evaluator to check
step by step.

Like the evaluator, it goes through ``route_llm_call(..., summarize=True)``
(plain text, no tools, no AgentResponse contract) and asks for JSON in the
prompt, so every provider works.
"""

import logging
from typing import List, Optional

from pydantic import BaseModel, field_validator

from agent.lc.tools_lc import first_line_description
from agent.stop_check import StopRequestedError

logger = logging.getLogger(__name__)

_MAX_STEPS = 8


class Plan(BaseModel):
    needs_plan: bool = True
    steps: List[str] = []

    @field_validator("steps", mode="before")
    @classmethod
    def _clean_steps(cls, v):
        if v is None:
            return []
        if isinstance(v, str):
            v = [v]
        return [str(s).strip() for s in v if str(s).strip()][:_MAX_STEPS]


PLANNER_PROMPT = """You plan the work of an AI assistant before it starts.
Given the user's request and the tools the assistant can use, write the shortest list of concrete steps that fully answers the request: which tool to call for what, and in what order. The last step is answering the user.
Use only the tools listed. If information only the user can give is missing, the single step is asking the user for it.
{mode_rule}
Reply with only a JSON object, no markdown:
{{"needs_plan": <boolean>, "steps": ["<step 1>", "<step 2>"]}}"""

_AUTO_RULE = (
    'If the request is simple (a greeting, small talk, a question answered in one step), '
    'reply {"needs_plan": false, "steps": []}.'
)
_ALWAYS_RULE = "Always write a plan, even for a simple request."


def _tools_text(tool_funcs) -> str:
    lines = []
    for f in tool_funcs or []:
        name = getattr(f, "__name__", None)
        if name:
            lines.append(f"- {name}: {first_line_description(f)}")
    return "\n".join(lines) or "(no tools)"


def build_planner_input(user_request: str, tool_funcs) -> str:
    return f"USER REQUEST:\n{user_request}\n\nTOOLS:\n{_tools_text(tool_funcs)}"


def parse_plan(raw_text) -> Optional[Plan]:
    from agent.autonomous_loop import _parse_json_response

    parsed = _parse_json_response(raw_text or "")
    if not isinstance(parsed, dict):
        return None
    try:
        return Plan.model_validate(parsed)
    except Exception as exc:
        logger.debug("Plan validation failed (%s); raw=%r", exc, str(raw_text)[:200])
        return None


def format_plan(steps: List[str]) -> str:
    return "\n".join(f"{i}. {step}" for i, step in enumerate(steps, 1))


def make_plan(user_request, tool_funcs, mode, models, cursor, session_id, message_in_id,
              is_ide) -> List[str]:
    """Steps for the request, or [] when no plan is needed or none could be made.

    ``mode`` is 'auto' (the planner may decide a plan is not needed) or 'always'.
    """
    from agent.llm_router import route_llm_call
    from agent.openai_tools import reset_has_fallback_model, set_has_fallback_model

    prompt = PLANNER_PROMPT.format(mode_rule=_ALWAYS_RULE if mode == "always" else _AUTO_RULE)
    planner_input = build_planner_input(user_request, tool_funcs)
    for i, model_name in enumerate(models):
        # A 503 fails over fast while another model follows (same as the executor).
        fallback_token = set_has_fallback_model(i < len(models) - 1)
        try:
            raw = route_llm_call(
                model_name, [], {"system_instruction": prompt, "temperature": 0},
                planner_input, cursor, session_id, message_in_id, is_ide, summarize=True,
            )
        except StopRequestedError:
            raise
        except Exception as e:
            logger.warning("Planner model %s failed: %s", model_name, e)
            continue
        finally:
            reset_has_fallback_model(fallback_token)
        plan = parse_plan(raw)
        if plan is None:
            logger.warning("Planner model %s returned no valid plan: %r", model_name, str(raw)[:200])
            continue
        if mode != "always" and not plan.needs_plan:
            return []
        return plan.steps
    return []
