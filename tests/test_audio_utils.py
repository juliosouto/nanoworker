import pytest
import os
import base64
import tempfile
from unittest.mock import patch, MagicMock

import utils.audio_utils as au
from utils.audio_utils import (
    extract_and_generate_audio,
    get_kokoro_model,
    generate_audio,
    get_whisper_model,
    transcribe_audio,
    process_base64_audio_to_text,
    transcribe_webhook_audio
)

@pytest.fixture(autouse=True)
def reset_globals():
    au._kokoro_model = None
    au._xtts_synthesizer = None
    au._whisper_model = None
    au.WhisperModel = MagicMock()
    yield
    au._kokoro_model = None
    au._xtts_synthesizer = None
    au._whisper_model = None

@pytest.fixture
def mock_db_config(mocker):
    mocker.patch('database.get_config', return_value="model_name")
    
    mock_db = MagicMock()
    mock_cursor = MagicMock()
    mock_db.cursor.return_value = mock_cursor
    mock_cursor.fetchall.return_value = [{'worker_name': 'test_worker'}]
    mocker.patch('database.get_db', return_value=mock_db)
    return mock_cursor

def test_extract_and_generate_audio_success(mocker):
    mocker.patch('utils.audio_utils.generate_audio', return_value="/fake/path.ogg")
    text_out, audio_path = extract_and_generate_audio("Hello <audio>voice me</audio> friend")
    assert text_out == "Hello  friend"
    assert audio_path == "/fake/path.ogg"

def test_extract_and_generate_audio_no_tag(mocker):
    text_out, audio_path = extract_and_generate_audio("Hello friend")
    assert text_out == "Hello friend"
    assert audio_path is None

def test_extract_and_generate_audio_error(mocker):
    mocker.patch('utils.audio_utils.generate_audio', side_effect=Exception("Fail"))
    text_out, audio_path = extract_and_generate_audio("Hello <audio>voice me</audio> friend")
    assert text_out == "Hello <audio>voice me</audio> friend"
    assert audio_path is None

def test_get_kokoro_model(mocker):
    mocker.patch('os.path.exists', side_effect=lambda path: True if path == au.MODELS_DIR else False)
    mock_dl = mocker.patch('utils.audio_utils.download_file')
    mock_kokoro = mocker.patch('utils.audio_utils.Kokoro', return_value="mock_kokoro")
    
    model = get_kokoro_model()
    assert model == "mock_kokoro"
    assert mock_dl.call_count == 2
    assert au._kokoro_model == "mock_kokoro"

def test_generate_audio_success(mocker):
    mocker.patch('database.get_config', return_value='kokoro')
    mocker.patch('utils.audio_utils.get_kokoro_model')
    mocker.patch('utils.audio_utils.detect', return_value="en")
    mocker.patch('utils.file_utils.get_temp_file_path', side_effect=["/tmp/test.wav", "/tmp/audio.ogg"])
    
    mock_model = MagicMock()
    mock_model.create.return_value = (b"samples", 24000)
    au._kokoro_model = mock_model
    
    mocker.patch('soundfile.write')
    mocker.patch('subprocess.run')
    mocker.patch('os.remove')
    
    path = generate_audio("Hello")
    assert type(path) is str

def test_generate_audio_xtts_success(mocker):
    mocker.patch('database.get_config', return_value='xtts-v2')
    mock_tts = MagicMock()
    mock_tts.speakers = ['Claribel Dervla']
    mocker.patch('utils.audio_utils.get_xtts_synthesizer', return_value={"type": "base", "tts": mock_tts})
    mocker.patch('utils.audio_utils.detect', return_value="pt")
    mocker.patch('utils.file_utils.get_temp_file_path', side_effect=["/tmp/test.wav", "/tmp/audio.ogg"])
    mocker.patch('subprocess.run')
    mocker.patch('os.remove')
    
    path = generate_audio("Olá mundo")
    assert type(path) is str
    assert mock_tts.tts_to_file.called

def test_generate_audio_fallback_lang(mocker):
    mocker.patch('database.get_config', return_value='kokoro')
    mocker.patch('utils.audio_utils.get_kokoro_model')
    from langdetect.lang_detect_exception import LangDetectException
    mocker.patch('utils.audio_utils.detect', side_effect=LangDetectException(0, "error"))
    mocker.patch('utils.file_utils.get_temp_file_path', side_effect=["/tmp/test.wav", "/tmp/audio.ogg"])
    
    mock_model = MagicMock()
    mock_model.create.return_value = (b"samples", 24000)
    au._kokoro_model = mock_model
    
    mocker.patch('soundfile.write')
    mocker.patch('subprocess.run')
    mocker.patch('os.remove')
    
    path = generate_audio("Hello")
    assert type(path) is str
    
def test_generate_audio_error(mocker):
    mocker.patch('database.get_config', return_value='kokoro')
    mocker.patch('utils.audio_utils.get_kokoro_model', side_effect=Exception("Failed"))
    path = generate_audio("Hello")
    assert path == ""

def test_get_whisper_model(mock_db_config):
    model = get_whisper_model()
    assert model is not None
    # Test caching
    assert get_whisper_model() is model

def test_transcribe_audio_success(mock_db_config):
    mock_model = MagicMock()
    mock_segment = MagicMock()
    mock_segment.text = "Hello world"
    mock_model.transcribe.return_value = ([mock_segment], None)
    au._whisper_model = mock_model
    
    res = transcribe_audio("fake.ogg")
    assert res == "Hello world"

def test_transcribe_audio_empty(mock_db_config):
    mock_model = MagicMock()
    mock_model.transcribe.return_value = ([], None)
    au._whisper_model = mock_model
    
    res = transcribe_audio("fake.ogg")
    assert "no text detected" in res

def test_transcribe_audio_not_installed(mock_db_config):
    au.WhisperModel = None
    res = transcribe_audio("fake.ogg")
    assert "faster-whisper not installed" in res

def test_transcribe_audio_error(mock_db_config):
    mock_model = MagicMock()
    mock_model.transcribe.side_effect = Exception("Fail")
    au._whisper_model = mock_model
    res = transcribe_audio("fake.ogg")
    assert "transcription error" in res

def test_transcribe_audio_ffmpeg_fallback_on_old_av(mock_db_config, mocker):
    """Regression (cloud): an old PyAV raises
    "TypeError: open() got an unexpected keyword argument 'metadata_errors'"
    inside faster-whisper's decode_audio. transcribe_audio must retry with an
    ffmpeg-decoded numpy array instead of surfacing the error."""
    import numpy as np

    mock_model = MagicMock()
    mock_segment = MagicMock()
    mock_segment.text = "ola mundo"
    mock_model.transcribe.side_effect = [
        TypeError("open() got an unexpected keyword argument 'metadata_errors'"),
        ([mock_segment], None),
    ]
    au._whisper_model = mock_model
    au._current_whisper_model_name = "model_name"
    mocker.patch(
        "utils.audio_utils._decode_audio_with_ffmpeg",
        return_value=np.zeros(1600, dtype="float32"),
    )

    res = transcribe_audio("fake.ogg")
    assert res == "ola mundo"
    assert mock_model.transcribe.call_count == 2
    # The retry must feed decoded samples, not the original file path
    second_audio = mock_model.transcribe.call_args_list[1][0][0]
    assert not isinstance(second_audio, str)

def test_transcribe_audio_fallback_unavailable_keeps_error(mock_db_config, mocker):
    """When the ffmpeg fallback cannot decode either, the original error must
    still surface through the standard '[Audio transcription error: ...]'."""
    mock_model = MagicMock()
    mock_model.transcribe.side_effect = TypeError(
        "open() got an unexpected keyword argument 'metadata_errors'"
    )
    au._whisper_model = mock_model
    au._current_whisper_model_name = "model_name"
    mocker.patch("utils.audio_utils._decode_audio_with_ffmpeg", return_value=None)

    res = transcribe_audio("fake.ogg")
    assert "transcription error" in res
    assert "metadata_errors" in res

def test_decode_audio_with_ffmpeg_success(mocker):
    import numpy as np

    mock_run = mocker.patch("subprocess.run")
    mock_run.return_value.returncode = 0
    mocker.patch("utils.file_utils.get_temp_file_path", return_value="/tmp/fb.wav")
    mocker.patch("os.path.exists", return_value=True)
    mocker.patch("os.unlink")
    mocker.patch("soundfile.read", return_value=(np.array([[0.1, 0.2]], dtype="float32"), 16000))

    audio = au._decode_audio_with_ffmpeg("/input.ogg")
    assert audio is not None
    assert audio.dtype == np.float32

def test_decode_audio_with_ffmpeg_failure_returns_none(mocker):
    mocker.patch("subprocess.run")  # returncode 0, but file not written
    mocker.patch("utils.file_utils.get_temp_file_path", return_value="/tmp/fb.wav")
    mocker.patch("os.path.exists", return_value=False)

    assert au._decode_audio_with_ffmpeg("/input.ogg") is None

def test_process_base64_audio_to_text(mocker):
    mocker.patch('base64.b64decode', return_value=b"audio data")
    mocker.patch('utils.audio_utils.transcribe_audio', return_value="Decoded text")
    mocker.patch('os.unlink')
    
    res = process_base64_audio_to_text("YXVkaW8=", "audio/mp4")
    assert res == "Decoded text"

def test_process_base64_audio_to_text_error(mocker):
    mocker.patch('base64.b64decode', side_effect=Exception("Fail decode"))
    with pytest.raises(Exception):
        process_base64_audio_to_text("bad")

def test_transcribe_webhook_audio(mocker):
    mocker.patch('utils.audio_utils.process_base64_audio_to_text', return_value="Decoded")
    res = transcribe_webhook_audio("Original msg", "base64", "mime")
    assert "Original msg" in res
    assert "[Transcription]: Decoded" in res

def test_transcribe_webhook_audio_error(mocker):
    mocker.patch('utils.audio_utils.process_base64_audio_to_text', side_effect=Exception("Fail"))
    res = transcribe_webhook_audio("Original msg", "base64", "mime")
    assert "[Internal error processing audio]" in res
