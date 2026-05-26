import subprocess

from utils.security_utils import require_permission

@require_permission('PERM_MAIL')
def search_mac_mail(query: str, limit: int = 5) -> str:
    """
    Searches for emails in the macOS Mail app where the sender, subject, or content contains the query.
    
    Args:
        query: The search term (e.g., sender name, email, or subject).
        limit: Maximum number of emails to retrieve.
        
    Returns:
        A formatted string with the emails found or an error message.
    """
    if not query or len(query.strip()) < 2:
        return "Error: Please provide a valid query string (at least 2 characters) or use get_recent_mac_mail to get recent emails."

    script = f"""
    tell application "Mail"
        set output to ""
        set counter to 0
        set matchedMessages to (messages of inbox whose sender contains "{query}" or subject contains "{query}")
        
        repeat with msg in matchedMessages
            try
                set msgId to id of msg
                set msgSender to sender of msg
                set msgSubject to subject of msg
                set msgDate to date received of msg as string
                
                set output to output & "ID: " & msgId & " | Sender: " & msgSender & " | Date: " & msgDate & " | Subject: " & msgSubject & linefeed
                
                set counter to counter + 1
                if counter >= {limit} then exit repeat
            on error errStr
                set output to output & "Error reading message: " & errStr & linefeed
            end try
        end repeat
        
        if output is "" then
            return "No emails found matching: {query}"
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
            return f"Error searching Mail: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Mail app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"


@require_permission('PERM_MAIL')
def read_mac_mail(message_id: int) -> str:
    """
    Reads the full content of an email from the macOS Mail app using its ID.
    
    Args:
        message_id: The ID of the email to read.
        
    Returns:
        The content of the email or an error message.
    """
    script = f"""
    tell application "Mail"
        try
            set msg to (first message of inbox whose id is {message_id})
            set msgSender to sender of msg
            set msgSubject to subject of msg
            set msgContent to content of msg
            
            return "Sender: " & msgSender & linefeed & "Subject: " & msgSubject & linefeed & "---" & linefeed & msgContent
        on error errStr
            return "Error reading email: " & errStr
        end try
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
            return f"Error reading Mail: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Mail app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"


@require_permission('PERM_MAIL')
def get_recent_mac_mail(limit: int = 5) -> str:
    """
    Retrieves the most recent emails from the macOS Mail app without filtering.
    Use this function when the user asks for the latest/recent emails.
    
    Args:
        limit: Maximum number of recent emails to retrieve.
        
    Returns:
        A formatted string with the recent emails or an error message.
    """
    script = f"""
    tell application "Mail"
        set output to ""
        try
            set recentMessages to (messages 1 thru {limit} of inbox)
            
            repeat with msg in recentMessages
                try
                    set msgId to id of msg
                    set msgSender to sender of msg
                    set msgSubject to subject of msg
                    set msgDate to date received of msg as string
                    
                    set output to output & "ID: " & msgId & " | Sender: " & msgSender & " | Date: " & msgDate & " | Subject: " & msgSubject & linefeed
                on error errStr
                    set output to output & "Error reading message: " & errStr & linefeed
                end try
            end repeat
            
            if output is "" then
                return "No recent emails found."
            else
                return output
            end if
        on error errStr
            return "Error retrieving recent emails: " & errStr
        end try
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
            return f"Error fetching recent Mail: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Mail app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"
