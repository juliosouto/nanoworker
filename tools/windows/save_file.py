import os
from utils.file_saver_core import core_save_file

def save_file_to_disk(file_content: str, filename: str, category: str) -> str:
    """
    Saves a file to the project's local disk structure under the specified category.
    Use this tool when you need to store files like documents, images, music, or videos.
    
    Args:
        file_content: The content of the file (can be raw text or a base64 encoded string).
        filename: The name to save the file as (e.g., 'report.pdf', 'photo.jpg').
        category: The category directory. Must be one of: 'documents', 'downloads', 'images', 'music', 'temp', 'videos'.
        
    Returns:
        str: A success message indicating where the file was saved, or an error message.
    """
    success, result = core_save_file(file_content, filename, category)
    
    if success:
        # Windows specific behavior: We might want to remove 'read-only' if it was inherited
        # Using basic python os functions as placeholders for future pywin32 integrations
        import stat
        try:
            os.chmod(result, stat.S_IWRITE)
        except Exception:
            pass
        return result
    else:
        return result
