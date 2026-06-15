import base64
import os
import re
import logging
from typing import Optional

logger = logging.getLogger(__name__)

ALLOWED_CATEGORIES = {"documents", "downloads", "images", "music", "temp", "videos"}

def secure_filename(filename: str) -> str:
    """Removes path traversal attempts and invalid characters from filename."""
    filename = os.path.basename(filename)
    filename = re.sub(r'[^a-zA-Z0-9_.-]', '_', filename)
    return filename

def core_save_file(file_content: str, filename: str, category: str) -> tuple[bool, str]:
    """
    Core logic to save a file to the project's /files/* structure.
    
    Args:
        file_content: Base64 string OR raw text to save.
        filename: Name of the file.
        category: Must be one of ALLOWED_CATEGORIES.
        
    Returns:
        tuple[bool, str]: (Success boolean, Message/Path).
    """
    if category not in ALLOWED_CATEGORIES:
        return False, f"Invalid category. Allowed categories are: {', '.join(ALLOWED_CATEGORIES)}"

    safe_filename = secure_filename(filename)
    if not safe_filename:
        return False, "Invalid filename."

    project_root = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    target_dir = os.path.join(project_root, "files", category)
    target_path = os.path.join(target_dir, safe_filename)

    os.makedirs(target_dir, exist_ok=True)

    try:
        # Check if it's base64 (very basic check)
        is_base64 = False
        content_to_write = None
        
        # Strip potential data URI headers
        content_str = file_content.strip()
        if content_str.startswith('data:'):
            try:
                _, b64_data = content_str.split(',', 1)
                content_to_write = base64.b64decode(b64_data)
                is_base64 = True
            except Exception:
                pass

        if not is_base64:
            # Try decoding as standard base64 if it looks like it
            if re.match(r'^[A-Za-z0-9+/]+={0,2}$', content_str) and len(content_str) % 4 == 0 and len(content_str) > 0:
                try:
                    content_to_write = base64.b64decode(content_str)
                    is_base64 = True
                except Exception:
                    pass

        if is_base64 and content_to_write is not None:
            with open(target_path, 'wb') as f:
                f.write(content_to_write)
        else:
            # Write as raw text
            with open(target_path, 'w', encoding='utf-8') as f:
                f.write(file_content)

        return True, target_path

    except Exception as e:
        logger.error(f"Failed to save file {filename} to {category}: {e}")
        return False, f"Error saving file: {str(e)}"
