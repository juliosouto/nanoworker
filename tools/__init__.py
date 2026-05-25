from database import get_config
from utils.file_utils import read_file, write_file

from .bash import run_bash_command
from .browser import (
    browser_click,
    browser_extract,
    browser_fill,
    browser_navigate,
    browser_run_js,
    browser_snapshot,
)
from .mac_calendar import create_mac_calendar_event, get_mac_calendar_events
from .mac_contacts import create_mac_contact, get_mac_contacts, search_mac_contacts
from .mac_icloud import list_icloud_files, read_icloud_file, write_icloud_file
from .mac_mail import get_recent_mac_mail, read_mac_mail, search_mac_mail
from .mac_notes import append_to_mac_note, create_mac_note, list_mac_notes, read_mac_note
from .mac_photos import delete_photos, export_photos, get_recent_photos, list_albums
from .mac_reminders import (
    complete_mac_reminder,
    create_mac_reminder,
    delete_mac_reminder,
    list_mac_reminders,
)
from .mac_screenshot import take_mac_screenshot
from .scheduling import delete_scheduled_task, list_scheduled_tasks, schedule_task
from .web_scraper import extract_webpage_text
from .web_search import search_web
from .whatsapp import send_whatsapp_file, send_whatsapp_message

def get_permitted_tools():
    """Returns a list of tools filtered by the user's permissions."""
    tools = [
        send_whatsapp_message, send_whatsapp_file, schedule_task, 
        list_scheduled_tasks, delete_scheduled_task
    ]
    
    if get_config('PERM_FS', 'false').lower() == 'true':
        tools.extend([read_file, write_file])
        
    if get_config('PERM_TERMINAL', 'false').lower() == 'true':
        tools.append(run_bash_command)

    if get_config('PERM_WEB_SEARCH', 'false').lower() == 'true':
        tools.append(search_web)
        
    if get_config('PERM_PLAYWRIGHT', 'false').lower() == 'true':
        tools.extend([
            browser_navigate, browser_snapshot, browser_click,
            browser_fill, browser_extract, browser_run_js
        ])
        
    if get_config('PERM_SAFARI', 'false').lower() == 'true':
        pass # Placeholder for Safari specific tools
        
    if get_config('PERM_CALENDAR', 'false').lower() == 'true':
        tools.extend([get_mac_calendar_events, create_mac_calendar_event])
        
    if get_config('PERM_CONTACTS', 'false').lower() == 'true':
        tools.extend([get_mac_contacts, search_mac_contacts, create_mac_contact])
        
    if get_config('PERM_PHOTOS', 'false').lower() == 'true':
        tools.extend([get_recent_photos, list_albums, export_photos, delete_photos])
        
    if get_config('PERM_ICLOUD', 'false').lower() == 'true':
        tools.extend([list_icloud_files, read_icloud_file, write_icloud_file])
        
    if get_config('PERM_NOTES', 'false').lower() == 'true':
        tools.extend([list_mac_notes, read_mac_note, create_mac_note, append_to_mac_note])
        
    if get_config('PERM_REMINDERS', 'false').lower() == 'true':
        tools.extend([list_mac_reminders, create_mac_reminder, complete_mac_reminder, delete_mac_reminder])
        
    if get_config('PERM_SCREENSHOT', 'false').lower() == 'true':
        tools.append(take_mac_screenshot)
        
    if get_config('PERM_MAIL', 'false').lower() == 'true':
        tools.extend([search_mac_mail, read_mac_mail, get_recent_mac_mail])
    
    return tools

# Keep AVAILABLE_TOOLS for backwards compatibility or full access if needed elsewhere
AVAILABLE_TOOLS = [
    read_file, write_file, run_bash_command, send_whatsapp_message, send_whatsapp_file, extract_webpage_text,
    browser_navigate, browser_snapshot, browser_click, browser_fill, browser_extract, browser_run_js,
    schedule_task, list_scheduled_tasks, delete_scheduled_task, get_mac_calendar_events, create_mac_calendar_event, get_mac_contacts, search_mac_contacts,
    create_mac_contact, get_recent_photos, list_albums, export_photos, delete_photos,
    list_icloud_files, read_icloud_file, write_icloud_file, list_mac_notes, read_mac_note,
    create_mac_note, append_to_mac_note, list_mac_reminders, create_mac_reminder, complete_mac_reminder, delete_mac_reminder,
    take_mac_screenshot, search_mac_mail, read_mac_mail, get_recent_mac_mail, search_web
]
