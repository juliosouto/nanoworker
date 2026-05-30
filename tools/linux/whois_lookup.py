import json
import urllib.request
import urllib.error
from utils.security_utils import require_permission


def get_whois_rdap(domain: str) -> str:
    """
    Fetches WHOIS registration data using the RDAP protocol via rdap.org.
    
    Args:
        domain: The domain to look up (e.g., 'google.com').
    
    Returns:
        A JSON string containing the full RDAP response data, or an error message if the lookup fails.
    """
    url = f"https://rdap.org/domain/{domain}"
    
    req = urllib.request.Request(url, headers={'Accept': 'application/rdap+json', 'User-Agent': 'Mozilla/5.0'})
    
    try:
        with urllib.request.urlopen(req) as response:
            data = response.read().decode('utf-8')
            parsed_data = json.loads(data)
            return json.dumps(parsed_data, indent=2, ensure_ascii=False)
    except urllib.error.HTTPError as e:
        return f"HTTP Error performing WHOIS RDAP lookup for '{domain}': {e.code} {e.reason}"
    except Exception as e:
        return f"Error performing WHOIS RDAP lookup for '{domain}': {str(e)}"
