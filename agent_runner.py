"""
Backward-compatibility shim.
All logic has been moved to the `agent` package.

This module re-exports all public symbols so that existing imports like:
    from agent_runner import process_message
    import agent_runner; agent_runner.route_llm_call(...)
continue to work without modification.
"""
from agent import (
    process_message,
    process_ide_message,
    route_llm_call,
    invoke_llm_with_fallback,
    call_gemini_llm,
    call_qwen_llm,
    call_groq_llm,
    call_openai_llm,
    convert_to_openai_tool,
    execute_openai_compatible_llm,
    execute_autonomous_loop,
)
