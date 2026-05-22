import subprocess
from utils.security_utils import require_permission
@require_permission('PERM_CONTACTS')
def get_mac_contacts(limit: int = 20) -> str:
    """
    Retrieves a list of contacts from the macOS Contacts app.
    
    Args:
        limit: Maximum number of contacts to retrieve.
        
    Returns:
        A formatted string with the contacts or an error message.
    """
    script = f"""
    tell application "Contacts"
        set output to ""
        set counter to 0
        set allPeople to every person
        repeat with p in allPeople
            try
                set pName to name of p
                if pName is missing value then set pName to ""
            on error
                set pName to ""
            end try
            
            try
                set pPhones to value of phones of p
                set AppleScript's text item delimiters to ", "
                set pPhonesStr to pPhones as string
                set AppleScript's text item delimiters to ""
            on error
                set pPhonesStr to ""
            end try
            
            try
                set pEmails to value of emails of p
                set AppleScript's text item delimiters to ", "
                set pEmailsStr to pEmails as string
                set AppleScript's text item delimiters to ""
            on error
                set pEmailsStr to ""
            end try
            
            set output to output & "Name: " & pName & " | Phones: " & pPhonesStr & " | Emails: " & pEmailsStr & linefeed
            
            set counter to counter + 1
            if counter >= {limit} then exit repeat
        end repeat
        
        if output is "" then
            return "No contacts found."
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
            return f"Error accessing Contacts: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Contacts app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"


@require_permission('PERM_CONTACTS')
def search_mac_contacts(query: str) -> str:
    """
    Searches for contacts matching the query by name or organization.
    
    Args:
        query: The search term.
        
    Returns:
        A formatted string with the matched contacts or an error message.
    """
    script = f"""
    tell application "Contacts"
        set output to ""
        set matchedPeople to (every person whose name contains "{query}" or organization contains "{query}")
        repeat with p in matchedPeople
            try
                set pName to name of p
                if pName is missing value then set pName to ""
            on error
                set pName to ""
            end try
            
            try
                set pPhones to value of phones of p
                set AppleScript's text item delimiters to ", "
                set pPhonesStr to pPhones as string
                set AppleScript's text item delimiters to ""
            on error
                set pPhonesStr to ""
            end try
            
            try
                set pEmails to value of emails of p
                set AppleScript's text item delimiters to ", "
                set pEmailsStr to pEmails as string
                set AppleScript's text item delimiters to ""
            on error
                set pEmailsStr to ""
            end try
            
            set output to output & "Name: " & pName & " | Phones: " & pPhonesStr & " | Emails: " & pEmailsStr & linefeed
        end repeat
        
        if output is "" then
            return "No contacts found matching: {query}"
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
            return f"Error searching Contacts: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Contacts app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"


@require_permission('PERM_CONTACTS')
def create_mac_contact(first_name: str, last_name: str = "", phone: str = "", email: str = "") -> str:
    """
    Creates a new contact in the macOS Contacts app.
    
    Args:
        first_name: First name of the contact.
        last_name: Last name of the contact (optional).
        phone: Phone number (optional).
        email: Email address (optional).
        
    Returns:
        Success or error message.
    """
    script = f"""
    tell application "Contacts"
        set newPerson to make new person with properties {{first name:"{first_name}", last name:"{last_name}"}}
        if "{phone}" is not "" then
            make new phone at end of phones of newPerson with properties {{label:"Mobile", value:"{phone}"}}
        end if
        if "{email}" is not "" then
            make new email at end of emails of newPerson with properties {{label:"Work", value:"{email}"}}
        end if
        save
    end tell
    return "Contact '{first_name} {last_name}' created successfully."
    """
    
    try:
        result = subprocess.run(
            ['osascript', '-e', script],
            capture_output=True,
            text=True,
            timeout=30
        )
        if result.returncode != 0:
            return f"Error creating contact: {result.stderr.strip()}"
        return result.stdout.strip()
    except subprocess.TimeoutExpired:
        return "Error: Request to Contacts app timed out."
    except Exception as e:
        return f"Error executing AppleScript: {str(e)}"
