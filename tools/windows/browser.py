from browser.manager import BrowserManager

from utils.security_utils import require_permission
from utils.session import current_session_id

# Dictionary mapping session_id -> BrowserManager instance
_sessions = {}

def get_browser_manager() -> BrowserManager:
    session_id = current_session_id.get()
    if not session_id:
        # Fallback to a default session if not set (e.g., testing)
        session_id = "default"
        
    if session_id not in _sessions:
        _sessions[session_id] = BrowserManager()
    return _sessions[session_id]

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
