from playwright.sync_api import sync_playwright

class BrowserManager:
    def __init__(self):
        self.playwright = None
        self.browser = None
        self.context = None
        self.page = None
        self.relaunch_custom_config()

    def start_browser(self, storage_state=None, headless=True, proxy=None, user_agent=None, browser_args=None, launch_kwargs=None, **context_kwargs):
        """
        Configura e inicializa o browser com os parâmetros especificados.
        Se já houver um browser aberto, ele será fechado e reiniciado.
        """
        if self.playwright:
            self.close()

        self.playwright = sync_playwright().start()
        
        # Parâmetros de inicialização do browser (launch)
        launch_options = {"headless": headless}
        if launch_kwargs:
            launch_options.update(launch_kwargs)
        if proxy:
            launch_options["proxy"] = proxy
        if browser_args:
            launch_options["args"] = browser_args

        self.browser = self.playwright.chromium.launch(**launch_options)
        
        # Parâmetros do contexto (context)
        context_options = context_kwargs
        if storage_state:
            context_options["storage_state"] = storage_state
        if user_agent:
            context_options["user_agent"] = user_agent
            
        self.context = self.browser.new_context(**context_options)
        self.page = self.context.new_page()

    def relaunch_custom_config(self):
        """
        Método dedicado para configurar todos os parâmetros do Playwright.
        Basta descomentar/comentar a linha do que você deseja (ou não) alterar.
        """
        self.start_browser(
            # === Configurações de Launch (Browser) ===
            headless=True,
            browser_args=[
                "--disable-blink-features=AutomationControlled", 
                "--disable-extensions",
                "--no-sandbox",
                "--disable-setuid-sandbox",
                "--disable-dev-shm-usage",
                "--user-agent=Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
                "--viewport=1920x1080",
                #"--locale=pt-BR",
                #"--timezone-id=America/Sao_Paulo",
                "--permissions=geolocation,notifications",
                "--geolocation",
                "--notifications",
                "--color-scheme=dark",
                "--ignore-https-errors",
                "--java-script-enabled",
                "--bypass-csp",
                #"--extra-http-headers=Custom-Header:xxxxxxx",
                "--disable-remote-fonts",
            ]
            # browser_args=[
            #     "--no-sandbox",
            #     "--disable-setuid-sandbox",
            #     "--disable-dev-shm-usage",
            #     "--disable-gpu",
            #     "--disable-blink-features=AutomationControlled"
            # ],
            # proxy={
            #     "server": "http://meu-proxy:3128",
            #     "username": "usuario",
            #     "password": "senha"
            # },
            # launch_kwargs={
            #     "executable_path": "/caminho/para/chrome",
            #     "timeout": 30000,
            #     "slow_mo": 50,
            # },
            
            # === Configurações de Contexto (Context / Page) ===
            # user_agent="Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36",
            # storage_state="auth.json",
            # viewport={"width": 1920, "height": 1080},
            # locale="pt-BR",
            # timezone_id="America/Sao_Paulo",
            # permissions=["geolocation", "notifications"],
            # geolocation={"latitude": -23.5505, "longitude": -46.6333},
            # color_scheme="dark",
            # ignore_https_errors=True,
            # java_script_enabled=True,
            # bypass_csp=True,
            # extra_http_headers={"Custom-Header": "Valor-Aqui"}
        )

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
