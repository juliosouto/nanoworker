import logging
import threading
import time
from playwright.sync_api import sync_playwright

logger = logging.getLogger(__name__)

class GlobalBrowser:
    """Singleton for the Playwright Chromium instance"""
    _instance = None
    _lock = threading.Lock()
    
    @classmethod
    def get_instance(cls):
        with cls._lock:
            if cls._instance is None:
                cls._instance = cls()
            return cls._instance
            
    def __init__(self):
        self.playwright = sync_playwright().start()
        
        launch_options = {
            "headless": True,
            "args": [
                "--disable-blink-features=AutomationControlled", 
                "--disable-extensions",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "--viewport=1920x1080",
                "--permissions=geolocation,notifications",
                "--geolocation",
                "--notifications",
                "--color-scheme=dark",
                "--ignore-https-errors",
                "--java-script-enabled",
                "--bypass-csp",
                "--disable-remote-fonts",
            ]
        }
        self.browser = self.playwright.chromium.launch(**launch_options)

    def new_context(self, **kwargs):
        return self.browser.new_context(**kwargs)

class BrowserManager:
    def __init__(self):
        self.context = None
        self.page = None
        self.last_activity = time.time()
        self.relaunch_custom_config()

    def update_activity(self):
        self.last_activity = time.time()

    def start_browser(self, storage_state=None, headless=True, proxy=None, user_agent=None, browser_args=None, launch_kwargs=None, **context_kwargs):
        """
        Configura e inicializa um context e page. O browser pesado é compartilhado.
        Se já houver um context aberto, ele será fechado e reiniciado.
        """
        if self.context:
            self.close()

        global_browser = GlobalBrowser.get_instance()
        
        context_options = context_kwargs
        if storage_state:
            context_options["storage_state"] = storage_state
        if user_agent:
            context_options["user_agent"] = user_agent
            
        # Opcionalmente tratar proxy aqui se necessário, 
        # embora o ideal para proxy global fosse na launch option. 
        # O Playwright suporta proxy por context a partir de algumas versões.
        if proxy:
            context_options["proxy"] = proxy
            
        self.context = global_browser.new_context(**context_options)
        self.page = self.context.new_page()

    def relaunch_custom_config(self):
        self.start_browser(
            # Configurações de Contexto (Context / Page)
            # ... (você pode adicionar storage_state, user_agent, locale, timezone_id, etc aqui)
        )

    def navigate(self, url):
        self.update_activity()
        try:
            self.page.goto(url, wait_until="domcontentloaded", timeout=30000)
            try:
                self.page.wait_for_load_state("networkidle", timeout=10000)
            except Exception:
                pass
            return f"Navigated to {url}"
        except Exception as e:
            return f"Error navigating to {url}: {e}"

    def get_snapshot(self, interactive_only=True):
        self.update_activity()
        js_code = """
        () => {
            let interactables = document.querySelectorAll('button, a, input, select, textarea, [role="button"], [tabindex], [role="link"], [role="checkbox"], [role="menuitem"]');
            let result = [];
            let counter = 1;
            interactables.forEach(el => {
                const style = window.getComputedStyle(el);
                if (style.display === 'none' || style.visibility === 'hidden' || style.opacity === '0') return;
                const rect = el.getBoundingClientRect();
                if (rect.width === 0 || rect.height === 0) return;
                
                let ref = '@e' + counter;
                counter++;
                el.setAttribute('data-browser-ref', ref);
                
                let label = el.innerText || el.value || el.getAttribute('aria-label') || el.getAttribute('placeholder') || '';
                label = label.trim().replace(/\\n/g, ' ').substring(0, 50);
                
                let tag = el.tagName.toLowerCase();
                let type = el.getAttribute('type');
                let desc = type ? `${tag}[type=${type}]` : tag;
                
                result.push(`[${ref}] ${desc} "${label}"`);
            });
            return result.join('\\n');
        }
        """
        try:
            res = self.page.evaluate(js_code)
            if not res:
                return "No interactive elements found."
            return res
        except Exception as e:
            return f"Error generating snapshot: {e}"

    def click(self, ref_id):
        self.update_activity()
        try:
            selector = f'[data-browser-ref="{ref_id}"]'
            self.page.locator(selector).first.scroll_into_view_if_needed()
            self.page.locator(selector).first.click(timeout=5000)
            self.page.wait_for_timeout(1000)
            return f"Clicked on {ref_id}"
        except Exception as e:
            return f"Error clicking {ref_id}: {e}"

    def fill(self, ref_id, text):
        self.update_activity()
        try:
            selector = f'[data-browser-ref="{ref_id}"]'
            self.page.locator(selector).first.scroll_into_view_if_needed()
            self.page.locator(selector).first.fill(text, timeout=5000)
            return f"Filled {ref_id} with '{text}'"
        except Exception as e:
            return f"Error filling {ref_id}: {e}"

    def extract(self, ref_id, property_name):
        self.update_activity()
        try:
            selector = f'[data-browser-ref="{ref_id}"]'
            element = self.page.locator(selector).first
            if property_name.lower() == 'text':
                return element.inner_text()
            elif property_name.lower() == 'html':
                return element.inner_html()
            else:
                return element.get_attribute(property_name)
        except Exception as e:
            return f"Error extracting {property_name} from {ref_id}: {e}"

    def run_js(self, script):
        self.update_activity()
        try:
            res = self.page.evaluate(script)
            return str(res)
        except Exception as e:
            return f"Error executing JS: {e}"

    def take_screenshot(self, path):
        self.update_activity()
        try:
            self.page.screenshot(path=path)
            return f"Screenshot saved to {path}"
        except Exception as e:
            return f"Error taking screenshot: {e}"

    def get_cookies(self):
        self.update_activity()
        return self.context.cookies()

    def add_cookies(self, cookies):
        self.update_activity()
        self.context.add_cookies(cookies)

    def save_state(self, path):
        self.update_activity()
        self.context.storage_state(path=path)

    def close(self):
        try:
            if self.page:
                self.page.close()
            if self.context:
                self.context.close()
        except Exception:
            pass
        finally:
            self.page = None
            self.context = None


# --- Gerenciamento Centralizado de Sessões ---

_sessions = {}
_sessions_lock = threading.Lock()
_cleanup_thread_started = False

def _cleanup_idle_sessions():
    idle_timeout = 600  # 10 minutos
    while True:
        try:
            time.sleep(60)
            now = time.time()
            to_remove = []
            
            with _sessions_lock:
                for sid, bm in _sessions.items():
                    if (now - bm.last_activity) > idle_timeout:
                        to_remove.append(sid)
                        
                for sid in to_remove:
                    logger.info(f"Closing idle BrowserManager for session {sid}")
                    bm = _sessions.pop(sid)
                    try:
                        bm.close()
                    except Exception as e:
                        logger.error(f"Error closing BrowserManager for {sid}: {e}")
        except Exception as e:
            logger.error(f"Error in BrowserManager cleanup thread: {e}")

def get_session_browser(session_id: str) -> BrowserManager:
    global _cleanup_thread_started
    
    with _sessions_lock:
        if not _cleanup_thread_started:
            t = threading.Thread(target=_cleanup_idle_sessions, daemon=True)
            t.start()
            _cleanup_thread_started = True
            
        if session_id not in _sessions:
            logger.info(f"Creating new BrowserManager for session {session_id}")
            _sessions[session_id] = BrowserManager()
        else:
            _sessions[session_id].update_activity()
            
        return _sessions[session_id]
