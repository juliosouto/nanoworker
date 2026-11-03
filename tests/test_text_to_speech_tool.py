"""Tests for tools/text_to_speech.py with the TTS engine mocked."""

from unittest.mock import patch

from tools.text_to_speech import text_to_audio


def test_returns_path_of_generated_audio(tmp_path):
    out = tmp_path / "audio.ogg"
    out.write_bytes(b"OggS")
    with patch("utils.audio_utils.generate_audio", return_value=str(out)) as gen:
        result = text_to_audio("  Olá, tudo bem?  ")
    gen.assert_called_once_with("Olá, tudo bem?")
    assert result == f"Audio generated successfully: {out}"


def test_empty_text():
    assert text_to_audio("   ").startswith("Error")


def test_too_long_text():
    assert "too long" in text_to_audio("a" * 5001)


def test_engine_failure_returns_error():
    with patch("utils.audio_utils.generate_audio", return_value=""):
        assert text_to_audio("oi").startswith("Error")
    with patch("utils.audio_utils.generate_audio", side_effect=RuntimeError("boom")):
        assert "boom" in text_to_audio("oi")
