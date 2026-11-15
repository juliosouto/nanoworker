"""Recover tool calls that a model wrote as plain text.

Some open models (e.g. Qwen served through an OpenAI-compatible endpoint
without a matching tool-call parser) emit their native tool-call template in
the message content instead of structured ``tool_calls``:

    <tool_call>
    <function=web_search>
    <parameter=query>
    some query
    </parameter>
    </function>
    </tool_call>

or the Hermes/JSON variant ``<tool_call>{"name": ..., "arguments": {...}}</tool_call>``.
The agent then treats that text as the final answer and it reaches the user.
``recover_text_tool_calls`` turns those blocks into real ``tool_calls`` so the
agent executes them.
"""

import json
import logging
import re
import uuid

logger = logging.getLogger(__name__)

# The closing tag is optional: a truncated reply may stop before it.
_BLOCK_RE = re.compile(r"<tool_call>\s*(.*?)\s*(?:</tool_call>|\Z)", re.S)
_FUNCTION_RE = re.compile(r"<function=([^>\s]+)\s*>(.*?)(?:</function>|\Z)", re.S)
_PARAM_RE = re.compile(r"<parameter=([^>\s]+)\s*>(.*?)</parameter>", re.S)


def _content_text(content):
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        return "".join(
            b.get("text", "") if isinstance(b, dict) else str(b) for b in content
        )
    return ""


def _param_types(tool):
    """{param name: JSON-schema type} for a LangChain tool, empty when unknown."""
    try:
        return {k: (v or {}).get("type") for k, v in (tool.args or {}).items()}
    except Exception:
        return {}


def _coerce(value, schema_type):
    value = value.strip()
    if schema_type in (None, "string"):
        return value
    try:
        return json.loads(value)
    except (ValueError, TypeError):
        return value


def _parse_block(block, param_types):
    """Return (name, args) for one <tool_call> body, or None if unparseable."""
    if block.startswith("{"):
        try:
            data = json.loads(block)
        except ValueError:
            return None
        name = data.get("name")
        args = data.get("arguments", data.get("parameters", {}))
        if isinstance(args, str):
            try:
                args = json.loads(args)
            except ValueError:
                return None
        if not name or not isinstance(args, dict):
            return None
        return name, args

    match = _FUNCTION_RE.search(block)
    if not match:
        return None
    name, body = match.group(1), match.group(2)
    types = param_types.get(name, {})
    args = {
        key: _coerce(value, types.get(key))
        for key, value in _PARAM_RE.findall(body)
    }
    return name, args


def recover_text_tool_calls(message, tools):
    """Return ``message`` with text tool calls moved into ``tool_calls``.

    The original message is returned unchanged when it already has tool calls,
    has no ``<tool_call>`` block, or none of the blocks names a bound tool.
    """
    from langchain_core.messages import AIMessage

    if not isinstance(message, AIMessage) or message.tool_calls:
        return message
    text = _content_text(message.content)
    if "<tool_call>" not in text:
        return message

    param_types = {t.name: _param_types(t) for t in tools}
    calls = []
    for block in _BLOCK_RE.findall(text):
        parsed = _parse_block(block, param_types)
        if parsed is None:
            continue
        name, args = parsed
        if name not in param_types:
            logger.warning("Text tool call names an unknown tool: %s", name)
            continue
        calls.append({
            "name": name,
            "args": args,
            "id": f"call_{uuid.uuid4().hex[:24]}",
            "type": "tool_call",
        })
    if not calls:
        return message

    remaining = _BLOCK_RE.sub("", text).strip()
    logger.info(
        "Recovered %d tool call(s) written as text: %s",
        len(calls), ", ".join(c["name"] for c in calls),
    )
    return message.model_copy(update={"content": remaining, "tool_calls": calls})


class TextToolCallBinder:
    """Wraps a chat model for ``create_tool_calling_agent`` (legacy flow).

    ``bind_tools`` returns the provider's bound model followed by the recovery
    step, so the agent's output parser sees structured tool calls.
    """

    def __init__(self, model):
        self._model = model

    def bind_tools(self, tools, **kwargs):
        from langchain_core.runnables import RunnableLambda

        bound = self._model.bind_tools(tools, **kwargs)
        return bound | RunnableLambda(lambda m: recover_text_tool_calls(m, tools))

    def __getattr__(self, name):
        return getattr(self._model, name)


def text_tool_call_middleware(tools):
    """``create_agent`` middleware (graph flow) applying the same recovery."""
    from langchain.agents.middleware import AgentMiddleware

    class TextToolCallMiddleware(AgentMiddleware):
        def after_model(self, state, runtime):
            messages = state.get("messages") or []
            if not messages:
                return None
            last = messages[-1]
            fixed = recover_text_tool_calls(last, tools)
            if fixed is last:
                return None
            # Same id: the add_messages reducer replaces the original message.
            return {"messages": [fixed]}

    return TextToolCallMiddleware()
