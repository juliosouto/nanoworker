import json
from ddgs import DDGS
from utils.security_utils import require_permission

@require_permission('PERM_WEB_SEARCH')
def search_web(query: str, max_results: int = 5) -> str:
    """
    Performs a web search using DuckDuckGo and returns the results.
    
    Args:
        query: The search term to query on the web.
        max_results: The maximum number of results to return (default is 5).
        
    Returns:
        A JSON string containing a list of search results, where each result 
        typically includes a 'title', 'href' (URL), and 'body' (snippet).
        Returns an error message if the search fails.
    """
    try:
        with DDGS() as ddgs:
            results = list(ddgs.text(query, max_results=max_results))
            
            if not results:
                return f"No results found for query: '{query}'"
                
            return json.dumps(results, indent=2, ensure_ascii=False)
            
    except Exception as e:
        return f"Error performing web search for '{query}': {str(e)}"
