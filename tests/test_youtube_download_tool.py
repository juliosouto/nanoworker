"""Tests for tools/<os>/youtube_download.py with yt-dlp mocked (no network)."""

import importlib
import os
from pathlib import Path
from unittest.mock import MagicMock, patch

import pytest

OS_FOLDERS = ("linux", "macos", "windows")


def _tool(os_folder="linux"):
    return importlib.import_module(f"tools.{os_folder}.youtube_download")


@pytest.fixture(autouse=True)
def db():
    from database import init_db

    init_db()


@pytest.fixture
def ydl(tmp_path):
    """Fake YoutubeDL that 'downloads' into tmp_path and records its options."""
    seen = {}

    class FakeYDL:
        def __init__(self, options):
            seen["options"] = options

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            seen["url"] = url
            return {"title": "Me at the zoo", "id": "abc"}

        def prepare_filename(self, info):
            ext = ".mp3" if "postprocessors" in seen["options"] else ".mp4"
            path = tmp_path / f"Me_at_the_zoo [abc]{ext}"
            path.write_bytes(b"x" * 1024)
            return str(path.with_suffix(".webm"))

    fake = MagicMock(YoutubeDL=FakeYDL)
    with patch.dict("sys.modules", {"yt_dlp": fake}):
        yield seen


def test_same_tool_on_every_os():
    root = Path(__file__).resolve().parent.parent / "tools"
    assert len({(root / f / "youtube_download.py").read_text() for f in OS_FOLDERS}) == 1


@pytest.mark.parametrize("os_folder", OS_FOLDERS)
def test_downloads_mp4_video(ydl, os_folder):
    out = _tool(os_folder).download_youtube_video("https://youtu.be/abc", max_height=480)
    assert out.startswith("Downloaded 'Me at the zoo'") and out.endswith("[abc].mp4")
    options = ydl["options"]
    assert "height<=480" in options["format"] and options["merge_output_format"] == "mp4"
    assert os.sep + os.path.join("files", "videos") in options["outtmpl"]
    assert options["noplaylist"] is True


def test_downloads_mp3_audio(ydl):
    out = _tool().download_youtube_video("https://www.youtube.com/watch?v=abc", audio_only=True)
    assert out.endswith("[abc].mp3")
    assert os.sep + os.path.join("files", "music") in ydl["options"]["outtmpl"]


@pytest.mark.parametrize("url", ["", "https://vimeo.com/1", "https://notyoutube.com/x", "youtube"])
def test_rejects_non_youtube_urls(ydl, url):
    assert _tool().download_youtube_video(url).startswith("Error: url must be a YouTube link")
    assert "url" not in ydl


def test_reports_download_errors():
    fake = MagicMock()
    fake.YoutubeDL.return_value.__enter__.return_value.extract_info.side_effect = Exception("Video unavailable")
    with patch.dict("sys.modules", {"yt_dlp": fake}):
        out = _tool().download_youtube_video("https://youtu.be/abc")
    assert out == "Error downloading the video: Video unavailable"


@pytest.mark.parametrize("os_folder", OS_FOLDERS)
def test_tool_is_loaded_on_every_os(os_folder):
    import tools

    with patch.object(tools, "AVAILABLE_TOOLS", []):
        tools._load_tools_from_directory(
            os.path.join(os.path.dirname(tools.__file__), os_folder), f"tools.{os_folder}"
        )
        assert "download_youtube_video" in {f.__name__ for f in tools.AVAILABLE_TOOLS}
