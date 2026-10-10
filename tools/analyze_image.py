import logging
import os

from utils.security_utils import require_permission

logger = logging.getLogger(__name__)

_MAX_IMAGE_BYTES = 15 * 1024 * 1024

_MIME_BY_EXT = {
    ".png": "image/png",
    ".jpg": "image/jpeg",
    ".jpeg": "image/jpeg",
    ".webp": "image/webp",
    ".gif": "image/gif",
    ".bmp": "image/bmp",
}


@require_permission('PERM_FS')
def analyze_image(image_path: str, question: str = "Describe this image in detail.") -> str:
    """
    Analyzes a local image with the vision model and answers a question about it.
    Use this tool when you need to SEE an image: describe screenshots, verify a crop_image/browser_screenshot
    result, read text inside images, or answer questions about visual content.
    
    Args:
        image_path: ABSOLUTE path of the image file (e.g. as returned by browser_screenshot).
        question: What you want to know about the image (e.g. 'Read the headline' or
                  'Does this screenshot still show a cookie consent popup?'). Default: detailed description.
    
    Returns:
        str: The vision model's answer, or an error message.
    """
    try:
        if not image_path or not os.path.isfile(image_path):
            return f"Error: image file not found: {image_path}"

        if os.path.getsize(image_path) > _MAX_IMAGE_BYTES:
            return (
                f"Error: image is larger than {_MAX_IMAGE_BYTES // (1024 * 1024)}MB. "
                f"Use image_resize to shrink it first."
            )

        from database import get_config

        api_key = get_config("GEMINI_API_KEY", "")
        if not api_key:
            return "Error: GEMINI_API_KEY is not configured in the settings, so vision analysis is unavailable."

        model_name = get_config("GEMINI_MODEL", "") or "gemini-2.0-flash"

        ext = os.path.splitext(image_path)[1].lower()
        mime = _MIME_BY_EXT.get(ext, "image/png")

        from google import genai
        from google.genai import types

        with open(image_path, "rb") as f:
            image_bytes = f.read()

        client = genai.Client(api_key=api_key)
        response = client.models.generate_content(
            model=model_name,
            contents=[
                question,
                types.Part.from_bytes(data=image_bytes, mime_type=mime),
            ],
        )

        answer = (response.text or "").strip()
        if not answer:
            return "Error: the vision model returned an empty answer."
        return answer
    except Exception as e:
        logger.error(f"analyze_image failed: {e}")
        return f"Error analyzing image: {str(e)}"