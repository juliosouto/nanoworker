import datetime

def apply_standard_rules(system_prompt: str, worker_name: str = None) -> str:
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
    7. I am sending a list of tools you can use.
    8. Check if there is a tool that can solve the user's request. If not, inform the user about it.
    """

    #print('**********************************************', flush=True)
    #print(standard_rules, flush=True)
    #print('**********************************************', flush=True)
    
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
