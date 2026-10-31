"""LangGraph tool-calling executor (agent flow, phase 1).

Drop-in replacement for ``langchain_classic.agents.AgentExecutor`` built on
``langchain.agents.create_agent`` (a compiled LangGraph graph: model node ⇄
tools node). It exposes the same ``invoke(payload, config=...) -> dict`` shape
the runner already drives, so ``_invoke_with_retry``, the feedback callback,
``/stop`` and the max-iterations fallback answer work unchanged:

    {"output": str, "intermediate_steps": [(ToolStep, observation), ...]}

When the step limit is hit the graph raises ``GraphRecursionError``; this
executor keeps the last streamed state and returns the same stop sentinel the
AgentExecutor uses, so the runner generates its final answer from the steps.

Later phases add planner/evaluator nodes around this graph.
"""

from collections import namedtuple

def _tool_error_message(exc, request):
    """Send a failing tool's error back to the model, like the legacy loops.

    Without this a tool exception aborts the whole run, the model fallback
    retries it from scratch and runs every tool (e.g. send_email) again.
    A user /stop keeps propagating.
    """
    from agent.stop_check import StopRequestedError

    if isinstance(exc, StopRequestedError):
        return None
    return f"Error executing {request.tool_call['name']}: {exc}"


# Mirrors the ``AgentAction`` attributes read by ``runner._steps_to_text``.
ToolStep = namedtuple("ToolStep", ["tool", "tool_input", "tool_call_id"])


def _payload_to_messages(payload):
    """Flatten the runner's prompt payload into the graph's message list."""
    from langchain_core.messages import HumanMessage

    messages = list(payload.get("chat_history") or [])
    messages.append(HumanMessage(content=payload.get("input", "")))
    messages.extend(payload.get("input_media") or [])
    return messages


def _intermediate_steps(messages):
    """Pair every tool call of the run with the ToolMessage that answered it."""
    from langchain_core.messages import AIMessage, ToolMessage

    results = {
        m.tool_call_id: m.content for m in messages if isinstance(m, ToolMessage)
    }
    steps = []
    for m in messages:
        if isinstance(m, AIMessage):
            for call in m.tool_calls or []:
                call_id = call.get("id")
                if call_id in results:
                    steps.append(
                        (ToolStep(call.get("name"), call.get("args"), call_id), results[call_id])
                    )
    return steps


class GraphAgentExecutor:
    """``create_agent`` graph with an AgentExecutor-like ``invoke``."""

    def __init__(self, model, tools, system_message, max_iterations, stopped_output):
        from langchain.agents import create_agent
        from langchain.agents.middleware import ToolErrorMiddleware

        self._graph = create_agent(
            model, tools, system_prompt=system_message,
            middleware=[ToolErrorMiddleware(_tool_error_message)],
        )
        # One iteration = a model call that requests tools + the tools node,
        # i.e. two graph steps; the final answer fits in the last model step.
        self._recursion_limit = 2 * max_iterations
        self._stopped_output = stopped_output

    def invoke(self, payload, config=None):
        from langchain_core.messages import AIMessage
        from langgraph.errors import GraphRecursionError

        input_messages = _payload_to_messages(payload)
        run_config = dict(config or {})
        run_config["recursion_limit"] = self._recursion_limit

        state = {"messages": input_messages}
        try:
            for state in self._graph.stream(
                {"messages": input_messages}, config=run_config, stream_mode="values"
            ):
                pass
        except GraphRecursionError:
            new = state["messages"][len(input_messages):]
            return {"output": self._stopped_output, "intermediate_steps": _intermediate_steps(new)}

        new = state["messages"][len(input_messages):]
        last = new[-1] if new else None
        output = last.content if isinstance(last, AIMessage) else ""
        return {"output": output, "intermediate_steps": _intermediate_steps(new)}
