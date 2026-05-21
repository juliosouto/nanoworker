import logging
import os

logger = logging.getLogger(__name__)

try:
    from faster_whisper import WhisperModel
except ImportError:
    WhisperModel = None

_whisper_model = None

def get_whisper_model():
    global _whisper_model
    if _whisper_model is None and WhisperModel is not None:
        logger.info("Loading faster-whisper model...")
        # device="cpu" is usually safe for general environments, though it could be configurable
        _whisper_model = WhisperModel("tiny", device="cpu", compute_type="int8")
    return _whisper_model

def transcribe_audio(file_path):
    """Transcribe audio file using faster-whisper."""
    model = get_whisper_model()
    if not model:
        return "[Audio message received - Transcription unavailable: faster-whisper not installed]"
        
    try:
        segments, info = model.transcribe(file_path, beam_size=5)
        text = " ".join([segment.text for segment in segments]).strip()
        return f"{text}" if text else "[Áudio recebido, mas nenhum texto detectado]"
    except Exception as e:
        logger.error(f"Transcription failed: {e}")
        return f"[Erro na transcrição de áudio: {e}]"
