from browser.manager import BrowserManager, get_session_browser

from utils.file_utils import get_temp_file_path
from utils.security_utils import require_permission
from utils.session import current_session_id

def get_browser_manager() -> BrowserManager:
    session_id = current_session_id.get()
    if not session_id:
        # Fallback to a default session if not set (e.g., testing)
        session_id = "default"
        
    return get_session_browser(session_id)

@require_permission('PERM_PLAYWRIGHT')
def browser_navigate(url: str) -> str:
    """
    Navigates the browser to a URL. 
    Use this tool for general browser automation unless the user explicitly requests Safari.
    Use this tool before extracting information or interacting with elements on a page.
    
    Args:
        url: The full URL to navigate to (e.g. 'https://example.com').
    """
    bm = get_browser_manager()
    return bm.navigate(url)

@require_permission('PERM_PLAYWRIGHT')
def browser_snapshot(interactive_only: bool = True) -> str:
    """
    Returns an LLM-friendly DOM representation of the current page.
    Use this tool for general browser automation unless the user explicitly requests Safari.
    Interactive elements will have a reference ID like [@e1], [@e2].
    Use this tool to see what is on the page and get reference IDs for interactions.
    
    Args:
        interactive_only: If True, only returns interactive elements (recommended).
    """
    bm = get_browser_manager()
    return bm.get_snapshot(interactive_only=interactive_only)

@require_permission('PERM_PLAYWRIGHT')
def browser_click(ref_id: str) -> str:
    """
    Clicks on an element specified by its reference ID (e.g., '@e1').
    Use this tool for general browser automation unless the user explicitly requests Safari.
    You must call browser_snapshot first to get valid reference IDs.
    
    Args:
        ref_id: The reference ID of the element to click (e.g., '@e1').
    """
    bm = get_browser_manager()
    return bm.click(ref_id)

@require_permission('PERM_PLAYWRIGHT')
def browser_fill(ref_id: str, text: str) -> str:
    """
    Fills an input field specified by its reference ID with the given text.
    Use this tool for general browser automation unless the user explicitly requests Safari.
    You must call browser_snapshot first to get valid reference IDs.
    
    Args:
        ref_id: The reference ID of the element (e.g., '@e1').
        text: The text to fill into the element.
    """
    bm = get_browser_manager()
    return bm.fill(ref_id, text)

@require_permission('PERM_PLAYWRIGHT')
def browser_extract(ref_id: str, property_name: str = "text") -> str:
    """
    Extracts text or an attribute from an element specified by its reference ID.
    Use this tool for general browser automation unless the user explicitly requests Safari.
    
    Args:
        ref_id: The reference ID of the element (e.g., '@e1').
        property_name: The property to extract ('text', 'html', or an attribute like 'href'). Defaults to 'text'.
    """
    bm = get_browser_manager()
    return bm.extract(ref_id, property_name)

@require_permission('PERM_PLAYWRIGHT')
def browser_run_js(script: str) -> str:
    """
    Executes arbitrary JavaScript on the current page and returns the result.
    Use this tool for general browser automation unless the user explicitly requests Safari.
    
    Args:
        script: The JavaScript code to evaluate. Must return a value.
    """
    bm = get_browser_manager()
    return bm.run_js(script)

@require_permission('PERM_PLAYWRIGHT')
def browser_screenshot(full_page: bool = False) -> str:
    """
    Takes a screenshot of the current page using the built-in headless browser and saves it as a PNG file.
    Use this tool whenever the user asks for a screenshot (or 'print') of a web page. It works on
    servers without a graphical display (e.g. Docker/headless Linux) because it renders with the
    internal headless Chromium — never use scrot or X11 tools for web page screenshots.
    You must call browser_navigate first to load the page.
    
    Args:
        full_page: If True, captures the entire scrollable page. If False (default), captures only the visible viewport.
        
    Returns:
        str: A success message containing the ABSOLUTE path of the saved PNG, or an error message.
             IMPORTANT: to share the image afterwards, you MUST pass the exact absolute path returned
             here to the send_whatsapp_file tool — do not reconstruct it.
    """
    bm = get_browser_manager()
    screenshot_path = get_temp_file_path("screenshot.png")
    return bm.take_screenshot(screenshot_path)

@require_permission('PERM_PLAYWRIGHT')
def browser_scroll(magnitude: float = 800) -> str:
    """
    Scrolls the current page by a number of pixels (positive down, negative up) and waits briefly for lazy-loaded content.
    Use this tool before browser_screenshot or browser_snapshot when the page only loads content as you scroll.
    
    Args:
        magnitude: Pixels to scroll. Positive scrolls down, negative scrolls up. Default 800.
    """
    bm = get_browser_manager()
    return bm.scroll(magnitude)

@require_permission('PERM_PLAYWRIGHT')
def browser_pdf(output_path: str = None) -> str:
    """
    Saves the current page as a PDF file using the headless browser and returns the ABSOLUTE path of the saved file.
    Use this tool when the user asks to save/export a web page as PDF. You must call browser_navigate first.
    
    Args:
        output_path: Optional ABSOLUTE path for the PDF. If omitted, a new temp file is created.
    
    Returns:
        str: A success message containing the ABSOLUTE path of the PDF, or an error message.
             IMPORTANT: to share the file afterwards, pass the exact path returned here to send_whatsapp_file.
    """
    bm = get_browser_manager()
    pdf_path = output_path or get_temp_file_path("page.pdf")
    return bm.save_as_pdf(pdf_path)
