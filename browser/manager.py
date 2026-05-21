from playwright.sync_api import sync_playwright

class BrowserManager:
    def __init__(self, storage_state=None):
        self.playwright = sync_playwright().start()
        self.browser = self.playwright.chromium.launch(headless=True)
        self.context = self.browser.new_context(storage_state=storage_state)
        self.page = self.context.new_page()

    def navigate(self, url):
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
        try:
            selector = f'[data-browser-ref="{ref_id}"]'
            self.page.locator(selector).first.scroll_into_view_if_needed()
            self.page.locator(selector).first.click(timeout=5000)
            # wait a bit for navigation or DOM updates
            self.page.wait_for_timeout(1000)
            return f"Clicked on {ref_id}"
        except Exception as e:
            return f"Error clicking {ref_id}: {e}"

    def fill(self, ref_id, text):
        try:
            selector = f'[data-browser-ref="{ref_id}"]'
            self.page.locator(selector).first.scroll_into_view_if_needed()
            self.page.locator(selector).first.fill(text, timeout=5000)
            return f"Filled {ref_id} with '{text}'"
        except Exception as e:
            return f"Error filling {ref_id}: {e}"

    def extract(self, ref_id, property_name):
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
        try:
            res = self.page.evaluate(script)
            return str(res)
        except Exception as e:
            return f"Error executing JS: {e}"

    def take_screenshot(self, path):
        try:
            self.page.screenshot(path=path)
            return f"Screenshot saved to {path}"
        except Exception as e:
            return f"Error taking screenshot: {e}"

    def get_cookies(self):
        return self.context.cookies()

    def add_cookies(self, cookies):
        self.context.add_cookies(cookies)

    def save_state(self, path):
        self.context.storage_state(path=path)

    def close(self):
        try:
            self.browser.close()
            self.playwright.stop()
        except:
            pass
