from utils.proxy_manager import enable_proxy, disable_proxy, status_proxy

def manage_proxy(action: str) -> str:
    """
    Manages the Global Proxy interceptor that affects all HTTP requests made by the agent.
    Use this to bypass IP blocks, API rate limits, or web scraping blocks.
    
    Args:
        action (str): The desired action. Accepts:
            - 'enable': Fetches a new free proxy, enables it globally, and returns the IP.
            - 'disable': Turns off the proxy and switches back to direct server connection.
            - 'status': Checks which proxy is currently in use.
            
    Returns:
        str: The result of the operation with current proxy information.
    """
    action = action.lower().strip()
    
    if action == 'enable':
        proxy = enable_proxy()
        if proxy:
            return f"Proxy enabled successfully. All future requests will use: {proxy}"
        else:
            return "Failed to fetch and enable a free proxy at this moment."
            
    elif action == 'disable':
        disable_proxy()
        return "Proxy disabled. Requests will now use the direct network."
        
    elif action == 'status':
        status = status_proxy()
        return f"Global Proxy Status: {status}"
        
    else:
        return f"Unknown action: '{action}'. Supported actions: 'enable', 'disable', 'status'."
