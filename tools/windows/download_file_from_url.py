import requests
import base64
from tools.windows.save_file import save_file_to_disk
from database import get_config

def download_file_from_url(url: str, filename: str, category: str) -> str:
    """
    Downloads a file from a given URL and saves it to the project's local disk under the specified category.
    Use this tool to download any kind of file (images, PDFs, documents, etc.) from the internet.
    
    Args:
        url: The URL to download the file from.
        filename: The name to save the downloaded file as (e.g., 'report.pdf', 'photo.jpg').
                  IMPORTANT: always include the correct file extension (e.g. '.jpg', '.png', '.pdf').
                  The extension is used to determine the file type when later sent to WhatsApp.
        category: The category directory. Must be one of: 'documents', 'downloads', 'images', 'music', 'temp', 'videos'.
                  Use 'images' for pictures downloaded from the web.
        
    Returns:
        str: A success message containing the ABSOLUTE saved path, or an error message.
             IMPORTANT: when sending the downloaded file afterwards, you MUST use the exact
             absolute path returned here (with send_whatsapp_file) — do not reconstruct it.
    """
    try:
        headers = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36"}
        with requests.get(url, stream=True, timeout=30, headers=headers) as response:
            response.raise_for_status()
            
            # Limit to prevent memory issues with base64 encoding (default 100MB)
            try:
                max_mb = int(get_config('MAX_DOWNLOAD_SIZE_MB', '100'))
            except (ValueError, TypeError):
                max_mb = 100
                
            MAX_SIZE = max_mb * 1024 * 1024
            content_bytes = bytearray()
            for chunk in response.iter_content(chunk_size=8192):
                if chunk:
                    content_bytes.extend(chunk)
                    if len(content_bytes) > MAX_SIZE:
                        return f"Error: File is too large (exceeds {max_mb}MB limit)."
            
            # Encode as base64 and format as Data URI so the core saver processes it correctly as a binary file
            b64_data = base64.b64encode(content_bytes).decode('utf-8')
            data_uri = f"data:application/octet-stream;base64,{b64_data}"
            
            return save_file_to_disk(data_uri, filename, category)
        
    except requests.RequestException as e:
        return f"Network error downloading file from URL: {str(e)}"
    except Exception as e:
        return f"Error processing downloaded file: {str(e)}"
