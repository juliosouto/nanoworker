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
_xtts_synthesizer = None

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
            if not audio_path:
                logger.error("generate_audio returned empty path")
                return text_without_audio, None
            return text_without_audio, audio_path
            
    except Exception as e:
        logger.exception(f"Failed to extract and generate audio: {e}")
        
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


def _find_xtts_finetuned_checkpoint():
    """
    Looks for fine-tuned checkpoints in .store/models/finetuned or models/finetuned.
    """
    candidate_dirs = [
        os.path.join(MODELS_DIR, "finetuned"),
        os.path.join(os.path.dirname(__file__), '..', 'models', 'finetuned'),
    ]
    for finetuned_root in candidate_dirs:
        if not os.path.exists(finetuned_root):
            continue
        subdirs = [os.path.join(finetuned_root, d) for d in os.listdir(finetuned_root) if os.path.isdir(os.path.join(finetuned_root, d))]
        subdirs.append(finetuned_root)
        for sdir in sorted(subdirs, key=lambda p: os.path.getmtime(p), reverse=True):
            files = os.listdir(sdir)
            ckpts = [os.path.join(sdir, f) for f in files if f.startswith("checkpoint_") and f.endswith(".pth") or f == "model.pth"]
            cfg = os.path.join(sdir, "config.json")
            if ckpts and os.path.exists(cfg):
                ckpts.sort(key=lambda p: os.path.getmtime(p), reverse=True)
                return ckpts[0], cfg
    return None, None


def get_xtts_synthesizer():
    """
    Loads Coqui XTTS-v2 for inference (supporting base and fine-tuned checkpoints).
    """
    global _xtts_synthesizer
    if _xtts_synthesizer is not None:
        return _xtts_synthesizer

    os.environ["COQUI_TOS_AGREED"] = "1"
    import torch
    import torchaudio

    # Compatibilidade com PyTorch 2.6+
    _orig_torch_load = torch.load
    def _safe_torch_load(*args, **kwargs):
        kwargs["weights_only"] = False
        return _orig_torch_load(*args, **kwargs)
    torch.load = _safe_torch_load

    # Fallback seguro para torchaudio.load via soundfile
    def _safe_torchaudio_load(filepath, *args, **kwargs):
        data, sr = sf.read(str(filepath))
        tensor = torch.from_numpy(data).float()
        if tensor.ndim == 1:
            tensor = tensor.unsqueeze(0)
        else:
            tensor = tensor.t()
        return tensor, sr
    torchaudio.load = _safe_torchaudio_load

    from TTS.tts.models.xtts import Xtts
    from TTS.tts.configs.xtts_config import XttsConfig
    from TTS.utils.manage import ModelManager

    device = "cuda" if torch.cuda.is_available() else ("mps" if torch.backends.mps.is_available() else "cpu")
    logger.info(f"Initializing Coqui XTTS-v2 on {device}...")

    manager = ModelManager()
    base_model_path, _, _ = manager.download_model("tts_models/multilingual/multi-dataset/xtts_v2")

    finetuned_checkpoint, finetuned_config = _find_xtts_finetuned_checkpoint()

    if finetuned_checkpoint and finetuned_config:
        logger.info(f"✨ Loading fine-tuned XTTS-v2 checkpoint: {finetuned_checkpoint}")
        config_xtts = XttsConfig()
        config_xtts.load_json(finetuned_config)
        model = Xtts.init_from_config(config_xtts)
        model.load_checkpoint(
            config_xtts,
            checkpoint_dir=base_model_path,
            checkpoint_path=finetuned_checkpoint,
            vocab_path=os.path.join(base_model_path, "vocab.json"),
            speaker_file_path=os.path.join(base_model_path, "speakers_xtts.pth"),
            eval=True,
            use_deepspeed=False
        )
        model.to(device)
        _xtts_synthesizer = {"type": "finetuned", "model": model, "device": device, "base_dir": base_model_path}
    else:
        logger.info("Loading base Coqui XTTS-v2 model...")
        from TTS.api import TTS
        tts = TTS("tts_models/multilingual/multi-dataset/xtts_v2").to(device)
        _xtts_synthesizer = {"type": "base", "tts": tts, "device": device, "base_dir": base_model_path}

    return _xtts_synthesizer


def _generate_audio_kokoro(text: str, voice: str = "af_heart") -> str:
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
        'pt-br': 'pm_alex',
        'en-us': 'am_echo',
        'es': 'ef_dora',
        'fr-fr': 'ff_siwis',
        'ja': 'jf_alpha',
        'ko': 'kf_alpha',
        'cmn': 'zf_xiaoxiao',
        'it': 'if_sara',
        'hi': 'hf_alpha'
    }
    
    # Only override the voice if it is the default "af_heart"
    if voice == "af_heart" and kokoro_lang in default_voices:
        voice = default_voices[kokoro_lang]
    
    logger.info(f"Synthesizing Kokoro audio: {text[:50]}... (Lang: {kokoro_lang}, Voice: {voice})")
    samples, sample_rate = model.create(text, voice=voice, speed=1.0, lang=kokoro_lang)
    
    temp_wav = get_temp_file_path(".wav")
    sf.write(temp_wav, samples, sample_rate)
    return temp_wav


def _get_speaker_wav_references() -> list[str]:
    """Finds speaker reference wavs for voice cloning."""
    candidate_paths = [
        os.path.join(MODELS_DIR, 'voices'),
        os.path.join(os.path.dirname(__file__), '..', 'models', 'voices'),
        os.path.join(MODELS_DIR, 'finetuned'),
        os.path.join(os.path.dirname(__file__), '..', 'models', 'finetuned'),
    ]
    ref_wavs = []
    for cdir in candidate_paths:
        if os.path.exists(cdir):
            for root, _, files in os.walk(cdir):
                for f in files:
                    if f.lower().endswith(('.wav', '.mp3', '.ogg', '.flac')) and not f.startswith('.'):
                        ref_wavs.append(os.path.join(root, f))
    return ref_wavs[:3]


_cached_latents = None

def _get_or_create_cached_latents(model, speaker_wavs):
    """Caches speaker latents in memory/disk to accelerate inference."""
    global _cached_latents
    if _cached_latents is not None:
        return _cached_latents

    candidate_cache_paths = [
        os.path.join(MODELS_DIR, "speaker_latents.pth"),
        os.path.join(os.path.dirname(__file__), '..', 'models', 'speaker_latents.pth'),
        os.path.join(os.path.dirname(__file__), '..', 'models', 'finetuned', 'speaker_latents.pth'),
        os.path.join(MODELS_DIR, "finetuned", "speaker_latents.pth"),
    ]
    for cache_path in candidate_cache_paths:
        if os.path.exists(cache_path):
            import torch
            try:
                cached = torch.load(cache_path, weights_only=False)
                device = next(model.parameters()).device
                _cached_latents = (cached["gpt_cond_latent"].to(device), cached["speaker_embedding"].to(device))
                logger.info(f"Loaded cached speaker latents from {cache_path}")
                return _cached_latents
            except Exception as e:
                logger.warning(f"Could not load cached latents from {cache_path}: {e}")

    if speaker_wavs:
        import torch
        gpt_cond_latent, speaker_embedding = model.get_conditioning_latents(
            audio_path=speaker_wavs,
            gpt_cond_len=6,
            max_ref_length=30
        )
        try:
            torch.save({
                "gpt_cond_latent": gpt_cond_latent.cpu(),
                "speaker_embedding": speaker_embedding.cpu()
            }, cache_path)
        except Exception:
            pass
        _cached_latents = (gpt_cond_latent, speaker_embedding)
        return _cached_latents

    return None, None


def _generate_audio_xtts(text: str) -> str:
    synth_obj = get_xtts_synthesizer()
    
    try:
        detected_lang = detect(text)
    except LangDetectException:
        detected_lang = "pt"
        
    supported_langs = {'en', 'es', 'fr', 'de', 'it', 'pt', 'pl', 'tr', 'ru', 'nl', 'cs', 'ar', 'zh-cn', 'ja', 'ko', 'hu', 'hi'}
    xtts_lang = detected_lang if detected_lang in supported_langs else 'pt'
    
    temp_wav = get_temp_file_path(".wav")
    speaker_wavs = _get_speaker_wav_references()

    logger.info(f"Synthesizing XTTS-v2 audio: {text[:50]}... (Lang: {xtts_lang}, Finetuned: {synth_obj.get('type') == 'finetuned'})")
    
    if synth_obj.get("type") == "finetuned":
        model = synth_obj["model"]
        gpt_cond_latent, speaker_embedding = _get_or_create_cached_latents(model, speaker_wavs)
        if gpt_cond_latent is not None and speaker_embedding is not None:
            out = model.inference(
                text=text,
                language=xtts_lang,
                gpt_cond_latent=gpt_cond_latent,
                speaker_embedding=speaker_embedding,
                temperature=0.7,
                length_penalty=1.0,
                repetition_penalty=2.0,
                top_k=50,
                top_p=0.85,
                enable_text_splitting=True
            )
        else:
            out = model.inference(
                text=text,
                language=xtts_lang,
                temperature=0.7,
                enable_text_splitting=True
            )
        sf.write(temp_wav, out["wav"], 24000, subtype='PCM_16')
    else:
        tts = synth_obj["tts"]
        if speaker_wavs:
            tts.tts_to_file(text=text, speaker_wav=speaker_wavs[0], language=xtts_lang, file_path=temp_wav, split_sentences=True)
        elif hasattr(tts, 'speakers') and tts.speakers:
            speaker_name = tts.speakers[0]
            tts.tts_to_file(text=text, speaker=speaker_name, language=xtts_lang, file_path=temp_wav, split_sentences=True)
        else:
            tts.tts_to_file(text=text, language=xtts_lang, file_path=temp_wav, split_sentences=True)
        
    return temp_wav


def generate_audio(text: str, voice: str = "af_heart") -> str:
    """
    Generates audio from text using the configured TTS model (Kokoro ONNX or Coqui XTTS-v2)
    and returns the path to the .ogg file.
    """
    try:
        from database import get_config
        tts_engine = get_config("TTS_MODEL", "kokoro").lower()
    except Exception:
        tts_engine = "kokoro"

    try:
        if tts_engine in ("xtts", "xtts-v2", "coqui-xtts-v2", "coqui"):
            temp_wav = _generate_audio_xtts(text)
        else:
            temp_wav = _generate_audio_kokoro(text, voice=voice)
            
        # Convert to ogg for WhatsApp using ffmpeg
        temp_ogg = get_temp_file_path("audio.ogg")
        subprocess.run([
            "ffmpeg", "-y", "-i", temp_wav,
            "-c:a", "libopus", "-b:a", "64k", "-strict", "-2", temp_ogg
        ], check=True, stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
        
        # Clean up wav
        try:
            os.remove(temp_wav)
        except Exception:
            pass
            
        return os.path.abspath(temp_ogg)
    except Exception as e:
        logger.exception(f"Error generating audio: {e}")
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

def _decode_audio_with_ffmpeg(file_path):
    """
    Fallback decoder used when faster-whisper's native PyAV decode fails
    (e.g. old/incompatible `av` versions raising "TypeError: open() got an
    unexpected keyword argument 'metadata_errors'").

    Converts the input to 16 kHz mono WAV with the system ffmpeg binary
    (installed in the Docker image) and loads it as float32 numpy samples,
    which model.transcribe() accepts directly — bypassing PyAV entirely.

    Returns a float32 numpy array, or None when ffmpeg is unavailable or the
    conversion fails.
    """
    try:
        import numpy as np

        wav_path = get_temp_file_path("whisper_fallback.wav")
        proc = subprocess.run(
            ["ffmpeg", "-y", "-i", file_path, "-ac", "1", "-ar", "16000", wav_path],
            stdout=subprocess.DEVNULL,
            stderr=subprocess.DEVNULL,
            timeout=120,
        )
        if proc.returncode != 0 or not os.path.exists(wav_path):
            logger.warning(f"ffmpeg fallback decode failed (exit {proc.returncode})")
            return None
        audio, _sample_rate = sf.read(wav_path, dtype="float32", always_2d=True)
        try:
            os.unlink(wav_path)
        except OSError:
            pass
        return audio.mean(axis=1).astype(np.float32)
    except FileNotFoundError:
        logger.warning("ffmpeg binary not found; fallback decode unavailable")
        return None
    except Exception as e:
        logger.warning(f"ffmpeg fallback decode failed: {e}")
        return None


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

        try:
            segments, info = model.transcribe(file_path, beam_size=5, initial_prompt=prompt)
        except Exception as decode_err:
            # Old/incompatible PyAV versions fail inside faster-whisper's
            # decode_audio ("TypeError: open() got an unexpected keyword
            # argument 'metadata_errors'"). Retry with a system-ffmpeg decoded
            # numpy array, which bypasses PyAV completely.
            logger.warning(f"faster-whisper native decode failed ({decode_err}); trying ffmpeg fallback")
            audio_array = _decode_audio_with_ffmpeg(file_path)
            if audio_array is None:
                raise
            segments, info = model.transcribe(audio_array, beam_size=5, initial_prompt=prompt)
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


def transcribe_webhook_audio(content, audio_base64, mimetype=''):
    """
    Transcribe audio from a webhook payload and append the result to the message content.

    Args:
        content: The original message text.
        audio_base64: Base64-encoded audio data.
        mimetype: Optional MIME type of the audio.

    Returns:
        str: The content with the transcription appended.
    """
    try:
        transcription = process_base64_audio_to_text(audio_base64, mimetype)
        return f"{content}\n[Transcription]: {transcription}"
    except Exception as e:
        logger.error(f"Failed to process webhook audio: {e}")
        return f"{content}\n[Internal error processing audio]"

