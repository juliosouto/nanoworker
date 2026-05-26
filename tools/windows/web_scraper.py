import logging

import trafilatura
from curl_cffi import requests
from playwright.sync_api import sync_playwright

def extract_webpage_text(url: str) -> str:
    """
    Extracts the main text content from a web page URL.
    Use this tool whenever the user asks for information from a specific web page.
    """
    try:
        # First attempt: curl_cffi with impersonate
        response = requests.get(url, impersonate="chrome148", timeout=15)
        html = response.text
        text = trafilatura.extract(html)
        
        if text:
            return text
            
        logging.info("Trafilatura failed to extract text with curl_cffi, falling back to Playwright")
    except Exception as e:
        logging.warning(f"curl_cffi request failed for {url}: {e}, falling back to Playwright")
        
    # Fallback: Playwright
    try:
        with sync_playwright() as p:
            browser = p.chromium.launch(headless=True)
            page = browser.new_page()
            page.goto(url, timeout=30000, wait_until="domcontentloaded")
            
            # Wait a bit for dynamic content
            page.wait_for_timeout(2000)
            
            html = page.content()
            text = trafilatura.extract(html)
            
            if not text:
                # If trafilatura still fails, try returning innerText of body
                text = page.locator("body").inner_text()
                
            browser.close()
            
            return text if text else "Failed to extract content from the page."
            
    except Exception as e:
        return f"Error extracting webpage text: {e}"
