import platform
from database import get_config
from utils.file_utils import read_file, write_file
from .macos.memory import manage_persistent_memory

OS_PLATFORM = platform.system()

if OS_PLATFORM == "Windows":
    from .windows.cmd import run_windows_command
    from .windows.browser import (
        browser_click, browser_extract, browser_fill,
        browser_navigate, browser_run_js, browser_snapshot,
    )
    from .windows.windows_screenshot import take_windows_screenshot
    from .windows.scheduling import delete_scheduled_task, list_scheduled_tasks, schedule_task
    from .windows.web_scraper import extract_webpage_text
    from .windows.web_search import search_web
    from .windows.whatsapp import send_whatsapp_file, send_whatsapp_message
    from .windows.tool_creator import create_self_developed_tool
    from .windows.binance_crypto_price import get_binance_crypto_price
    from .windows.get_currency_or_metal_price import get_currency_or_metal_price
else:
    from .macos.bash import run_bash_command
    from .macos.browser import (
        browser_click, browser_extract, browser_fill,
        browser_navigate, browser_run_js, browser_snapshot,
    )
    from .macos.mac_calendar import create_mac_calendar_event, get_mac_calendar_events
    from .macos.mac_contacts import create_mac_contact, get_mac_contacts, search_mac_contacts
    from .macos.mac_icloud import list_icloud_files, read_icloud_file, write_icloud_file
    from .macos.mac_mail import get_recent_mac_mail, read_mac_mail, search_mac_mail
    from .macos.mac_notes import append_to_mac_note, create_mac_note, list_mac_notes, read_mac_note
    from .macos.mac_photos import delete_photos, export_photos, get_recent_photos, list_albums
    from .macos.mac_reminders import (
        complete_mac_reminder, create_mac_reminder, delete_mac_reminder, list_mac_reminders,
    )
    from .macos.mac_screenshot import take_mac_screenshot
    from .macos.scheduling import delete_scheduled_task, list_scheduled_tasks, schedule_task
    from .macos.web_scraper import extract_webpage_text
    from .macos.web_search import search_web
    from .macos.whatsapp import send_whatsapp_file, send_whatsapp_message
    
    if OS_PLATFORM == "Linux":
        from .linux.tool_creator import create_self_developed_tool
        from .linux.binance_crypto_price import get_binance_crypto_price
        from .linux.get_currency_or_metal_price import get_currency_or_metal_price
    else:
        from .macos.tool_creator import create_self_developed_tool
        from .macos.binance_crypto_price import get_binance_crypto_price
        from .macos.get_currency_or_metal_price import get_currency_or_metal_price

def get_permitted_tools():
    """Returns a list of tools filtered by the user's specific tool settings."""
    tools = []
    import sys
    import os
    
    for tool_func in list(AVAILABLE_TOOLS):
        # Verify self-developed tool file still exists
        mod_name = getattr(tool_func, '__module__', '')
        if 'self_developed' in mod_name or 'self-developed' in mod_name:
            if mod_name in sys.modules:
                module = sys.modules[mod_name]
                if hasattr(module, '__file__') and module.__file__:
                    if not os.path.exists(module.__file__):
                        AVAILABLE_TOOLS.remove(tool_func)
                        continue

        tool_name = tool_func.__name__
        # Se for verdadeiro (default = 'true'), a ferramenta é disponibilizada
        if get_config(f'TOOL_{tool_name.upper()}', 'true').lower() == 'true':
            tools.append(tool_func)
            
    return tools

# Keep AVAILABLE_TOOLS for backwards compatibility or full access if needed elsewhere
AVAILABLE_TOOLS = [
    read_file, write_file, send_whatsapp_message, send_whatsapp_file, extract_webpage_text,
    browser_navigate, browser_snapshot, browser_click, browser_fill, browser_extract, browser_run_js,
    schedule_task, list_scheduled_tasks, delete_scheduled_task, search_web, manage_persistent_memory,
    create_self_developed_tool, get_binance_crypto_price, get_currency_or_metal_price
]

if OS_PLATFORM == "Windows":
    AVAILABLE_TOOLS.extend([run_windows_command, take_windows_screenshot])
else:
    AVAILABLE_TOOLS.extend([
        run_bash_command, get_mac_calendar_events, create_mac_calendar_event, get_mac_contacts, search_mac_contacts,
        create_mac_contact, get_recent_photos, list_albums, export_photos, delete_photos,
        list_icloud_files, read_icloud_file, write_icloud_file, list_mac_notes, read_mac_note,
        create_mac_note, append_to_mac_note, list_mac_reminders, create_mac_reminder, complete_mac_reminder, delete_mac_reminder,
        take_mac_screenshot, search_mac_mail, read_mac_mail, get_recent_mac_mail
    ])

try:
    import importlib
    if OS_PLATFORM == "Windows":
        mod = importlib.import_module('tools.self-developed.windows')
    elif OS_PLATFORM == "Linux":
        mod = importlib.import_module('tools.self-developed.linux')
    else:
        mod = importlib.import_module('tools.self-developed.macos')
    
    AVAILABLE_TOOLS.extend(mod.AVAILABLE_SELF_DEVELOPED_TOOLS)
except Exception:
    pass
