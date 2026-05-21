import os
import requests
import soundfile as sf
import tempfile
import uuid
import logging
import subprocess
from kokoro_onnx import Kokoro

logger = logging.getLogger(__name__)

MODELS_DIR = os.path.join(os.path.dirname(__file__), '..', '.store', 'models')
KOKORO_MODEL_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/kokoro-v1.0.onnx"
KOKORO_VOICES_URL = "https://github.com/thewh1teagle/kokoro-onnx/releases/download/model-files-v1.0/voices-v1.0.bin"

_kokoro_model = None

def download_file(url, dest):
    logger.info(f"Downloading {url} to {dest}...")
    response = requests.get(url, stream=True)
    response.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info(f"Downloaded {dest}.")

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
        
        # generate audio
        logger.info(f"Synthesizing audio for text: {text[:50]}...")
        samples, sample_rate = model.create(text, voice=voice, speed=1.0, lang="pt-br")
        
        # Save to temp wav
        temp_dir = os.path.join(os.path.dirname(__file__), '..', 'temp')
        if not os.path.exists(temp_dir):
            os.makedirs(temp_dir)
            
        temp_wav = os.path.join(temp_dir, f"{uuid.uuid4().hex}.wav")
        sf.write(temp_wav, samples, sample_rate)
        
        # Convert to ogg for WhatsApp using ffmpeg
        temp_ogg = os.path.join(temp_dir, f"audio_{uuid.uuid4().hex}.ogg")
        subprocess.run([
            "ffmpeg", "-y", "-i", temp_wav,
            "-c:a", "libopus", "-strict", "-2", temp_ogg
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
