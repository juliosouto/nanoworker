import base64
import logging
import os
import re
import subprocess
import tempfile
import uuid

import requests
import soundfile as sf
from kokoro_onnx import Kokoro
from langdetect import detect
from langdetect.lang_detect_exception import LangDetectException

from utils.file_utils import download_file, get_temp_file_path

logger = logging.getLogger(__name__)

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

_whisper_model = None
_kokoro_model = None

MODELS_DIR = os.path.join(os.path.dirname(__file__), '..', '.store', 'models')
KOKORO_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
KOKORO_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

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



def get_kokoro_model():
    global _kokoro_model
    if _kokoro_model is not None:
        return _kokoro_model

    if not os.path.exists(MODELS_DIR):
        os.makedirs(MODELS_DIR)

    model_path = os.path.join(MODELS_DIR, 'kokoro-v1.0.onnx')
    voices_path = os.path.join(MODELS_DIR, 'voices-v1.0.bin')

    if not os.path.exists(model_path):
        download_file(KOKORO_MODEL_URL, model_path)
    if not os.path.exists(voices_path):
        download_file(KOKORO_VOICES_URL, voices_path)

    logger.info("Loading Kokoro model...")
    _kokoro_model = Kokoro(model_path, voices_path)
    return _kokoro_model

def generate_audio(text: str, voice: str = "af_heart") -> str:
    """
    Generates audio from text using Kokoro-ONNX and returns the path to the .ogg file.
    """
    try:
        model = get_kokoro_model()
        
        # Detect language dynamically
        try:
            detected_lang = detect(text)
        except LangDetectException:
            detected_lang = "pt"
            
        # Map detected language to Kokoro format. en -> en-us, pt -> pt-br
        lang_mapping = {
            'pt': 'pt-br',
            'en': 'en-us',
            'es': 'es',
            'fr': 'fr-fr',
            'ja': 'ja',
            'ko': 'ko',
            'zh-cn': 'cmn',
            'zh-tw': 'cmn',
            'it': 'it',
            'hi': 'hi'
        }
        
        kokoro_lang = lang_mapping.get(detected_lang, 'en-us')
        
        # Map languages to best default voices
        default_voices = {
            'pt-br': 'pm_alex',  # Mantido a sua escolha (Português Masculino)
            'en-us': 'am_echo',  # Corrigido para voz masculina em inglês
            'es': 'ef_dora',
            'fr-fr': 'ff_siwis',
            'ja': 'jf_alpha',
            'ko': 'kf_alpha',
            'cmn': 'zf_xiaoxiao',
            'it': 'if_sara',     # Italiano
            'hi': 'hf_alpha'     # Hindi
        }
        
        # Only override the voice if it is the default "af_heart"
        if voice == "af_heart" and kokoro_lang in default_voices:
            voice = default_voices[kokoro_lang]
        
        # generate audio
        logger.info(f"Synthesizing audio for text: {text[:50]}... (Detected Lang: {detected_lang}, Using Lang: {kokoro_lang}, Voice: {voice})")
        samples, sample_rate = model.create(text, voice=voice, speed=1.0, lang=kokoro_lang)
        
        # Save to temp wav
        temp_wav = get_temp_file_path(".wav")
        sf.write(temp_wav, samples, sample_rate)
        
        # Convert to ogg for WhatsApp using ffmpeg
        temp_ogg = get_temp_file_path("audio.ogg")
        subprocess.run([
            "ffmpeg", "-y", "-i", temp_wav,
            "-c:a", "libopus", "-b:a", "64k", "-strict", "-2", temp_ogg
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Clean up wav
        try:
            os.remove(temp_wav)
        except:
            pass
            
        return os.path.abspath(temp_ogg)
    except Exception as e:
        logger.error(f"Error generating audio: {e}")
        return ""

def get_whisper_model():
    global _whisper_model, _current_whisper_model_name
    if WhisperModel is not None:
        from database import get_config
        model_name = get_config("WHISPER_MODEL", "small")
        if not model_name:
            model_name = "small"
        if _whisper_model is None or _current_whisper_model_name != model_name:
            logger.info(f"Loading faster-whisper model ({model_name})...")
            _whisper_model = WhisperModel(model_name, device="cpu", compute_type="int8")
            _current_whisper_model_name = model_name
    return _whisper_model

def transcribe_audio(file_path):
    """Transcribe audio file using faster-whisper."""
    model = get_whisper_model()
    if not model:
        return "[Audio message received - Transcription unavailable: faster-whisper not installed]"
        
    try:
        try:
            from database import get_db, get_config
            agent_name = get_config('agent_name', '')
            
            hotwords = []
            if agent_name:
                hotwords.extend([agent_name, f"@{agent_name}"])
                
            conn = get_db()
            cursor = conn.cursor()
            cursor.execute('SELECT worker_name FROM workers_config')
            worker_names = [row['worker_name'].strip() for row in cursor.fetchall() if row['worker_name']]
            conn.close()
            
            for name in worker_names:
                hotwords.extend([name, f"@{name}", name.replace(" ", ""), f"@{name.replace(' ', '')}"])
                
            prompt = ", ".join(hotwords) if hotwords else None
        except Exception:
            prompt = None

        segments, info = model.transcribe(file_path, beam_size=5, initial_prompt=prompt)
        text = " ".join([segment.text for segment in segments]).strip()
        return f"{text}" if text else "[Audio received, but no text detected]"
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return f"[Audio transcription error: {e}]"

def process_base64_audio_to_text(audio_base64: str, mimetype: str = '') -> str:
    """Decodes a base64 audio string, saves it to a temp file, and returns the transcription."""
    try:
        audio_data = base64.b64decode(audio_base64)
        ext = ".ogg"
        if mimetype.startswith('audio/mp4'):
            ext = ".m4a"
        
        with tempfile.NamedTemporaryFile(delete=False, suffix=ext) as tf:
            tf.write(audio_data)
            temp_path = tf.name
            
        try:
            transcription = transcribe_audio(temp_path)
            return transcription
        finally:
            try:
                os.unlink(temp_path)
            except:
                pass
    except Exception as e:
        logger.error(f"Failed to process base64 audio: {e}")
        raise
