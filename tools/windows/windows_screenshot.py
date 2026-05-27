import os
import time
from datetime import datetime
from PIL import ImageGrab

from utils.security_utils import require_permission

@require_permission('PERM_SCREENSHOT')
def take_windows_screenshot(output_path: str = None) -> str:
    """
    Takes a screenshot of the Windows screen and saves it locally.
    If output_path is not provided, it generates one in temp/screenshots/.
    IMPORTANT: This tool only saves the file locally. To actually show it to the user on WhatsApp,
    you MUST subsequently call the `send_whatsapp_file` tool with the returned path and phone_number="self".
    """
    if not output_path:
        os.makedirs("temp/screenshots", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"temp/screenshots/screenshot_{timestamp}.png"
    
    time.sleep(3)
        
    try:
        screenshot = ImageGrab.grab()
        screenshot.save(output_path)
        return f"Screenshot saved successfully at: {output_path}"
    except Exception as e:
        return f"Error taking screenshot: {str(e)}"
