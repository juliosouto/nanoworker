"""Composite tool: search for an image online and send it to the current chat.

This wraps search + download + send into a SINGLE call so that small models only
need to provide a query (and optional caption) — they no longer have to juggle
URLs, absolute file paths, categories or the group JID across chained tool calls.
"""
import importlib
import json
import logging
import platform
import re

from utils.session import current_session_id

logger = logging.getLogger(__name__)


def _os_folder() -> str:
    p = platform.system()
    if p == "Windows":
        return "windows"
    if p == "Linux":
        return "linux"
    return "macos"


def _sanitize_filename_from_wikimedia_url(url: str, title: str = "") -> str:
    """Derives a safe filename (with extension) from a Wikimedia upload URL."""
    leaf = url.rstrip("/").split("/")[-1]
    # Wikimedia thumb URLs end like ".../320px-Name.jpg" ; drop the "NNNpx-" prefix.
    leaf = re.sub(r"^\d+px-", "", leaf)
    if leaf.startswith("thumb"):
        leaf = leaf.split("-", 1)[-1]
    leaf = re.sub(r"[^a-zA-Z0-9_.-]", "_", leaf).strip(".")
    if not leaf:
        leaf = re.sub(r"[^a-zA-Z0-9_-]", "_", title or "image").strip("_")[:40] or "image"
    if "." not in leaf:
        leaf += ".jpg"
    return leaf


def _resolve_current_channel():
    """Returns the channel_id of the current session (WhatsApp JID) or None."""
    session_id = current_session_id.get()
    if not session_id:
        return None
    try:
        from database import get_db
        conn = get_db()
        try:
            cursor = conn.cursor()
            cursor.execute('SELECT channel_id FROM sessions WHERE id = ?', (session_id,))
            row = cursor.fetchone()
            return row['channel_id'] if row else None
        finally:
            conn.close()
    except Exception as e:
        logger.error(f"Failed to resolve current channel: {e}")
        return None


def find_and_send_image(query: str, caption: str = "") -> str:
    """
    Searches for an image on the web and sends it directly to the CURRENT WhatsApp chat.
    Use this tool whenever the user asks you to send, show, post, find or provide an
    image, picture, photo or meme in this chat. It handles search, download and sending
    in one step — you only need to provide the search term.

    Args:
        query: The term to search for (e.g. 'golden retriever dog', 'Eiffel Tower').
        caption: Optional short text caption to accompany the image (default empty).

    Returns:
        str: A confirmation that the image was sent, or a clear error message.
    """
    query = str(query or "").strip()
    if not query:
        return "Error: the 'query' parameter is required. Provide a term to search for an image."

    channel = _resolve_current_channel()
    if not channel:
        return ("Error: could not determine the current WhatsApp chat. "
                "The image tool can only send to the current conversation; "
                "reply inside the target group/chat before asking for an image.")

    folder = _os_folder()

    try:
        search_mod = importlib.import_module(f"tools.{folder}.wikimedia_image_search")
        results_raw = search_mod.search_wikimedia_images(query, limit=3)
    except Exception as e:
        return f"Error searching for images: {str(e)}"

    try:
        results = json.loads(results_raw)
    except Exception:
        results = None

    if not isinstance(results, list) or not results:
        return (f"No image found for query '{query}'. "
                f"Search result: {str(results_raw)[:200]}")

    url = results[0].get("url", "")
    title = results[0].get("title", "")
    if not url or "upload.wikimedia.org" not in url:
        return (f"Error: the first search result for '{query}' is not a direct image URL. "
                f"Raw results: {str(results_raw)[:200]}")

    filename = _sanitize_filename_from_wikimedia_url(url, title)

    try:
        dl_mod = importlib.import_module(f"tools.{folder}.download_file_from_url")
        saved = dl_mod.download_file_from_url(url, filename, "images")
    except Exception as e:
        return f"Error downloading image: {str(e)}"

    if isinstance(saved, str) and saved.lower().startswith(("error", "network error")):
        return saved

    try:
        wa_mod = importlib.import_module(f"tools.{folder}.whatsapp")
        return wa_mod.send_whatsapp_file(channel, saved, caption=str(caption or ""))
    except Exception as e:
        return f"Error sending image to WhatsApp: {str(e)}"