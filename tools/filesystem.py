import os

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
