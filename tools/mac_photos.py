import subprocess
import os
from utils.security_utils import require_permission

@require_permission('PERM_PHOTOS')
def get_recent_photos(limit: int = 5) -> str:
    """
    Retrieves the metadata (ID, filename, date) of the most recent photos from the macOS Photos app.
    
    Args:
        limit: Number of recent photos to retrieve.
        
    Returns:
        A formatted string with the recent photos' metadata or an error message.
    """
    script = f"""
    tell application "Photos"
        set allItems to media items
        set totalCount to count of allItems
        set limitNum to {limit}
        if totalCount < limitNum then set limitNum to totalCount
        if totalCount = 0 then return "No photos found in library."
        
        set startIdx to totalCount - limitNum + 1
        set output to ""
        
        repeat with i from startIdx to totalCount
            try
                set currentItem to item i of allItems
                set itemName to filename of currentItem
                set itemID to id of currentItem
                set itemDate to date of currentItem
                set output to output & "ID: " & itemID & " | Name: " & itemName & " | Date: " & itemDate & linefeed
            end try
        end repeat
        
        if output is "" then
            return "No recent photos retrieved."
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
            return f"Error accessing Photos: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Photos app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"

@require_permission('PERM_PHOTOS')
def list_albums() -> str:
    """
    Lists all albums in the macOS Photos app.
    
    Returns:
        A formatted string with the albums' names and IDs or an error message.
    """
    script = """
    tell application "Photos"
        set allAlbums to albums
        set output to ""
        repeat with a in allAlbums
            try
                set albumName to name of a
                set albumID to id of a
                set output to output & "Album: " & albumName & " | ID: " & albumID & linefeed
            end try
        end repeat
        if output is "" then
            return "No albums found."
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
            return f"Error accessing Photos: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Photos app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"

@require_permission('PERM_PHOTOS')
def export_photos(photo_ids: list[str], destination_path: str) -> str:
    """
    Exports photos from the macOS Photos app to a specific local directory.
    
    Args:
        photo_ids: List of photo IDs to export.
        destination_path: The absolute path of the directory to export the photos to.
        
    Returns:
        A success message or an error message.
    """
    if not os.path.exists(destination_path):
        try:
            os.makedirs(destination_path, exist_ok=True)
        except Exception as e:
            return f"Error creating destination directory: {e}"
            
    if not photo_ids:
        return "Error: No photo IDs provided for export."

    # Build AppleScript array of IDs
    ids_str = ", ".join([f'"{pid}"' for pid in photo_ids])
    
    script = f"""
    set exportFolder to POSIX file "{destination_path}" as alias
    set targetIds to {{{ids_str}}}
    set exportCount to 0
    
    tell application "Photos"
        set allMedia to media items
        set targetMedia to {{}}
        
        -- AppleScript filtering by a list of IDs can be tricky, so we iterate
        repeat with pId in targetIds
            try
                set foundItem to (first media item whose id is pId)
                set end of targetMedia to foundItem
            end try
        end repeat
        
        if (count of targetMedia) > 0 then
            export targetMedia to exportFolder
            set exportCount to (count of targetMedia)
        end if
    end tell
    
    return "Exported " & exportCount & " photos successfully to {destination_path}."
    """
    
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True,
            text=True,
            timeout=60
        )
        if result.returncode != 0:
            return f"Error exporting photos: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to export photos timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"

@require_permission('PERM_PHOTOS')
def delete_photos(photo_ids: list[str]) -> str:
    """
    Deletes photos from the macOS Photos app.
    NOTE: Currently disabled for safety.
    
    Args:
        photo_ids: List of photo IDs to delete.
        
    Returns:
        A message indicating success, failure, or that the feature is disabled.
    """
    # DELETION IS DISABLED FOR SAFETY
    DELETE_ENABLED = False
    
    if not DELETE_ENABLED:
        return "Error: Photo deletion is currently disabled for safety reasons."
        
    if not photo_ids:
        return "Error: No photo IDs provided for deletion."
        
    ids_str = ", ".join([f'"{pid}"' for pid in photo_ids])
    
    script = f"""
    set targetIds to {{{ids_str}}}
    set deleteCount to 0
    
    tell application "Photos"
        repeat with pId in targetIds
            try
                set foundItem to (first media item whose id is pId)
                delete foundItem
                set deleteCount to deleteCount + 1
            end try
        end repeat
    end tell
    
    return "Deleted " & deleteCount & " photos successfully."
    """
    
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            return f"Error deleting photos: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to delete photos timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"
