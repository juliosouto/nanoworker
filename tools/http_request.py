import ipaddress
import json
import socket
from urllib.parse import urlsplit

from curl_cffi import requests

from utils.security_utils import require_permission

_MAX_BODY_CHARS = 8000
_MAX_RESPONSE_BYTES = 5_000_000
_ALLOWED_METHODS = ("GET", "POST", "PUT", "PATCH", "DELETE", "HEAD")


def _assert_safe_url(url: str) -> str:
    """
    Blocks SSRF-style targets: only http(s) to public hosts. Local, private,
    link-local and reserved addresses (including cloud metadata endpoints) are
    refused.
    """
    parts = urlsplit(url)
    if parts.scheme not in ("http", "https"):
        raise ValueError(f"Scheme '{parts.scheme or 'none'}' not allowed. Use http:// or https://.")

    host = (parts.hostname or "").lower()
    if not host:
        raise ValueError("URL has no hostname.")
    if host in ("localhost", "metadata.google.internal", "metadata.goog") or host.endswith(".local") or host.endswith(".internal"):
        raise ValueError(f"Host '{host}' is internal and blocked.")

    try:
        infos = socket.getaddrinfo(host, None)
    except socket.gaierror as e:
        raise ValueError(f"Could not resolve host '{host}': {e}")

    for info in infos:
        ip = ipaddress.ip_address(info[4][0])
        if ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_reserved or ip.is_multicast:
            raise ValueError(
                f"Host '{host}' resolves to a private/reserved address ({ip}) — blocked for security."
            )
    return url


@require_permission('PERM_WEB_SEARCH')
def http_request(url: str, method: str = "GET", headers: dict = None, body: str = None, json_data: str = None, timeout_seconds: int = 30) -> str:
    """
    Performs a raw HTTP request to any public URL and returns the response status and body.
    Use this tool to call REST APIs, check endpoints or fetch data that web_scraper cannot parse.
    Internal/private addresses (localhost, 10.x, 192.168.x, cloud metadata) are blocked for security.
    
    Args:
        url: The full target URL (must start with http:// or https://).
        method: HTTP method: 'GET' (default), 'POST', 'PUT', 'PATCH', 'DELETE' or 'HEAD'.
        headers: Optional dict of HTTP headers to send (e.g. {"Authorization": "Bearer ..."}).
        body: Optional raw request body as a string (for POST/PUT/PATCH).
        json_data: Optional JSON string to send as the request body with Content-Type application/json
                   (e.g. '{"key": "value"}'). Takes precedence over 'body'.
        timeout_seconds: Request timeout in seconds (default 30, max 120).
    
    Returns:
        str: 'Status: <code>' + 'Content-Type: ...' + the response body (truncated to 8000 chars), or an error message.
    """
    try:
        _assert_safe_url(url)

        method = (method or "GET").upper()
        if method not in _ALLOWED_METHODS:
            return f"Error: method '{method}' not allowed. Use one of: {', '.join(_ALLOWED_METHODS)}."

        timeout_seconds = min(max(int(timeout_seconds or 30), 1), 120)

        # The headers param may arrive as a JSON string when the provider
        # declares it as a string (Gemini-safe schemas) — accept both shapes.
        if isinstance(headers, str):
            try:
                headers = json.loads(headers) if headers.strip() else {}
            except (ValueError, TypeError):
                return "Error: 'headers' must be a JSON object (e.g. {\"Authorization\": \"Bearer ...\"}) or omitted."

        kwargs = {"timeout": timeout_seconds, "impersonate": "chrome"}
        if headers:
            kwargs["headers"] = headers
        if json_data is not None:
            try:
                kwargs["json"] = json.loads(json_data)
            except json.JSONDecodeError as e:
                return f"Error: json_data is not valid JSON: {e}"
        elif body is not None:
            kwargs["data"] = body

        response = getattr(requests, method.lower())(url, **kwargs)

        content_type = response.headers.get("Content-Type", "") if response.headers else ""
        is_text = any(t in content_type.lower() for t in ("text", "json", "xml", "html")) or not content_type

        body_text = "[binary body omitted]" if not is_text else (response.text or "")[:_MAX_BODY_CHARS]
        suffix = "" if len(response.text or "") <= _MAX_BODY_CHARS else f"\n...[body truncated at {_MAX_BODY_CHARS} chars]"

        header_note = ""
        if len(response.content or b"") > _MAX_RESPONSE_BYTES:
            header_note = "\n⚠️ Response was larger than 5MB — use download_file_from_url for full downloads."

        return f"Status: {response.status_code}\nContent-Type: {content_type or 'unknown'}\n\n{body_text}{suffix}{header_note}"
    except ValueError as e:
        return f"Error: {str(e)}"
    except Exception as e:
        return f"Error performing HTTP request: {str(e)}"