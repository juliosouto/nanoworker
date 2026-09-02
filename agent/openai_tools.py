"""
OpenAI tool schema conversion and the shared execution loop
for OpenAI-compatible LLM providers (OpenAI, Groq, Qwen).
"""
import inspect
import json
import re
import time
import uuid

from agent.db_feedback import insert_feedback
from database import get_config


def convert_to_openai_tool(func) -> dict:
    """
    Converts a Python function into an OpenAI compatible tool schema.
    """
    name = func.__name__

    # Docstring parsing for description
    doc = func.__doc__ or ""
    description = doc.strip().split("\n\n")[0].strip() if doc else f"Executes function {name}"

    sig = inspect.signature(func)
    properties = {}
    required = []

    # Type map Python to JSON Schema
    type_map = {
        str: "string",
        int: "integer",
        float: "number",
        bool: "boolean",
        list: "array",
        dict: "object"
    }

    for param_name, param in sig.parameters.items():
        if param_name in ["self", "args", "kwargs"]:
            continue

        param_type = type_map.get(param.annotation, "string")

        # Simple extraction of parameter description from docstring if present
        param_desc = f"Parameter {param_name}"
        if doc:
            for line in doc.split("\n"):
                if f"{param_name}:" in line or f"{param_name} " in line:
                    parts = line.split(":", 1)
                    if len(parts) > 1:
                        param_desc = parts[1].strip()
                        break

        properties[param_name] = {
            "type": param_type,
            "description": param_desc
        }

        # Detect fixed-choice values ("Must be one of: 'a', 'b', 'c'.") and expose
        # them as an enum so small models don't send invalid values.
        one_of = re.search(r"Must be one of[:\s]*([^.]+)", param_desc)
        if one_of:
            choices = [v.strip().strip("'\"") for v in re.split(r"[,]|\bor\b", one_of.group(1)) if v.strip()]
            if len(choices) >= 2:
                properties[param_name]["enum"] = choices

        if param.default == inspect.Parameter.empty:
            required.append(param_name)

    return {
        "type": "function",
        "function": {
            "name": name,
            "description": description[:1024],
            "parameters": {
                "type": "object",
                "properties": properties,
                "required": required
            }
        }
    }


def _describe_tool_args(func) -> str:
    """Returns a human-readable list of a function's parameters for error feedback."""
    try:
        sig = inspect.signature(func)
    except Exception:
        return "(signature unavailable)"
    parts = []
    for pname, param in sig.parameters.items():
        if pname in ("self", "args", "kwargs"):
            continue
        default = "" if param.default is inspect.Parameter.empty else f" (default: {param.default!r})"
        parts.append(f"{pname}{default}")
    return ", ".join(parts) if parts else "(no arguments)"


def execute_openai_compatible_llm(client, model_name: str, history: list, config_kwargs: dict, content, cursor, session_id: str, message_in_id: str, table: str, limit_tokens: int = None, on_complete=None) -> str:
    """
    Unified recursive executor loop for OpenAI-compatible LLM providers that dynamically
    converts tools and executes python function calls.
    """
    # 1. Map history and content to OpenAI format
    messages = []
    show_tools_results = config_kwargs.pop("show_tools_results", True)

    if "system_instruction" in config_kwargs:
        messages.append({"role": "system", "content": config_kwargs["system_instruction"]})

    for msg in history:
        role = "user" if msg.role == "user" else "assistant"
        text_parts = [p.text for p in msg.parts if getattr(p, 'text', None)]
        messages.append({"role": role, "content": " ".join(text_parts)})

    if isinstance(content, list):
        text_parts = []
        for p in content:
            if isinstance(p, str):
                text_parts.append(p)
            elif getattr(p, 'text', None):
                text_parts.append(p.text)
    else:
        text_parts = [content]
    messages.append({"role": "user", "content": " ".join([t for t in text_parts if t])})

    # 2. Convert raw python functions into OpenAI tool schemas
    permitted_tools = config_kwargs.get("tools", [])
    openai_tools = [convert_to_openai_tool(f) for f in permitted_tools] if permitted_tools else None

    # Normalize model name for reasoning detection
    model_lower = model_name.lower()
    model_base = model_lower.split("/")[-1] if "/" in model_lower else model_lower
    is_reasoning = model_base.startswith("o1") or model_base.startswith("o3") or "nano" in model_base

    try:
        max_iterations = int(get_config("AUTONOMOUS_MODE", "10"))
    except Exception:
        max_iterations = 10
    
    try:
        agent_name = get_config("agent_name", "Agent")
    except Exception:
        agent_name = "Agent"

    # 3. Tool execution loop
    iteration = 0
    while iteration < max_iterations:
        call_args = {
            "model": model_name,
            "messages": messages,
        }
        if openai_tools:
            call_args["tools"] = openai_tools

        if not is_reasoning:
            call_args["temperature"] = config_kwargs.get("temperature", 1.0)
            if limit_tokens:
                call_args["max_tokens"] = limit_tokens
        else:
            if limit_tokens:
                call_args["max_completion_tokens"] = limit_tokens

        try:
            response = client.chat.completions.create(**call_args)
        except Exception as e:
            err_msg = str(e).lower()
            if "max_tokens" in err_msg or "unsupported" in err_msg or "parameter" in err_msg:
                fallback_args = {
                    "model": model_name,
                    "messages": messages,
                }
                if openai_tools:
                    fallback_args["tools"] = openai_tools
                if limit_tokens:
                    fallback_args["max_completion_tokens"] = limit_tokens
                response = client.chat.completions.create(**fallback_args)
            else:
                raise e

        if not response.choices:
            iteration += 1
            if iteration >= max_iterations:
                return "Error: Model returned empty responses after maximum retries."
            insert_feedback(cursor, table, session_id, message_in_id,
                f"⚠️ Empty response from model (attempt {iteration}/{max_iterations}). Retrying...")
            time.sleep(2)
            continue

        message = response.choices[0].message
        tool_calls = getattr(message, 'tool_calls', None)

        if not tool_calls:
            # We reached the final text answer, return it
            return message.content or ""

        # We have tool calls!
        # A. Append assistant message with tool calls to standard OpenAI history
        serialized_tool_calls = []
        for tc in tool_calls:
            serialized_tool_calls.append({
                "id": tc.id,
                "type": "function",
                "function": {
                    "name": tc.function.name,
                    "arguments": tc.function.arguments
                }
            })
        messages.append({
            "role": "assistant",
            "content": message.content,
            "tool_calls": serialized_tool_calls
        })

        # B. Execute the tools in Python and log feedback in the output table
        tools_used = []
        tool_results = []
        for tc in tool_calls:
            tool_name = tc.function.name
            arguments_str = tc.function.arguments

            # Parse the model's JSON arguments defensively, giving small models
            # actionable feedback instead of swallowing errors silently.
            args = {}
            args_error = None
            if arguments_str:
                try:
                    args = json.loads(arguments_str)
                    if not isinstance(args, dict):
                        args_error = f"expected a JSON object but got a {type(args).__name__}"
                except Exception as je:
                    args_error = f"invalid JSON ({str(je)})"

            # Log execution starting
            msg_start = f"⚙️ Executing local tool: {tool_name}..."
            insert_feedback(cursor, table, session_id, message_in_id, msg_start)

            tool_func = next(
                (f for f in permitted_tools if getattr(f, '__name__', '') == tool_name),
                None,
            )
            result = "Tool not found"
            if tool_func is None:
                available = ", ".join(
                    sorted(getattr(f, '__name__', '') for f in permitted_tools)) or "none"
                result = (f"Error: tool '{tool_name}' does not exist. "
                          f"Available tools: {available}. Call one of these instead.")
            elif args_error:
                expected = _describe_tool_args(tool_func)
                result = (f"Error: arguments for {tool_name} could not be parsed ({args_error}). "
                          f"Expected arguments: {expected}. "
                          f"Provide a valid JSON object with ONLY those keys.")
            else:
                try:
                    result = tool_func(**args)
                except TypeError as te:
                    expected = _describe_tool_args(tool_func)
                    result = (f"Error executing {tool_name}: {str(te)}. "
                              f"Expected arguments: {expected}.")
                except Exception as ex:
                    result = f"Error executing {tool_name}: {str(ex)}"

            if tool_name not in tools_used:
                tools_used.append(tool_name)
            tool_results.append(str(result))

            # Append tool response message to OpenAI history
            messages.append({
                "role": "tool",
                "tool_call_id": tc.id,
                "name": tool_name,
                "content": str(result)
            })

        # Log execution finished
        if tools_used:
            tools_str = ", ".join(tools_used)
            results_str = "\nResults:\n- " + "\n- ".join(tool_results)
            msg_end = f"⚙️ Executed tools: {tools_str}{results_str}"
            insert_feedback(cursor, table, session_id, message_in_id, msg_end)
            if on_complete and show_tools_results:
                try:
                    on_complete(msg_end)
                except Exception:
                    pass

        iteration += 1
        if iteration == max_iterations:
            messages.append({"role": "user", "content": f"{agent_name} continue"})
            max_iterations += int(get_config("AUTONOMOUS_MODE", "10"))
            
            if iteration > 100:  # Hard safety limit
                return "Error: Tool execution loop exceeded absolute maximum limit."

    return "Error: Tool execution loop exceeded maximum iterations."
