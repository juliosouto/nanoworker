import os
import subprocess
import time
from datetime import datetime
from utils.security_utils import require_permission

@require_permission('PERM_SCREENSHOT')
def take_mac_screenshot(output_path: str = None) -> str:
    """
    Takes a screenshot of the macOS screen and saves it.
    If output_path is not provided, it generates one in temp/screenshots/.
    """
    if not output_path:
        os.makedirs("temp/screenshots", exist_ok=True)
        timestamp = datetime.now().strftime("%Y%m%d_%H%M%S")
        output_path = f"temp/screenshots/screenshot_{timestamp}.png"
    
    time.sleep(3)
        
    try:
        subprocess.run(["screencapture", output_path], check=True)
        return f"Screenshot saved successfully at: {output_path}"
    except subprocess.CalledProcessError as e:
        return f"Error taking screenshot: {str(e)}"
    except Exception as e:
        return f"Unexpected error: {str(e)}"
