import re
from utils.tts import generate_audio
import logging

logger = logging.getLogger(__name__)

def extract_and_generate_audio(message: str) -> tuple[str, str | None]:
    """
    Extracts the <audio> tag from a message, generates the audio file,
    and returns the remaining text and the audio file path.
    
    Args:
        message: The text message, potentially containing an <audio> tag.
        
    Returns:
        A tuple containing:
        - text_without_audio: The text message with the <audio> tag removed.
        - audio_path: The absolute path to the generated audio file, or None if no tag was found.
    """
    try:
        match = re.search(r'<audio>(.*?)</audio>', message, re.DOTALL)
        if match:
            audio_text = match.group(1).strip()
            text_without_audio = message.replace(match.group(0), '').strip()
            
            audio_path = generate_audio(audio_text)
            return text_without_audio, audio_path
            
    except Exception as e:
        logger.error(f"Failed to extract and generate audio: {e}")
        
    return message.strip(), None
