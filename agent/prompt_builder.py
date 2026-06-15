"""
System prompt construction and config_kwargs assembly.
Extracts the duplicated prompt-building logic from process_message and process_ide_message.
"""
import logging

import standard_prompts
from database import get_config, get_ide_config
from google.genai import types
from tools import get_permitted_tools
from utils.message_utils import process_tools_for_llm


logger = logging.getLogger(__name__)

# The JSON schema prompt appended to all system prompts
JSON_SCHEMA_PROMPT = """
You MUST output your final response as a valid JSON object matching exactly this schema:
{
  "user_prompt": "<the user's original request>",
  "llm_response": "<your complete response addressing the request>",
  "is_the_user_request_completely_satisfied": <boolean>,
  "critical_system_failure": <boolean>
}
Note: Set "critical_system_failure" to true ONLY if you encounter an unrecoverable system exception or fatal tool error that prevents you from satisfying the request.
Do not include any markdown formatting like ```json, just the raw JSON object.
"""


def _fetch_user_memory(cursor) -> str:
    """
    Fetches user memory instructions from the database.

    Returns:
        str: Formatted memory block, or empty string if none found.
    """
    try:
        cursor.execute('SELECT id, instruction FROM user_memory')
        memories = cursor.fetchall()
        if memories:
            return "User Memory / Persistent Instructions:\n" + "\n".join(
                f"[ID: {r['id']}] {r['instruction']}" for r in memories
            )
    except Exception as e:
        logger.error(f"Error fetching user memory: {e}")
    return ""


def _inject_project_path(system_prompt: str) -> str:
    """
    Prepends workspace directory instructions if a project path is configured.
    """
    project_path = get_ide_config('CURRENT_PROJECT_PATH')
    if project_path:
        return (
            f"IMPORTANT: You are currently operating in the workspace directory: {project_path}\n"
            f"You MUST use this absolute path as the base directory for all file operations "
            f"(reading, writing, searching) unless the user specifies otherwise.\n\n"
            f"{system_prompt}"
        )
    return system_prompt


def _inject_channel_rules(system_prompt: str, channel_id: str, include_tool_rules: bool) -> str:
    """
    Prepends channel-specific instructions (WhatsApp, web-chat) to the system prompt.
    """
    if not channel_id:
        return system_prompt

    if channel_id.startswith('whatsapp:') or channel_id.startswith('wa_web:'):
        clean_channel = channel_id.replace('wa_web:', '').replace('whatsapp:', '')
        if include_tool_rules:
            return (
                f"This message comes from WhatsApp (Channel ID: {clean_channel}). To reply to the current conversation, "
                f"simply output your text directly. Do NOT use the send_whatsapp_message tool "
                f"for standard replies. The system will automatically forward your text to the chat. "
                f"However, if you need to send an image or file (like a screenshot) to the current conversation, you MUST use "
                f"the send_whatsapp_file tool (with phone_number='{clean_channel}'). If you need to send it to another chat or group, use their respective phone_number.\n\n{system_prompt}"
            )
        else:
            return (
                f"This message comes from WhatsApp (Channel ID: {clean_channel}). To reply to the current conversation, "
                f"simply output your text directly. The system will automatically forward "
                f"your text to the chat.\n\n{system_prompt}"
            )
    elif channel_id.startswith('web-chat'):
        return f"This message comes from the web chat (HTML). You must reply via the web chat.\n\n{system_prompt}"

    return system_prompt


def build_system_prompt(
    cursor,
    worker=None,
    channel_id: str = None,
    include_tool_rules: bool = True,
    has_image: bool = False,
    worker_name: str = None,
    ide_prompt: str = None,
) -> str:
    """
    Builds the complete system prompt with all rules, memory, and JSON schema.

    Arguments:
        cursor: Database cursor for fetching user memory.
        worker (dict, optional): Worker config dict (for process_message path).
        channel_id (str, optional): Channel ID for channel-specific rules.
        include_tool_rules (bool): Whether to include tool usage rules.
        has_image (bool): Whether the current message has an image/document.
        worker_name (str, optional): Name of the worker for standard rules.
        ide_prompt (str, optional): IDE-specific prompt (for process_ide_message path).

    Returns:
        str: The fully assembled system prompt.
    """
    # 1. Base prompt
    if ide_prompt is not None:
        system_prompt = ide_prompt
    elif worker and worker.get('worker_instructions'):
        system_prompt = worker['worker_instructions']
    else:
        system_prompt = ""

    # 2. Channel-specific rules
    system_prompt = _inject_channel_rules(system_prompt, channel_id, include_tool_rules)

    # 3. Project path
    system_prompt = _inject_project_path(system_prompt)

    # 4. Standard rules
    system_prompt = standard_prompts.apply_standard_rules(
        system_prompt, worker_name=worker_name, include_tool_rules=include_tool_rules
    )

    # 5. Image/document rules
    if has_image:
        system_prompt = standard_prompts.apply_image_document_rules(system_prompt)

    # 6. JSON schema prompt
    if system_prompt:
        system_prompt = f"{system_prompt}\n\n{JSON_SCHEMA_PROMPT}"
    else:
        system_prompt = JSON_SCHEMA_PROMPT

    # 7. User memory
    memory_block = _fetch_user_memory(cursor)
    if memory_block:
        if system_prompt:
            system_prompt = f"{system_prompt}\n\n{memory_block}"
        else:
            system_prompt = memory_block

    return system_prompt


def build_config_kwargs(
    system_prompt: str,
    tools=None,
    thinking_enabled: bool = False,
    show_tools_results: bool = True,
) -> dict:
    """
    Builds the config_kwargs dict for LLM calls.

    Arguments:
        system_prompt (str): The assembled system prompt.
        tools (list, optional): List of tool functions to provide.
        thinking_enabled (bool): Whether to enable thinking mode.
        show_tools_results (bool): Whether to stream tool execution results to the client.

    Returns:
        dict: Configuration kwargs for the LLM call.
    """
    config_kwargs = {
        "temperature": 0.0,
        "show_tools_results": show_tools_results,
    }

    if tools:
        config_kwargs["tools"] = process_tools_for_llm(tools)

    if system_prompt:
        config_kwargs["system_instruction"] = system_prompt

    if thinking_enabled:
        config_kwargs["thinking_config"] = types.ThinkingConfig(thinking_budget=8000)

    return config_kwargs
