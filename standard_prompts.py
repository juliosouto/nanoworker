def apply_standard_rules(system_prompt: str) -> str:
    """
    Appends standard rules to the beginning of the system prompt.
    Currently, the rules are empty as requested, but can be updated here.
    """
    standard_rules = """
    1. You are a helpful assistant.
    2. If the user asks you to send an audio or voice message, wrap ONLY the text you want to be spoken inside <audio></audio> tags. The backend system will automatically intercept this tag, generate the audio using Kokoro TTS, and send it as a voice note. For example: <audio>Hi, here is your audio!</audio>.
    3. Other rules may be defined below. If so, just follow them.
    4. Every time the user asks for information of a url, you should use the `extract_webpage_text` tool to read the content of the page before answering.

    """
    
    if standard_rules:
        if system_prompt:
            return f"{standard_rules}\n\n{system_prompt}"
        return standard_rules
        
    return system_prompt
