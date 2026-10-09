import requests
import logging

logger = logging.getLogger(__name__)

_original_request = requests.Session.request
_proxy_enabled = False
_current_proxies = None

import os
import requests
from bs4 import BeautifulSoup
import random

def _fetch_working_proxy():
    try:
        res = requests.get('https://free-proxy-list.net/', timeout=10)
        soup = BeautifulSoup(res.text, 'html.parser')
        proxies = []
        for row in soup.find('table').find_all('tr')[1:]:
            cols = row.find_all('td')
            if len(cols) >= 8 and cols[6].text == 'yes': # HTTPS support
                ip = cols[0].text
                port = cols[1].text
                proxies.append(f"http://{ip}:{port}")
        
        random.shuffle(proxies)
        for proxy in proxies[:5]:
            try:
                # Test the proxy
                test_res = requests.get('https://api.ipify.org', proxies={'http': proxy, 'https': proxy}, timeout=5)
                if test_res.status_code == 200:
                    return proxy
            except Exception:
                continue
    except Exception as e:
        logger.error(f"Error scraping proxies: {e}")
    return None

def enable_proxy():
    """Habilita o proxy global, buscando um novo proxy aleatório."""
    global _proxy_enabled, _current_proxies
    try:
        logger.info("Buscando um proxy gratuito disponível (custom fetcher)...")
        proxy = _fetch_working_proxy()
        if not proxy:
            raise Exception("Nenhum proxy funcionando encontrado.")
            
        _current_proxies = {'http': proxy, 'https': proxy}
        _proxy_enabled = True
        
        # Patch urllib
        import urllib.request
        proxy_support = urllib.request.ProxyHandler(_current_proxies)
        opener = urllib.request.build_opener(proxy_support)
        urllib.request.install_opener(opener)
        
        # Set NO_PROXY environment variable for urllib and native libs
        os.environ['NO_PROXY'] = ",".join(EXCLUDED_DOMAINS)
        os.environ['no_proxy'] = ",".join(EXCLUDED_DOMAINS)
        
        # Set HTTP_PROXY and HTTPS_PROXY as the ultimate global fallback
        os.environ['HTTP_PROXY'] = proxy
        os.environ['HTTPS_PROXY'] = proxy
        os.environ['http_proxy'] = proxy
        os.environ['https_proxy'] = proxy
        
        logger.info(f"Proxy habilitado: {proxy}")
        return proxy
    except Exception as e:
        logger.error(f"Falha ao obter proxy: {e}")
        return None

def disable_proxy():
    """Desabilita o proxy global."""
    global _proxy_enabled, _current_proxies
    _proxy_enabled = False
    _current_proxies = None
    
    # Restore urllib
    import urllib.request
    urllib.request.install_opener(urllib.request.build_opener())
    
    # Remove NO_PROXY env vars
    os.environ.pop('NO_PROXY', None)
    os.environ.pop('no_proxy', None)
    
    # Remove HTTP_PROXY env vars
    os.environ.pop('HTTP_PROXY', None)
    os.environ.pop('HTTPS_PROXY', None)
    os.environ.pop('http_proxy', None)
    os.environ.pop('https_proxy', None)
    
    logger.info("Proxy desabilitado.")

def status_proxy():
    """Retorna o status atual do proxy."""
    if _proxy_enabled and _current_proxies:
        return f"Active: {_current_proxies['http']}"
    return "Disabled"

def get_current_proxy() -> str | None:
    """Retorna o URL do proxy atual (como string simples) ou None."""
    if _proxy_enabled and _current_proxies:
        return _current_proxies.get('http')
    return None

def get_playwright_proxy_config() -> dict | None:
    """Retorna a configuração completa de proxy para o Playwright, incluindo os bypasses."""
    if _proxy_enabled and _current_proxies:
        return {
            "server": _current_proxies['http'],
            "bypass": ",".join(EXCLUDED_DOMAINS)
        }
    return None

import urllib.parse

EXCLUDED_DOMAINS = (
    '127.0.0.1',
    'localhost',
    'api.openai.com',
    'api.groq.com',
    'integrate.api.nvidia.com',
    'generativelanguage.googleapis.com'
)

def _is_url_excluded(url: str) -> bool:
    try:
        parsed = urllib.parse.urlparse(url)
        hostname = parsed.hostname or ""
        for domain in EXCLUDED_DOMAINS:
            if domain == hostname or hostname.endswith('.' + domain):
                return True
    except Exception:
        pass
    return False

def _patched_request(self, method, url, **kwargs):
    """Método que substitui requests.Session.request para injetar o proxy invisivelmente."""
    global _proxy_enabled, _current_proxies
    
    if _proxy_enabled and _current_proxies and not _is_url_excluded(url):
        # Só injeta se a requisição não definiu um proxy próprio
        if 'proxies' not in kwargs or not kwargs['proxies']:
            kwargs['proxies'] = _current_proxies
            
    return _original_request(self, method, url, **kwargs)

# Variável para o original do curl_cffi
_original_curl_request = None
_original_curl_async_request = None
try:
    import curl_cffi.requests
    _original_curl_request = curl_cffi.requests.Session.request
    if hasattr(curl_cffi.requests, 'AsyncSession'):
        _original_curl_async_request = curl_cffi.requests.AsyncSession.request
except ImportError:
    pass

def _patched_curl_request(self, method, url, **kwargs):
    global _proxy_enabled, _current_proxies
    if _proxy_enabled and _current_proxies and not _is_url_excluded(url):
        if 'proxies' not in kwargs or not kwargs['proxies']:
            kwargs['proxies'] = _current_proxies
    return _original_curl_request(self, method, url, **kwargs)

async def _patched_curl_async_request(self, method, url, **kwargs):
    global _proxy_enabled, _current_proxies
    if _proxy_enabled and _current_proxies and not _is_url_excluded(url):
        if 'proxies' not in kwargs or not kwargs['proxies']:
            kwargs['proxies'] = _current_proxies
    return await _original_curl_async_request(self, method, url, **kwargs)

def setup_global_proxy():
    """Inicia o monkey-patching do requests no boot."""
    requests.Session.request = _patched_request
    if _original_curl_request:
        curl_cffi.requests.Session.request = _patched_curl_request
    if _original_curl_async_request:
        curl_cffi.requests.AsyncSession.request = _patched_curl_async_request
    logger.info("Proxy Monkey-Patch ativado globalmente no requests (e curl_cffi se disponível).")

