import subprocess
from datetime import datetime
from utils.security_utils import require_permission

@require_permission('PERM_CALENDAR')
def get_mac_calendar_events(days_ahead: int = 1) -> str:
    """
    Retrieves events from the macOS Calendar app for today and the given number of days ahead.
    
    Args:
        days_ahead: Number of days to look ahead (0 for today only, 1 for today and tomorrow, etc.).
        
    Returns:
        A formatted string with the calendar events or an error message.
    """
    days = max(0, days_ahead)
    script = f"""
    tell application "Calendar"
        set startDate to current date
        set time of startDate to 0
        set endDate to startDate + (({days} + 1) * days)
        set output to ""
        repeat with c in calendars
            try
                set cName to name of c
                set cEvents to (every event of c whose start date is greater than or equal to startDate and start date is less than endDate)
                repeat with e in cEvents
                    set eSum to summary of e
                    set eStart to start date of e
                    set eEnd to end date of e
                    set output to output & "Calendar: " & cName & " | Event: " & eSum & " | Start: " & eStart & " | End: " & eEnd & linefeed
                end repeat
            end try
        end repeat
        if output is "" then
            return "No events found."
        else
            return output
        end if
    end tell
    """
    
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            return f"Error accessing Calendar: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Calendar app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"


@require_permission('PERM_CALENDAR')
def create_mac_calendar_event(calendar_name: str, summary: str, start_time: str, end_time: str) -> str:
    """
    Creates a new event in a specified macOS Calendar.
    
    Args:
        calendar_name: The exact name of the calendar (e.g., 'Work', 'Home').
        summary: The title or summary of the event.
        start_time: ISO 8601 formatted string for start time (e.g., '2026-05-21T10:00:00').
        end_time: ISO 8601 formatted string for end time (e.g., '2026-05-21T11:00:00').
        
    Returns:
        Success or error message.
    """
    try:
        start_dt = datetime.fromisoformat(start_time.replace("Z", "+00:00"))
        end_dt = datetime.fromisoformat(end_time.replace("Z", "+00:00"))
    except ValueError as e:
        return f"Error parsing dates: {e}. Please use ISO 8601 format (e.g., '2026-05-21T10:00:00')."
        
    script = f"""
    set startDt to current date
    set year of startDt to {start_dt.year}
    set month of startDt to {start_dt.month}
    set day of startDt to {start_dt.day}
    set hours of startDt to {start_dt.hour}
    set minutes of startDt to {start_dt.minute}
    set seconds of startDt to {start_dt.second}
    
    set endDt to current date
    set year of endDt to {end_dt.year}
    set month of endDt to {end_dt.month}
    set day of endDt to {end_dt.day}
    set hours of endDt to {end_dt.hour}
    set minutes of endDt to {end_dt.minute}
    set seconds of endDt to {end_dt.second}
    
    tell application "Calendar"
        try
            set targetCalendar to calendar "{calendar_name}"
        on error
            return "Error: Calendar '{calendar_name}' not found."
        end try
        
        tell targetCalendar
            make new event with properties {{summary:"{summary}", start date:startDt, end date:endDt}}
        end tell
    end tell
    return "Event created successfully in '{calendar_name}' calendar."
    """
    
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            return f"Error creating event: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Calendar app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"
