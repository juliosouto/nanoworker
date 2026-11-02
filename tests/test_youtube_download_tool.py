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


@pytest.fixture(autouse=True)
def proxy():
    """Mocked proxy manager: each enable_proxy hands out a new proxy."""
    state = {"current": None, "enabled": [], "disabled": 0}

    def enable():
        state["current"] = f"http://p{len(state['enabled']) + 1}:8080"
        state["enabled"].append(state["current"])
        return state["current"]

    def disable():
        state["current"] = None
        state["disabled"] += 1

    with patch("utils.proxy_manager.enable_proxy", enable), \
            patch("utils.proxy_manager.disable_proxy", disable), \
            patch("utils.proxy_manager.get_current_proxy", lambda: state["current"]):
        yield state


@pytest.fixture
def ydl(tmp_path):
    """Fake YoutubeDL that 'downloads' into tmp_path and records its options."""
    seen = {"proxies": [], "fail_with": []}

    class FakeYDL:
        def __init__(self, options):
            seen["options"] = options
            seen["proxies"].append(options["proxy"])

        def __enter__(self):
            return self

        def __exit__(self, *a):
            return False

        def extract_info(self, url, download):
            seen["url"] = url
            if seen["fail_with"]:
                raise Exception(seen["fail_with"].pop(0))
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


def test_downloads_through_a_proxy_and_disconnects(ydl, proxy):
    _tool().download_youtube_video("https://youtu.be/abc")
    assert ydl["proxies"] == ["http://p1:8080"]
    assert proxy["current"] is None and proxy["disabled"] == 1


def test_switches_proxy_after_a_failure(ydl, proxy):
    ydl["fail_with"] = ["HTTP Error 403"]
    out = _tool().download_youtube_video("https://youtu.be/abc")
    assert out.startswith("Downloaded")
    assert ydl["proxies"] == ["http://p1:8080", "http://p2:8080"]
    assert proxy["current"] is None


def test_direct_connection_after_every_proxy_fails(ydl, proxy):
    ydl["fail_with"] = ["403"] * 3
    out = _tool().download_youtube_video("https://youtu.be/abc")
    assert out.startswith("Downloaded")
    assert ydl["proxies"][-1] == ""  # yt-dlp: empty proxy = direct connection
    assert len(ydl["proxies"]) == 4


def test_all_attempts_fail(ydl, proxy):
    ydl["fail_with"] = ["403"] * 3 + ["Video unavailable"]
    out = _tool().download_youtube_video("https://youtu.be/abc")
    assert out.startswith("Error downloading the video (all proxies and the direct connection failed)")
    assert "Video unavailable" in out
    assert proxy["current"] is None


def test_keeps_a_proxy_the_agent_turned_on(ydl, proxy):
    proxy["current"] = "http://mine:8080"
    _tool().download_youtube_video("https://youtu.be/abc")
    assert ydl["proxies"] == ["http://mine:8080"]
    assert proxy["disabled"] == 0 and proxy["current"] == "http://mine:8080"


def test_downloads_mp3_audio(ydl):
    out = _tool().download_youtube_video("https://www.youtube.com/watch?v=abc", audio_only=True)
    assert out.endswith("[abc].mp3")
    assert os.sep + os.path.join("files", "music") in ydl["options"]["outtmpl"]


@pytest.mark.parametrize("url", ["", "https://vimeo.com/1", "https://notyoutube.com/x", "youtube"])
def test_rejects_non_youtube_urls(ydl, url):
    assert _tool().download_youtube_video(url).startswith("Error: url must be a YouTube link")
    assert "url" not in ydl


@pytest.mark.parametrize("os_folder", OS_FOLDERS)
def test_tool_is_loaded_on_every_os(os_folder):
    import tools

    with patch.object(tools, "AVAILABLE_TOOLS", []):
        tools._load_tools_from_directory(
            os.path.join(os.path.dirname(tools.__file__), os_folder), f"tools.{os_folder}"
        )
        assert "download_youtube_video" in {f.__name__ for f in tools.AVAILABLE_TOOLS}
