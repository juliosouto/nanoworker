import subprocess
from utils.security_utils import require_permission

@require_permission('PERM_NOTES')
def list_mac_notes(folder_name: str = None) -> str:
    """
    Lists notes from the macOS Notes app.
    
    Args:
        folder_name: Optional folder name to filter notes.
    """
    if folder_name:
        script = f"""
        tell application "Notes"
            try
                set targetFolder to folder "{folder_name}"
            on error
                return "Error: Folder '{folder_name}' not found."
            end try
            
            set output to ""
            repeat with n in notes of targetFolder
                set nName to name of n
                set output to output & "- " & nName & linefeed
            end repeat
            
            if output is "" then
                return "No notes found in folder '{folder_name}'."
            else
                return output
            end if
        end tell
        """
    else:
        script = f"""
        tell application "Notes"
            set output to ""
            repeat with f in folders
                set fName to name of f
                repeat with n in notes of f
                    set nName to name of n
                    set output to output & "Folder: " & fName & " | Note: " & nName & linefeed
                end repeat
            end repeat
            if output is "" then
                return "No notes found."
            else
                return output
            end if
        end tell
        """

    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return f"Error accessing Notes: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Notes app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"

@require_permission('PERM_NOTES')
def read_mac_note(note_name: str) -> str:
    """
    Reads the content of a specific note from the macOS Notes app.
    """
    safe_name = note_name.replace('"', '\\"').replace('\\', '\\\\')
    script = f"""
    tell application "Notes"
        try
            set targetNote to first note whose name is "{safe_name}"
            return body of targetNote
        on error
            return "Error: Note '{safe_name}' not found."
        end try
    end tell
    """
    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return f"Error accessing Notes: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Notes app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"

@require_permission('PERM_NOTES')
def create_mac_note(note_name: str, body: str, folder_name: str = None) -> str:
    """
    Creates a new note in the macOS Notes app.
    """
    safe_name = note_name.replace('"', '\\"').replace('\\', '\\\\')
    safe_body = body.replace('"', '\\"').replace('\\', '\\\\')
    
    if folder_name:
        safe_folder = folder_name.replace('"', '\\"').replace('\\', '\\\\')
        script = f"""
        tell application "Notes"
            try
                set targetFolder to folder "{safe_folder}"
            on error
                return "Error: Folder '{safe_folder}' not found."
            end try
            make new note at targetFolder with properties {{name:"{safe_name}", body:"{safe_body}"}}
            return "Note '{safe_name}' created successfully in folder '{safe_folder}'."
        end tell
        """
    else:
        script = f"""
        tell application "Notes"
            make new note with properties {{name:"{safe_name}", body:"{safe_body}"}}
            return "Note '{safe_name}' created successfully."
        end tell
        """
        
    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return f"Error creating Note: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Notes app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"

@require_permission('PERM_NOTES')
def append_to_mac_note(note_name: str, text_to_append: str) -> str:
    """
    Appends text to an existing note in the macOS Notes app.
    """
    safe_name = note_name.replace('"', '\\"').replace('\\', '\\\\')
    safe_text = text_to_append.replace('"', '\\"').replace('\\', '\\\\')
    
    script = f"""
    tell application "Notes"
        try
            set targetNote to first note whose name is "{safe_name}"
            set currentBody to body of targetNote
            set body of targetNote to currentBody & "<br><br>{safe_text}"
            return "Text appended to note '{safe_name}' successfully."
        on error
            return "Error: Note '{safe_name}' not found."
        end try
    end tell
    """
    try:
        result = subprocess.run(['osascript', '-e', script], capture_output=True, text=True, timeout=30)
        if result.returncode != 0:
            return f"Error appending to Note: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Notes app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"
