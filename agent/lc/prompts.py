"""Modular system-prompt construction (Fase 1).

Composes the same blocks as agent.prompt_builder.build_system_prompt, but:
- the static rules come from a compact ChatPromptTemplate (~40-50% shorter
  than standard_prompts.apply_standard_rules, with the useless "big list"
  rule removed and rules 5/6 merged);
- the prose JSON-schema block (JSON_SCHEMA_PROMPT[_WITH_PLAN]) is OMITTED
  when the provider will enforce the contract natively via structured output
  (native_structured=True) — the contract lives in agent.lc.outputs.AgentResponse.
"""
import datetime
import logging

from langchain_core.prompts import ChatPromptTemplate

import standard_prompts

logger = logging.getLogger(__name__)

# Compact rewrite of standard_prompts.apply_standard_rules. Variables are
# filled per call by ChatPromptTemplate.
COMPACT_RULES_TEMPLATE = """\
1. Your name is {worker_name}; you are a helpful assistant.
2. Current datetime: {datetime}. User location: {location}.
3. The final answer to the end user must be one paragraph, 50-150 chars, unless another length is explicitly requested (detailed data answers may go up to 10000 chars).
4. For audio/voice replies, wrap ONLY the spoken text in <audio></audio> tags; the backend auto-generates a Kokoro TTS voice note.
5. Always be precise and fulfill the user's request completely.
6. For facts, current events or verifiable data, you MUST invoke search_web before answering.
7. Files are stored in /app/files/ with subfolders: documents/, downloads/, images/, music/, temp/, videos/.
"""
COMPACT_RULES_WITH_TOOLS = """\
8. You are sending a list of tools you can use; always use a tool to fulfill the user's request.\
"""

_compact_rules_prompt = ChatPromptTemplate.from_template(COMPACT_RULES_TEMPLATE)


def compact_standard_rules(worker_name=None, include_tool_rules=True) -> str:
    """Renders the compact static rules via the LangChain template."""
    try:
        location = standard_prompts._get_user_location()
    except Exception:
        location = "Unknown"
    messages = _compact_rules_prompt.format_messages(
        worker_name=worker_name or "Assistant",
        datetime=datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S"),
        location=location,
    )
    rendered = messages[0].content if messages else ""
    if include_tool_rules:
        rendered += "\n" + COMPACT_RULES_WITH_TOOLS
    return rendered


def build_system_prompt(
    cursor,
    worker=None,
    channel_id=None,
    include_tool_rules=True,
    has_image=False,
    worker_name=None,
    ide_prompt=None,
    native_structured=False,
    models_to_try=None,
    message_query: str = "",
) -> str:
    """Builds the complete system prompt (same signature/semantics as
    agent.prompt_builder.build_system_prompt, plus native_structured).

    When native_structured=True the prose JSON-schema block is omitted: the
    API itself enforces the AgentResponse contract (see agent.lc.outputs).
    """
    from agent.prompt_builder import (
        JSON_SCHEMA_PROMPT,
        JSON_SCHEMA_PROMPT_WITH_PLAN,
        _inject_channel_rules,
        _inject_project_path,
        get_config,  # same symbol the legacy path uses (patchable in tests)
    )
    from agent.lc import memory_rag

    # 1. Base prompt
    if ide_prompt is not None:
        system_prompt = ide_prompt
    elif worker and worker.get("worker_instructions"):
        system_prompt = worker["worker_instructions"]
    else:
        system_prompt = ""

    # 2. Channel-specific rules
    system_prompt = _inject_channel_rules(system_prompt, channel_id, include_tool_rules)

    # 3. Project path
    system_prompt = _inject_project_path(system_prompt)

    # 4. Standard rules (compact, LangChain template) — prepended like legacy.
    rules = compact_standard_rules(worker_name=worker_name, include_tool_rules=include_tool_rules)
    if system_prompt:
        system_prompt = f"{rules}\n{system_prompt}"
    else:
        system_prompt = rules

    # 5. Image/document rules
    if has_image:
        system_prompt = standard_prompts.apply_image_document_rules(system_prompt)

    # 6. JSON schema prompt — only when structured output is NOT native.
    if not native_structured:
        schema_enabled = get_config("PLAN_BEFORE_EXECUTION", "false").lower() == "true"
        schema_prompt = JSON_SCHEMA_PROMPT_WITH_PLAN if schema_enabled else JSON_SCHEMA_PROMPT
        if system_prompt:
            system_prompt = f"{system_prompt}\n\n{schema_prompt}"
        else:
            system_prompt = schema_prompt

    # 7. User memory (Fase 2: semantic top-k via RAG; falls back to legacy injection).
    memory_block = memory_rag.get_memory_block(cursor, query=message_query)
    if memory_block:
        if system_prompt:
            system_prompt = f"{system_prompt}\n\n{memory_block}"
        else:
            system_prompt = memory_block

    return system_prompt