import subprocess

def list_mac_reminders(list_name: str = None) -> str:
    """
    Lists active reminders from the macOS Reminders app.
    
    Args:
        list_name: Optional name of the list to filter reminders from.
    """
    if list_name:
        safe_list = list_name.replace('"', '\\"').replace('\\', '\\\\')
        script = f"""
        tell application "Reminders"
            try
                set targetList to list "{safe_list}"
            on error
                return "Error: List '{safe_list}' not found."
            end try
            
            set output to ""
            repeat with r in (reminders of targetList whose completed is false)
                set rName to name of r
                set output to output & "- " & rName & linefeed
            end repeat
            
            if output is "" then
                return "No active reminders found in list '{safe_list}'."
            else
                return output
            end if
        end tell
        """
    else:
        script = """
        tell application "Reminders"
            set output to ""
            repeat with l in lists
                set lName to name of l
                repeat with r in (reminders of l whose completed is false)
                    set rName to name of r
                    set output to output & "List: " & lName & " | Reminder: " & rName & linefeed
                end repeat
            end repeat
            if output is "" then
                return "No active reminders found."
            else
                return output
            end if
        end tell
        """

    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return f"Error accessing Reminders: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Reminders app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"

def create_mac_reminder(name: str, notes: str = None, list_name: str = None) -> str:
    """
    Creates a new reminder in the macOS Reminders app.
    """
    safe_name = name.replace('"', '\\"').replace('\\', '\\\\')
    
    notes_prop = ""
    if notes:
        safe_notes = notes.replace('"', '\\"').replace('\\', '\\\\')
        notes_prop = f', body:"{safe_notes}"'
        
    if list_name:
        safe_list = list_name.replace('"', '\\"').replace('\\', '\\\\')
        script = f"""
        tell application "Reminders"
            try
                set targetList to list "{safe_list}"
            on error
                return "Error: List '{safe_list}' not found."
            end try
            make new reminder at end of targetList with properties {{name:"{safe_name}"{notes_prop}}}
            return "Reminder '{safe_name}' created successfully in list '{safe_list}'."
        end tell
        """
    else:
        script = f"""
        tell application "Reminders"
            make new reminder with properties {{name:"{safe_name}"{notes_prop}}}
            return "Reminder '{safe_name}' created successfully in default list."
        end tell
        """
        
    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return f"Error creating Reminder: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Reminders app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"

def complete_mac_reminder(name: str, list_name: str = None) -> str:
    """
    Marks a reminder as completed in the macOS Reminders app.
    """
    safe_name = name.replace('"', '\\"').replace('\\', '\\\\')
    
    if list_name:
        safe_list = list_name.replace('"', '\\"').replace('\\', '\\\\')
        script = f"""
        tell application "Reminders"
            try
                set targetList to list "{safe_list}"
                set targetReminder to first reminder of targetList whose name is "{safe_name}" and completed is false
                set completed of targetReminder to true
                return "Reminder '{safe_name}' completed successfully."
            on error
                return "Error: Active reminder '{safe_name}' not found in list '{safe_list}'."
            end try
        end tell
        """
    else:
        script = f"""
        tell application "Reminders"
            try
                set targetReminder to first reminder whose name is "{safe_name}" and completed is false
                set completed of targetReminder to true
                return "Reminder '{safe_name}' completed successfully."
            on error
                return "Error: Active reminder '{safe_name}' not found."
            end try
        end tell
        """
        
    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return f"Error completing Reminder: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Reminders app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"

def delete_mac_reminder(name: str, list_name: str = None) -> str:
    """
    Deletes a reminder from the macOS Reminders app.
    """
    safe_name = name.replace('"', '\\"').replace('\\', '\\\\')
    
    if list_name:
        safe_list = list_name.replace('"', '\\"').replace('\\', '\\\\')
        script = f"""
        tell application "Reminders"
            try
                set targetList to list "{safe_list}"
                set targetReminder to first reminder of targetList whose name is "{safe_name}"
                delete targetReminder
                return "Reminder '{safe_name}' deleted successfully."
            on error
                return "Error: Reminder '{safe_name}' not found in list '{safe_list}'."
            end try
        end tell
        """
    else:
        script = f"""
        tell application "Reminders"
            try
                set targetReminder to first reminder whose name is "{safe_name}"
                delete targetReminder
                return "Reminder '{safe_name}' deleted successfully."
            on error
                return "Error: Reminder '{safe_name}' not found."
            end try
        end tell
        """
        
    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return f"Error deleting Reminder: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Reminders app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"
