import datetime

_cached_location = None

def _get_user_location():
    global _cached_location
    if _cached_location is None:
        try:
            import geocoder
            g = geocoder.ip('me')
            if g.ok:
                _cached_location = f"{g.city}, {g.state}, {g.country}"
            else:
                _cached_location = "Unknown"
        except Exception:
            _cached_location = "Unknown"
    return _cached_location


def apply_standard_rules(system_prompt: str, worker_name: str = None, include_tool_rules: bool = True) -> str:
    """
    Appends standard rules to the beginning of the system prompt.
    Currently, the rules are empty as requested, but can be updated here.
    """
    
    user_location = _get_user_location()
    
    standard_rules = f"""
    1. Your name is {worker_name}.
    2. You are a helpful assistant.
    3. Current Datetime: {datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")}.
    4. User Location: {user_location}.
    5. The final answer to the end user must have up to one paragraph, between 50 and 150 characters, unless other number is explicitly requested.
    6. If the user requested detailed information or data, your response can be up to 10000 characters.
    7. If the user asks you to send an audio or voice message, wrap ONLY the text you want to be spoken inside <audio></audio> tags. The backend system will automatically intercept this tag, generate the audio using Kokoro TTS, and send it as a voice note. For example: <audio>Hi, here is your audio!</audio>.
    8. Always make sure your answer is precise and fulfills completely the user's request.
    9. Whenever a query involves facts, current events, or verifiable data, you are strictly prohibited from answering based solely on your internal training. You must obligatorily invoke the search_web tool before generating any response.
    """

    if include_tool_rules:
        standard_rules += """
    10. I am sending a list of tools you can use. It's a big list.
    11. Always use a tool to fulfill the user's request.
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
