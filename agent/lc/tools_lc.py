"""LangChain-native tool adapter for phase 4 (slim tool schemas + result caps).

This module is the source of truth for how tools are presented to the LLM:

  * ``lc_tool`` turns a Python tool into a ``StructuredTool`` whose description
    is only the FIRST LINE of the docstring, leaving the full docstring (and
    therefore the ``/settings/tools`` UI and any full-text indexing) untouched.

  * ``@cap_tool_result`` caps execution results to ``LC_TOOL_RESULT_MAX_CHARS``
    characters, so a single giant tool output can never flood the context window
    (it benefits the legacy OpenAI loop, the Gemini loop and the future langchain
    stack alike).

  * ``gemini_tool_declarations`` builds explicit ``FunctionDeclaration`` schemas
    for the Google genai SDK, replacing the SDK's implicit conversion that
    otherwise consumes the full docstring as description.

The schema changes are gated behind ``LC_TOOL_COMPACT_SCHEMA`` (default 'on'),
so they can be flipped off without any code revert. The ``@cap_tool_result``
decorator is not gated: it is controlled by ``LC_TOOL_RESULT_MAX_CHARS``
(0 disables it; otherwise the default is 6000).
"""

import functools
import inspect
import json
import logging
import re
from typing import Any, Callable, Dict, List

from google.genai import types
from langchain_core.tools import StructuredTool

from agent.lc import settings as lc_settings

logger = logging.getLogger(__name__)

# Marker appended to truncated tool results so the model knows to narrow the query.
TRUNCATION_MARKER = "[truncated — narrow your query for full data]"

# Matches the legacy schema-building behaviour in ``openai_tools.py``:
#   param_desc = "Parameter {name}"  unless a docstring line defines it.
_TYPE_MAP = {
    str: "string",
    int: "integer",
    float: "number",
    bool: "boolean",
    list: "array",
    dict: "object",
}

_PYDANTIC_TYPE_MAP = {
    "string": str,
    "integer": int,
    "number": float,
    "boolean": bool,
    "array": list,
    "object": dict,
}


def first_line_description(func: Callable) -> str:
    """Short description: first non-empty line of the docstring.

    Falls back to a generic sentence when the function has no docstring.
    The full docstring is left intact on the function itself.
    """
    doc = getattr(func, "__doc__", "") or ""
    for line in doc.splitlines():
        line = line.strip()
        if line:
            return line
    return f"Executes {func.__name__}"


def tool_param_schema(func: Callable) -> Dict[str, Any]:
    """JSON schema properties for the parameters of ``func`` (legacy parity).

    Rebuilds exactly what ``openai_tools.convert_to_openai_tool`` builds:
    python-type -> json-schema-type, first docstring line that names the param
    as description, and ``enum`` for ``Must be one of: ...`` hints.
    """
    doc = getattr(func, "__doc__", "") or ""
    sig = inspect.signature(func)
    properties: Dict[str, Any] = {}
    required: List[str] = []

    for name, param in sig.parameters.items():
        if name in ("self", "args", "kwargs"):
            continue

        py_type = param.annotation
        json_type = _TYPE_MAP.get(py_type, "string")
        if json_type == "string" and py_type not in _TYPE_MAP:
            # Unknown annotation: do not lie about the type.
            json_type = "string"

        param_desc = f"Parameter {name}"
        if doc:
            for line in doc.splitlines():
                if f"{name}:" in line or f"{name} " in line:
                    parts = line.split(":", 1)
                    if len(parts) > 1:
                        param_desc = parts[1].strip()
                        break

        prop: Dict[str, Any] = {"type": json_type, "description": param_desc}

        one_of = re.search(r"Must be one of[:\s]*([^.]+)", param_desc)
        if one_of:
            choices = [
                v.strip().strip("'\"")
                for v in re.split(r"[,]\s*|\bor\b", one_of.group(1))
                if v.strip()
            ]
            if len(choices) >= 2:
                prop["enum"] = choices

        properties[name] = prop
        if param.default is inspect.Parameter.empty:
            required.append(name)

    return {"type": "object", "properties": properties, "required": required}


def _build_args_schema(func: Callable) -> Any:
    """Pydantic args_schema built manually (deterministic, no docstring parser)."""
    try:
        from pydantic import create_model, Field
    except ImportError:  # pragma: no cover - pydantic is a langchain hard dep
        from pydantic_v1 import create_model, Field  # type: ignore

    schema = tool_param_schema(func)
    sig = inspect.signature(func)
    fields: Dict[str, Any] = {}
    for pname, pdef in schema["properties"].items():
        param = sig.parameters.get(pname)
        field_type = _PYDANTIC_TYPE_MAP.get(pdef["type"], str)
        if param is not None and param.default is not inspect.Parameter.empty:
            fields[pname] = (field_type, Field(default=param.default, description=pdef.get("description", "")))
        else:
            fields[pname] = (field_type, Field(description=pdef.get("description", "")))
    return create_model(f"{func.__name__}Args", **fields)


def cap_tool_result(func: Callable) -> Callable:
    """Decorator that caps the tool's execution result to LC_TOOL_RESULT_MAX_CHARS.

    The wrapper keeps the function's name, docstring and signature intact
    (``functools.wraps``), so schemas, permission checks and the
    ``/settings/tools`` UI all continue to work unchanged.
    """
    marker = TRUNCATION_MARKER

    @functools.wraps(func)
    def wrapper(*args: Any, **kwargs: Any) -> Any:
        result = func(*args, **kwargs)
        text = str(result)
        max_chars = lc_settings.tool_result_max_chars()
        if max_chars > 0 and len(text) > max_chars:
            keep = max_chars - len(marker)
            text = text[:keep] + marker if keep > 0 else text[:max_chars]
        return text

    wrapper.__lc_capped__ = True  # marker so cap_tools stays idempotent
    return wrapper


def cap_tools(funcs: List[Callable]) -> List[Callable]:
    """Apply ``@cap_tool_result`` to every tool, skipping already-capped ones."""
    return [
        cap_tool_result(f) if not getattr(f, "__lc_capped__", False) else f
        for f in funcs
    ]


def lc_tool(func: Callable) -> StructuredTool:
    """Build a ``StructuredTool`` for a single Python tool.

    Description = first line of the docstring (slim schema). The args schema is
    built from the signature + the same parameter-description heuristics used by
    the legacy OpenAI converter, so enums and per-param hints stay intact.
    """
    args_schema = _build_args_schema(func)
    return StructuredTool.from_function(
        func=func,
        name=func.__name__,
        description=first_line_description(func),
        args_schema=args_schema,
    )


def build_lc_tools(funcs: List[Callable]) -> List[StructuredTool]:
    """Convert a list of Python tool functions into ``StructuredTool`` objects.

    A single tool whose schema cannot be built (e.g. a user-authored tool from
    ``tool_creator`` with a docstring that breaks the parser) is skipped with a
    warning instead of crashing the whole LLM call — same resilience as the
    legacy OpenAI converter in ``agent/openai_tools.py``.
    """
    tools: List[StructuredTool] = []
    for f in funcs:
        try:
            tools.append(lc_tool(f))
        except Exception as conv_err:
            logger.warning(
                "Skipping tool '%s': LangChain schema build failed (%s)",
                getattr(f, "__name__", "?"),
                conv_err,
            )
    return tools


def gemini_tool_declarations(funcs: List[Callable]) -> List[types.Tool]:
    """Build explicit genai ``types.Tool`` / ``FunctionDeclaration`` schemas.

    Used by the Gemini loop so the SDK does not pull the full docstring as the
    description; instead only the short first-line description + the legacy-parity
    parameter schema are used. A tool that cannot be converted is skipped with a
    warning instead of crashing the whole Gemini call.
    """
    result: List[types.Tool] = []
    for func in funcs:
        try:
            func_decl = types.FunctionDeclaration(
                name=func.__name__,
                description=first_line_description(func),
                parameters=types.Schema(**tool_param_schema(func)),
            )
            result.append(types.Tool(function_declarations=[func_decl]))
        except Exception as conv_err:
            logger.warning(
                "Skipping tool '%s': Gemini declaration build failed (%s)",
                getattr(func, "__name__", "?"),
                conv_err,
            )
    return result


# System prompt for the opt-in tool relevance selector (TOOL_RELEVANCE_FILTER).
# Biased toward over-inclusion ("when unsure, include it") so a borderline
# message can never strand the model without a tool it needed.
_RELEVANCE_SYSTEM_PROMPT = (
    "You are a tool selector. You receive the user's message and a catalog of "
    "available tools (name: short description). Decide which tools are actually "
    "needed to fulfill the request. Respond with ONLY a JSON array of tool "
    "names, e.g. [\"web_search\", \"send_whatsapp_file\"]. Rules: include a tool "
    "only if the request plausibly needs it; when unsure, include it; never "
    "invent tool names; if no tool is needed, return []."
)


def _message_text(content) -> str:
    """Flattens multimodal message content into plain text for the selector."""
    if isinstance(content, str):
        return content
    if isinstance(content, list):
        parts = []
        for p in content:
            if isinstance(p, str):
                parts.append(p)
            elif isinstance(p, dict):
                t = p.get("text") or p.get("content") or ""
                if t:
                    parts.append(str(t))
            else:
                t = getattr(p, "text", None)
                if t:
                    parts.append(str(t))
        return " ".join(parts)
    return str(content or "")


def _resolve_selector_credentials(model_name):
    """Resolves ``(provider, api_key)`` for the relevance-selector model.

    Mirrors ``route_llm_call``: the decrypted ``llm_config`` row for the model
    is the source of truth; for Gemini models with no row (or no key there) it
    falls back to the ``GEMINI_API_KEY`` app_config value (``set_config``
    encrypts sensitive keys, so it is decrypted too — ``decrypt_value`` returns
    plain text unchanged on any failure). ``make_chat_model`` does NOT resolve
    keys itself, so without this the selector could never reach a provider.
    Any failure returns ``(None, None)``: ``make_chat_model`` then raises and
    the filter fails open with the full tool set.
    """
    try:
        from database import decrypt_value, get_config, get_db

        from agent.lc.models import resolve_provider

        provider = None
        api_key = None
        conn = get_db()
        try:
            c = conn.cursor()
            c.execute(
                "SELECT provider, api_key FROM llm_config WHERE model_name = ?",
                (model_name,),
            )
            row = c.fetchone()
        finally:
            conn.close()
        if row:
            try:
                provider = row["provider"].lower() if row["provider"] else None
            except (KeyError, IndexError, TypeError):
                provider = None
            try:
                if row["api_key"]:
                    api_key = decrypt_value(row["api_key"])
            except (KeyError, IndexError, TypeError):
                api_key = None
        if not api_key:
            try:
                if resolve_provider(provider, model_name) == "gemini":
                    raw = get_config("GEMINI_API_KEY", None)
                    if raw:
                        api_key = decrypt_value(raw)
            except Exception:
                pass
        return provider, api_key
    except Exception:
        return None, None


def filter_tools_by_relevance(
    funcs: List[Callable], content, model_name: str = None
) -> List[Callable]:
    """Narrow ``funcs`` to the tools relevant to the user's message (opt-in).

    Gated behind ``TOOL_RELEVANCE_FILTER`` (advanced settings toggle, default
    off). When on, ONE lightweight LangChain chat call receives the tool
    catalog (name + first-line docstring) and the user message, and answers
    with a JSON array of the tool names it needs.

    Fail-open contract: ANY problem (flag off, empty message, selector error,
    unparseable output, empty or unknown selection) returns the ORIGINAL list
    unchanged, so enabling the feature can never break a conversation.
    """
    if not funcs:
        return funcs
    if not lc_settings.tool_relevance_filter():
        return funcs

    try:
        message_text = _message_text(content).strip()
        if not message_text:
            return funcs

        from agent.lc.models import make_chat_model

        catalog = "\n".join(
            f"- {f.__name__}: {first_line_description(f)}" for f in funcs
        )
        selector_name = (
            model_name
            or lc_settings.summarizer_model()
            or "gemini-2.0-flash"
        )
        provider, api_key = _resolve_selector_credentials(selector_name)
        model = make_chat_model(
            selector_name, provider=provider, api_key=api_key, temperature=0
        )
        response = model.invoke(
            [
                ("system", _RELEVANCE_SYSTEM_PROMPT),
                (
                    "human",
                    f"Available tools:\n{catalog}\n\n"
                    f"User message:\n{message_text[:4000]}",
                ),
            ]
        )
        raw = getattr(response, "content", response)
        if not isinstance(raw, str):
            raw = str(raw)

        match = re.search(r"\[.*\]", raw, re.DOTALL)
        if not match:
            logger.warning(
                "Tool relevance filter: no JSON array in selector output; "
                "keeping all %d tools",
                len(funcs),
            )
            return funcs
        chosen = json.loads(match.group(0))
        if not isinstance(chosen, list):
            return funcs

        valid = {f.__name__: f for f in funcs}
        picked = [n for n in chosen if isinstance(n, str) and n in valid]
        if not picked:
            logger.warning(
                "Tool relevance filter: empty/unknown selection; keeping all "
                "%d tools",
                len(funcs),
            )
            return funcs

        filtered = [valid[n] for n in picked]
        logger.info(
            "Tool relevance filter: %d/%d tools selected (%s)",
            len(filtered),
            len(funcs),
            ", ".join(picked[:8]),
        )
        return filtered
    except Exception as e:
        logger.warning(
            "Tool relevance filter failed (%s); keeping all %d tools",
            e,
            len(funcs),
        )
        return funcs
