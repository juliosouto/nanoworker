import os
import sys
import types
from unittest.mock import MagicMock

import pytest
from PIL import Image

from tools.http_request import http_request
from tools.pdf_tools import pdf_to_text
from tools.audio_tools import audio_convert, audio_trim
from tools.analyze_image import analyze_image


@pytest.fixture
def perm_enabled(mocker):
    mocker.patch("utils.security_utils.get_config", return_value="true")


# ---------------- http_request ----------------

def test_http_request_blocks_private_targets(mocker, perm_enabled):
    mocker.patch(
        "tools.http_request.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("192.168.0.10", 0))],
    )
    result = http_request("https://internal.example.com/api")
    assert "private/reserved address" in result


def test_http_request_blocks_loopback(mocker, perm_enabled):
    result = http_request("http://127.0.0.1:5000/admin")
    assert "Error:" in result


def test_http_request_blocks_internal_names(perm_enabled):
    assert "internal and blocked" in http_request("http://localhost/api")
    assert "internal and blocked" in http_request("https://metadata.google.internal/x")


def test_http_request_blocks_scheme(perm_enabled):
    assert "not allowed" in http_request("ftp://example.com/file")


def test_http_request_blocks_method(perm_enabled):
    assert "not allowed" in http_request("https://example.com", method="TRACE")


def test_http_request_success(mocker, perm_enabled):
    mocker.patch(
        "tools.http_request.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    mock_resp = MagicMock()
    mock_resp.status_code = 200
    mock_resp.headers = {"Content-Type": "application/json"}
    mock_resp.text = '{"ok": true}'
    mock_resp.content = b'{"ok": true}'
    mock_requests = mocker.patch("tools.http_request.requests")
    mock_requests.post.return_value = mock_resp

    result = http_request("https://api.example.com/v1", method="POST", json_data='{"a": 1}')
    assert "Status: 200" in result
    assert '"ok": true' in result
    mock_requests.post.assert_called_once()


def test_http_request_invalid_json(mocker, perm_enabled):
    # DNS is resolved during the SSRF guard; mock it so the JSON error surfaces
    mocker.patch(
        "tools.http_request.socket.getaddrinfo",
        return_value=[(2, 1, 6, "", ("93.184.216.34", 0))],
    )
    result = http_request("https://api.example.com", json_data="{bad")
    assert "not valid JSON" in result


# ---------------- pdf_to_text ----------------

def test_pdf_to_text_missing_file(perm_enabled):
    assert "PDF file not found" in pdf_to_text("/no/doc.pdf")


def test_pdf_to_text_extracts_text(mocker, tmp_path, perm_enabled):
    fake_page = MagicMock()
    fake_page.extract_text.return_value = "hello from pdf"
    fake_reader = MagicMock()
    fake_reader.pages = [fake_page, fake_page]
    fake_pypdf = types.ModuleType("pypdf")
    fake_pypdf.PdfReader = MagicMock(return_value=fake_reader)

    mocker.patch.dict(sys.modules, {"pypdf": fake_pypdf})
    pdf = str(tmp_path / "doc.pdf")
    open(pdf, "w").write("%PDF-fake")

    result = pdf_to_text(pdf)
    assert "hello from pdf" in result
    assert "2 pages" in result


# ---------------- audio tools ----------------

def test_audio_convert_success(mocker, tmp_path, perm_enabled):
    src = str(tmp_path / "voice.ogg")
    open(src, "w").write("fake audio")
    mocker.patch("tools.audio_tools.shutil.which", return_value="/usr/bin/ffmpeg")
    mock_run = mocker.patch("tools.audio_tools.subprocess.run")
    mock_run.return_value.returncode = 0
    mocker.patch("os.path.getsize", return_value=1234)

    result = audio_convert(src, output_format="mp3")
    assert "Audio converted to mp3" in result
    assert mock_run.call_args[0][0][0] == "ffmpeg"


def test_audio_convert_no_ffmpeg(tmp_path, perm_enabled, mocker):
    src = str(tmp_path / "voice.ogg")
    open(src, "w").write("fake audio")
    mocker.patch("tools.audio_tools.shutil.which", return_value=None)
    assert "not available" in audio_convert(src)


def test_audio_convert_bad_format(tmp_path, perm_enabled):
    src = str(tmp_path / "voice.ogg")
    open(src, "w").write("x")
    assert "output_format must be one of" in audio_convert(src, output_format="exe")


def test_audio_trim_validates_range(tmp_path, perm_enabled):
    src = str(tmp_path / "voice.ogg")
    open(src, "w").write("x")
    result = audio_trim(src, start_seconds=30, end_seconds=10)
    assert "end_seconds must be greater" in result


# ---------------- analyze_image ----------------

def test_analyze_image_missing_file(perm_enabled):
    assert "image file not found" in analyze_image("/no/img.png")


def test_analyze_image_no_api_key(mocker, tmp_path, perm_enabled):
    mocker.patch("database.get_config", side_effect=lambda k, d=None: "" if k == "GEMINI_API_KEY" else d)
    img = str(tmp_path / "i.png")
    Image.new("RGB", (10, 10)).save(img)
    result = analyze_image(img)
    assert "GEMINI_API_KEY is not configured" in result


def test_analyze_image_success(mocker, tmp_path):
    mocker.patch("utils.security_utils.get_config", return_value="true")
    mocker.patch(
        "database.get_config",
        side_effect=lambda k, d=None: "fake-key" if k == "GEMINI_API_KEY" else (d or ""),
    )
    mock_client_cls = mocker.patch("google.genai.Client")
    mock_client_cls.return_value.models.generate_content.return_value.text = "It is a red square."

    img = str(tmp_path / "i.png")
    Image.new("RGB", (10, 10), color=(200, 0, 0)).save(img)

    result = analyze_image(img, question="What is it?")
    assert "red square" in result


# ---------------- browser_scroll / browser_pdf wrappers ----------------

def test_linux_browser_scroll_wrapper(mocker):
    import tools.linux.browser as lb
    mocker.patch("utils.security_utils.get_config", return_value="true")
    mock_bm = MagicMock()
    mock_bm.scroll.return_value = "Scrolled by 800 pixels"
    mocker.patch("tools.linux.browser.get_browser_manager", return_value=mock_bm)

    assert lb.browser_scroll(800) == "Scrolled by 800 pixels"
    mock_bm.scroll.assert_called_once_with(800)


def test_linux_browser_pdf_wrapper(mocker):
    import tools.linux.browser as lb
    mocker.patch("utils.security_utils.get_config", return_value="true")
    mocker.patch("tools.linux.browser.get_temp_file_path", return_value="/tmp/page.pdf")
    mock_bm = MagicMock()
    mock_bm.save_as_pdf.return_value = "PDF saved to /tmp/page.pdf"
    mocker.patch("tools.linux.browser.get_browser_manager", return_value=mock_bm)

    assert lb.browser_pdf() == "PDF saved to /tmp/page.pdf"
    mock_bm.save_as_pdf.assert_called_once_with("/tmp/page.pdf")