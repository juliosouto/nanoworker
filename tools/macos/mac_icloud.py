import os
import shutil

from utils.security_utils import require_permission

ICLOUD_DRIVE_PATH = os.path.expanduser("~/Library/Mobile Documents/com~apple~CloudDocs")

def _get_absolute_icloud_path(path_relative: str) -> str:
    """Helper to resolve a relative path to the absolute iCloud Drive path, ensuring it stays within iCloud."""
    if not os.path.exists(ICLOUD_DRIVE_PATH):
        raise Exception(f"iCloud Drive folder not found at: {ICLOUD_DRIVE_PATH}")
    
    # Strip leading slashes to prevent absolute path evaluation by os.path.join
    path_relative = path_relative.lstrip("/")
    abs_path = os.path.abspath(os.path.join(ICLOUD_DRIVE_PATH, path_relative))
    
    # Ensure it doesn't break out of iCloud Drive
    if not abs_path.startswith(ICLOUD_DRIVE_PATH):
        raise ValueError("Access to paths outside of iCloud Drive is restricted.")
    
    return abs_path

@require_permission('PERM_ICLOUD')
def list_icloud_files(path_relative: str = "") -> list:
    """
    Lists files and directories within a folder in iCloud Drive.
    
    Args:
        path_relative: Relative path of the folder (e.g. 'Documents' or ''). 
                       Empty for the root of iCloud Drive.
    """
    target_path = _get_absolute_icloud_path(path_relative)
    
    if not os.path.isdir(target_path):
        raise NotADirectoryError(f"The path is not a directory or does not exist: {target_path}")
        
    try:
        items = []
        for item in os.listdir(target_path):
            item_path = os.path.join(target_path, item)
            items.append({
                "name": item,
                "is_dir": os.path.isdir(item_path),
                "size": os.path.getsize(item_path) if os.path.isfile(item_path) else None
            })
        return items
    except PermissionError as e:
        raise PermissionError(f"Permission denied when accessing {target_path}. Check if the process has Full Disk Access.") from e

@require_permission('PERM_ICLOUD')
def read_icloud_file(file_path_relative: str) -> str:
    """
    Reads the content of a text file in iCloud Drive.
    
    Args:
        file_path_relative: File path relative to the root of iCloud Drive (e.g. 'Notes/text.txt').
    """
    target_path = _get_absolute_icloud_path(file_path_relative)
    
    if not os.path.isfile(target_path):
        raise FileNotFoundError(f"File not found: {target_path}")
        
    try:
        with open(target_path, 'r', encoding='utf-8') as f:
            return f.read()
    except PermissionError as e:
        raise PermissionError(f"Permission denied when reading {target_path}. Check macOS permissions.") from e
    except UnicodeDecodeError as e:
        raise ValueError(f"The file appears to be binary or is not UTF-8 encoded: {target_path}") from e

@require_permission('PERM_ICLOUD')
def write_icloud_file(file_path_relative: str, content: str) -> str:
    """
    Writes content (text) to a file in iCloud Drive. 
    If the parent folder does not exist, it will be created.
    
    Args:
        file_path_relative: Relative path of the file (e.g. 'Notes/new_text.txt').
        content: The text content to be written to the file.
    """
    target_path = _get_absolute_icloud_path(file_path_relative)
    parent_dir = os.path.dirname(target_path)
    
    try:
        if not os.path.exists(parent_dir):
            os.makedirs(parent_dir, exist_ok=True)
            
        with open(target_path, 'w', encoding='utf-8') as f:
            f.write(content)
        return f"File saved successfully at: {target_path}"
    except PermissionError as e:
        raise PermissionError(f"Permission denied when writing to {target_path}. Check macOS permissions.") from e
