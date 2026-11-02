"""
Downloads a YouTube video (or only its audio) with yt-dlp into the project's
files/videos (or files/music) folder, ready to be sent with send_whatsapp_file.
"""

import logging
import os
from urllib.parse import urlparse

logger = logging.getLogger(__name__)

_YOUTUBE_HOSTS = ("youtube.com", "youtu.be")
# Free proxies fail often: try this many before the direct connection.
_PROXY_ATTEMPTS = 3


def _is_youtube(url) -> bool:
    host = (urlparse(url).hostname or "").lower()
    return any(host == h or host.endswith("." + h) for h in _YOUTUBE_HOSTS)


def _files_dir(category):
    project_root = os.path.dirname(os.path.dirname(os.path.dirname(os.path.abspath(__file__))))
    path = os.path.join(project_root, "files", category)
    os.makedirs(path, exist_ok=True)
    return path


def download_youtube_video(url: str, audio_only: bool = False, max_height: int = 720) -> str:
    """Downloads a YouTube video as MP4 (or only its audio as MP3) to the local disk. The tool connects to a proxy by itself (switching proxies when one fails), then disconnects: do NOT call manage_proxy around it. After it returns, carry on with what the user asked (e.g. send the file with send_whatsapp_file).

    Args:
        url (str): The YouTube video URL (youtube.com or youtu.be).
        audio_only (bool): True to download only the audio as MP3 (default False).
        max_height (int): Maximum video height in pixels, e.g. 360, 480, 720, 1080 (default 720). Ignored for audio.

    Returns:
        str: A success message with the ABSOLUTE path of the saved file, or an error message.
             When sending the file afterwards (send_whatsapp_file), use exactly this path.
    """
    url = str(url or "").strip()
    if not _is_youtube(url):
        return "Error: url must be a YouTube link (youtube.com or youtu.be)."
    try:
        max_height = int(max_height)
    except (TypeError, ValueError):
        return "Error: max_height must be a number, e.g. 720."

    try:
        import yt_dlp
    except ImportError:
        return "Error: yt-dlp is not installed. Run: pip install yt-dlp"

    from database import get_config

    try:
        max_mb = int(get_config("MAX_DOWNLOAD_SIZE_MB", "100"))
    except (TypeError, ValueError):
        max_mb = 100

    options = {
        "outtmpl": os.path.join(_files_dir("music" if audio_only else "videos"), "%(title).80s [%(id)s].%(ext)s"),
        "noplaylist": True,
        "quiet": True,
        "noprogress": True,
        "no_warnings": True,
        "restrictfilenames": True,
        "max_filesize": max_mb * 1024 * 1024,
    }
    if audio_only:
        options["format"] = "bestaudio/best"
        options["postprocessors"] = [{"key": "FFmpegExtractAudio", "preferredcodec": "mp3"}]
    else:
        # MP4 (H.264 + AAC) plays everywhere, WhatsApp included.
        options["format"] = (
            f"bv*[height<={max_height}][ext=mp4]+ba[ext=m4a]/"
            f"b[height<={max_height}][ext=mp4]/b[height<={max_height}]/b"
        )
        options["merge_output_format"] = "mp4"

    from utils.proxy_manager import disable_proxy, enable_proxy, get_current_proxy

    # A proxy the agent turned on before stays on; one this tool turns on is
    # turned off before returning.
    proxy_was_on = get_current_proxy() is not None
    errors = []
    info = path = None
    try:
        # One fresh proxy per attempt, then the direct connection as last resort.
        for attempt in range(_PROXY_ATTEMPTS + 1):
            proxy = None
            if attempt < _PROXY_ATTEMPTS:
                proxy = get_current_proxy() if proxy_was_on and attempt == 0 else enable_proxy()
                if not proxy:
                    errors.append("no working proxy found")
                    continue
            try:
                with yt_dlp.YoutubeDL({**options, "proxy": proxy or ""}) as ydl:
                    info = ydl.extract_info(url, download=True)
                    path = ydl.prepare_filename(info)
                break
            except Exception as e:
                logger.warning(f"YouTube download failed for {url} via {proxy or 'direct connection'}: {e}")
                errors.append(f"{proxy or 'direct'}: {e}")
    finally:
        if not proxy_was_on:
            disable_proxy()

    if path is None:
        return "Error downloading the video (all proxies and the direct connection failed): " + " | ".join(errors[-2:])

    # The postprocessors change the extension (merge to mp4, audio to mp3).
    path = os.path.splitext(path)[0] + (".mp3" if audio_only else ".mp4")
    if not os.path.exists(path):
        return f"Error: the download did not produce a file (it may exceed the {max_mb}MB limit)."
    size_mb = os.path.getsize(path) / (1024 * 1024)
    return f"Downloaded '{info.get('title', '')}' ({size_mb:.1f}MB) to: {os.path.abspath(path)}"
