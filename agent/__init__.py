"""
Agent package — modularized LLM agent pipeline.

Public API:
    - process_message: Entry point for WhatsApp/chat messages
    - process_ide_message: Entry point for IDE messages
    - route_llm_call: Routes to the correct LLM provider
    - invoke_llm_with_fallback: Tries multiple models with fallback
    - call_gemini_llm, call_qwen_llm, call_groq_llm, call_openai_llm, call_ollama_llm, call_nvidia_llm: Provider-specific calls
    - convert_to_openai_tool: Converts Python functions to OpenAI tool schemas
    - execute_openai_compatible_llm: Shared execution loop for OpenAI-compatible providers
    - execute_autonomous_loop: Auto-reflection loop
"""

from agent.message_processor import process_message, process_ide_message
from agent.llm_router import route_llm_call, invoke_llm_with_fallback
from agent.llm_providers import call_gemini_llm, call_qwen_llm, call_groq_llm, call_openai_llm, call_ollama_llm, call_nvidia_llm
from agent.openai_tools import convert_to_openai_tool, execute_openai_compatible_llm
from agent.autonomous_loop import execute_autonomous_loop

__all__ = [
    "process_message",
    "process_ide_message",
    "route_llm_call",
    "invoke_llm_with_fallback",
    "call_gemini_llm",
    "call_qwen_llm",
    "call_groq_llm",
    "call_openai_llm",
    "call_ollama_llm",
    "call_nvidia_llm",
    "convert_to_openai_tool",
    "execute_openai_compatible_llm",
    "execute_autonomous_loop",
]
