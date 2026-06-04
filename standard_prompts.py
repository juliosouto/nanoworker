import datetime

def apply_standard_rules(system_prompt: str, worker_name: str = None, include_tool_rules: bool = True) -> str:
    """
    Appends standard rules to the beginning of the system prompt.
    Currently, the rules are empty as requested, but can be updated here.
    """
    
    standard_rules = f"""
    1. Your name is {worker_name}.
    2. You are a helpful assistant.
    3. Current Datetime: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}
    4. The final answer to the end user must have up to one paragraph, between 50 and 150 characters, unless other number is explicitly requested.
    5. If the user requested detailed information or data, your response could have up to 10000 characters.
    6. If the user asks you to send an audio or voice message, wrap ONLY the text you want to be spoken inside <audio></audio> tags. The backend system will automatically intercept this tag, generate the audio using Kokoro TTS, and send it as a voice note. For example: <audio>Hi, here is your audio!</audio>.
    """

    if include_tool_rules:
        standard_rules += """
    7. I am sending a list of tools you can use. It's a big list.
    8. Always use a tool to fulfill the user's request.
    9. Always make sure your answer is precise and fulfills completely the user's request.
    10. Whenever a query involves facts, current events, or verifiable data, you are strictly prohibited from answering based solely on your internal training. You must obligatorily invoke the search tool before generating any response.
    11. Do not rely on your internal knowledge for factual data. If the information is not present in the tool output, state that you do not have updated information after performing the search.
    """
    
    standard_rules += "\n    "

    if standard_rules:
        if system_prompt:
            return f"{standard_rules}\n{system_prompt}"
        return standard_rules
    return system_prompt


def apply_image_document_rules(system_prompt: str) -> str:
    """
    Appends specific rules to the system prompt when an image or document is present in the user's prompt.
    """
    media_rules = r"If it's a document containing data, extract and structure literally 100% of the data."
    if system_prompt:
        return f"{system_prompt}\n\n{media_rules}"
    return media_rules
