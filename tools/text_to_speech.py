"""
Turns text into a spoken audio file with the TTS engine already used for
<audio> replies (Kokoro by default, quality set by TTS_MODEL).

Loaded on every OS (root tools/ directory). The result is an .ogg (opus)
file that WhatsApp plays as a voice note; send it with send_whatsapp_file.
"""

import logging
import os

logger = logging.getLogger(__name__)

_MAX_CHARS = 5000


def text_to_audio(text: str) -> str:
    """Converts text into a spoken audio file (.ogg voice note) using the local Kokoro TTS. The language is detected from the text. Use it when you need the audio as a file (to send with send_whatsapp_file, save or process); for a plain voice reply, the <audio></audio> tags are enough.

    Args:
        text (str): The text to be spoken (max 5000 characters).

    Returns:
        str: A success message with the ABSOLUTE path of the .ogg file, or an error message.
    """
    text = (text or "").strip()
    if not text:
        return "Error: text is empty."
    if len(text) > _MAX_CHARS:
        return f"Error: text is too long ({len(text)} characters, max {_MAX_CHARS})."

    try:
        from utils.audio_utils import generate_audio

        path = generate_audio(text)
    except Exception as e:
        logger.warning(f"Could not generate audio: {e}")
        return f"Error generating the audio: {e}"

    if not path or not os.path.isfile(path):
        return "Error: the TTS engine did not produce an audio file."
    return f"Audio generated successfully: {path}"
