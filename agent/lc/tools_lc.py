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
import re
from typing import Any, Callable, Dict, List

from google.genai import types
from langchain_core.tools import StructuredTool

from agent.lc import settings as lc_settings

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
    """Convert a list of Python tool functions into ``StructuredTool`` objects."""
    return [lc_tool(f) for f in funcs]


def gemini_tool_declarations(funcs: List[Callable]) -> List[types.Tool]:
    """Build explicit genai ``types.Tool`` / ``FunctionDeclaration`` schemas.

    Used by the Gemini loop so the SDK does not pull the full docstring as the
    description; instead only the short first-line description + the legacy-parity
    parameter schema are used.
    """
    result: List[types.Tool] = []
    for func in funcs:
        func_decl = types.FunctionDeclaration(
            name=func.__name__,
            description=first_line_description(func),
            parameters=types.Schema(**tool_param_schema(func)),
        )
        result.append(types.Tool(function_declarations=[func_decl]))
    return result
