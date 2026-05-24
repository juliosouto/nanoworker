import base64
import logging
import os
import shutil
import uuid

import requests

from utils.security_utils import require_permission

logger = logging.getLogger(__name__)

def get_temp_dir() -> str:
    """Returns the absolute path to the project's temp directory, creating it if necessary."""
    temp_dir = os.path.join(os.path.dirname(os.path.dirname(os.path.abspath(__file__))), "temp")
    os.makedirs(temp_dir, exist_ok=True)
    return temp_dir

def get_temp_file_path(filename: str = "") -> str:
    """Generates a unique temporary file path within the project's temp directory."""
    temp_dir = get_temp_dir()
    unique_id = uuid.uuid4().hex[:8]
    if filename:
        return os.path.join(temp_dir, f"{unique_id}_{filename}")
    return os.path.join(temp_dir, unique_id)

def create_temp_copy(file_path: str) -> str:
    """Creates a temporary copy of a file and returns the path to the copy."""
    file_name = os.path.basename(file_path)
    temp_file_path = get_temp_file_path(file_name)
    shutil.copy2(file_path, temp_file_path)
    return temp_file_path

@require_permission('PERM_FS')
def read_file(path: str) -> str:
    """
    Reads the content of a file from the filesystem.
    
    Args:
        path: The absolute or relative path to the file to read.
        
    Returns:
        The content of the file as a string.
    """
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read()
    except Exception as e:
        return f"Error reading file {path}: {str(e)}"

@require_permission('PERM_FS')
def write_file(path: str, content: str) -> str:
    """
    Writes content to a file in the filesystem.
    Creates parent directories if they don't exist.
    
    Args:
        path: The absolute or relative path to the file to write.
        content: The text content to write to the file.
        
    Returns:
        A success message or an error message.
    """
    try:
        os.makedirs(os.path.dirname(os.path.abspath(path)), exist_ok=True)
        with open(path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"Successfully wrote to {path}"
    except Exception as e:
        return f"Error writing to file {path}: {str(e)}"

def download_file(url: str, dest: str) -> None:
    """Downloads a file from a URL to a destination path."""
    logger.info(f"Downloading {url} to {dest}...")
    response = requests.get(url, stream=True)
    response.raise_for_status()
    with open(dest, "wb") as f:
        for chunk in response.iter_content(chunk_size=8192):
            f.write(chunk)
    logger.info(f"Downloaded {dest}.")

def save_base64_attachment(b64_data: str, file_name: str = 'attachment') -> str | None:
    """
    Decodifica um base64 e salva o arquivo em temp/.
    Retorna o caminho com prefixo "path:" em caso de sucesso.
    """
    try:
        file_path = get_temp_file_path(file_name)
        with open(file_path, "wb") as f:
            f.write(base64.b64decode(b64_data))
        return "path:" + file_path
    except Exception as e:
        logger.error(f"Failed to save attachment to temp/: {e}")
        return None

def get_file_tree(dir_path: str, base_dir: str) -> list:
    tree = []
    try:
        entries = sorted(os.scandir(dir_path), key=lambda e: (not e.is_dir(), e.name.lower()))
        for entry in entries:
            if entry.name in ['.git', '.venv', 'node_modules', '__pycache__', '.DS_Store', '.whatsapp_session', 'nanoworker.db', '.store']:
                continue
            
            rel_path = os.path.relpath(entry.path, start=base_dir)
            
            if entry.is_dir():
                tree.append({
                    "name": entry.name,
                    "path": rel_path,
                    "type": "directory",
                    "children": get_file_tree(entry.path, base_dir)
                })
            else:
                tree.append({
                    "name": entry.name,
                    "path": rel_path,
                    "type": "file"
                })
    except Exception as e:
        logging.error(f"Error reading directory {dir_path}: {e}")
    return tree
