from .filesystem import read_file, write_file
from .bash import run_bash_command
from .whatsapp import send_whatsapp_message, send_whatsapp_file
from .browser import (
    browser_navigate,
    browser_snapshot,
    browser_click,
    browser_fill,
    browser_extract,
    browser_run_js
)
from .scheduling import schedule_task
from .mac_calendar import get_mac_calendar_events, create_mac_calendar_event
from .mac_photos import get_recent_photos, list_albums, export_photos, delete_photos
from .mac_icloud import list_icloud_files, read_icloud_file, write_icloud_file
from .mac_notes import list_mac_notes, read_mac_note, create_mac_note, append_to_mac_note
from .mac_reminders import list_mac_reminders, create_mac_reminder, complete_mac_reminder, delete_mac_reminder

# Expose a list of all tools to be injected into the LLM
AVAILABLE_TOOLS = [
    read_file,
    write_file,
    run_bash_command,
    send_whatsapp_message,
    send_whatsapp_file,
    browser_navigate,
    browser_snapshot,
    browser_click,
    browser_fill,
    browser_extract,
    browser_run_js,
    schedule_task,
    get_mac_calendar_events,
    create_mac_calendar_event,
    get_recent_photos,
    list_albums,
    export_photos,
    delete_photos,
    list_icloud_files,
    read_icloud_file,
    write_icloud_file,
    list_mac_notes,
    read_mac_note,
    create_mac_note,
    append_to_mac_note,
    list_mac_reminders,
    create_mac_reminder,
    complete_mac_reminder,
    delete_mac_reminder
]
