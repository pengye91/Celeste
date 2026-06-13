"""
Web Scraping Toolkit -- HTTP and web page extraction tools.

Provides tools for making HTTP requests, scraping page content,
and downloading files from the web.

SECURITY (SEC-003): every URL must pass ``_validate_url`` before any HTTP
call is made. The validator restricts schemes to http/https, and rejects
host literals that resolve to private, loopback, link-local, or otherwise
non-routable IP addresses.
"""

from __future__ import annotations

import ipaddress
import socket
from typing import Any
from urllib.parse import urlparse

from celeste.toolkits.base import BaseToolkit, ToolDefinition, ToolParameter


# ---------------------------------------------------------------------------
# SSRF protection (SEC-003)
# ---------------------------------------------------------------------------

_ALLOWED_SCHEMES = frozenset({"http", "https"})


def _validate_url(url: str) -> dict[str, Any] | None:
    """Validate a URL against SSRF risks. Returns ``None`` if safe.

    Returns a structured ``{"error": "ssrf_blocked", "reason": ...}`` dict
    if the URL must not be fetched. The check is intentionally conservative:
    if any resolution fails or the host cannot be classified as a public IP,
    the request is denied.
    """
    if not isinstance(url, str) or not url.strip():
        return {"error": "ssrf_blocked", "reason": "URL is empty"}
    try:
        parsed = urlparse(url)
    except Exception:
        return {"error": "ssrf_blocked", "reason": "URL could not be parsed"}

    if parsed.scheme.lower() not in _ALLOWED_SCHEMES:
        return {
            "error": "ssrf_blocked",
            "reason": f"scheme '{parsed.scheme}' is not allowed (must be http/https)",
        }

    host = parsed.hostname  # strips port and brackets
    if not host:
        return {"error": "ssrf_blocked", "reason": "URL has no host"}

    # Try direct literal first (ipaddress handles IPv4 + IPv6)
    try:
        ip = ipaddress.ip_address(host)
    except ValueError:
        # Hostname — resolve it. If resolution fails, deny.
        try:
            infos = socket.getaddrinfo(host, None)
        except socket.gaierror as exc:
            return {
                "error": "ssrf_blocked",
                "reason": f"DNS resolution failed for {host}: {exc}",
            }
        resolved_ips = {info[4][0] for info in infos}
        # If ANY resolved IP is private, deny (rebinding mitigation).
        for ip_str in resolved_ips:
            try:
                ip = ipaddress.ip_address(ip_str)
            except ValueError:
                continue
            if _is_blocked_ip(ip):
                return {
                    "error": "ssrf_blocked",
                    "reason": f"host {host} resolves to blocked IP {ip}",
                }
        return None

    if _is_blocked_ip(ip):
        return {
            "error": "ssrf_blocked",
            "reason": f"IP literal {ip} is in a blocked range",
        }
    return None


def _is_blocked_ip(ip: ipaddress._BaseAddress) -> bool:
    """Return True if *ip* is in any range we refuse to fetch."""
    # is_private covers RFC1918 + loopback + link-local + ULA + unique local.
    # is_loopback, is_link_local, is_multicast, is_reserved, is_unspecified
    # are separate flags we explicitly check too.
    return (
        ip.is_private
        or ip.is_loopback
        or ip.is_link_local
        or ip.is_multicast
        or ip.is_reserved
        or ip.is_unspecified
    )


class WebScrapingToolkit(BaseToolkit):
    """Web automation tools for HTTP requests and page scraping."""

    @property
    def name(self) -> str:
        return "web_scraping"

    @property
    def description(self) -> str:
        return "Web automation tools for HTTP requests, page scraping, and file downloads."

    # ------------------------------------------------------------------
    # Tool definitions
    # ------------------------------------------------------------------

    _TOOLS: list[ToolDefinition] = [
        ToolDefinition(
            name="http_get",
            description="Perform an HTTP GET request to a URL.",
            parameters=[
                ToolParameter(
                    name="url",
                    type="string",
                    description="Target URL for the GET request.",
                    required=True,
                ),
                ToolParameter(
                    name="headers",
                    type="object",
                    description="Optional HTTP headers to include in the request.",
                    required=False,
                ),
            ],
            returns="HTTP response body as a string.",
        ),
        ToolDefinition(
            name="http_post",
            description="Perform an HTTP POST request to a URL.",
            parameters=[
                ToolParameter(
                    name="url",
                    type="string",
                    description="Target URL for the POST request.",
                    required=True,
                ),
                ToolParameter(
                    name="body",
                    type="object",
                    description="Request body payload.",
                    required=True,
                ),
                ToolParameter(
                    name="headers",
                    type="object",
                    description="Optional HTTP headers to include in the request.",
                    required=False,
                ),
            ],
            returns="HTTP response body as a string.",
        ),
        ToolDefinition(
            name="scrape_page",
            description="Scrape and extract content from a web page.",
            parameters=[
                ToolParameter(
                    name="url",
                    type="string",
                    description="URL of the page to scrape.",
                    required=True,
                ),
                ToolParameter(
                    name="selector",
                    type="string",
                    description="Optional CSS selector to target specific elements.",
                    required=False,
                ),
            ],
            returns="Extracted page content as a string.",
        ),
        ToolDefinition(
            name="download_file",
            description="Download a file from a URL to a local destination.",
            parameters=[
                ToolParameter(
                    name="url",
                    type="string",
                    description="URL of the file to download.",
                    required=True,
                ),
                ToolParameter(
                    name="destination",
                    type="string",
                    description="Local file path where the file will be saved.",
                    required=True,
                ),
            ],
            returns="Confirmation message with file path.",
        ),
    ]

    # ------------------------------------------------------------------
    # Public API
    # ------------------------------------------------------------------

    def get_tools(self) -> list[ToolDefinition]:
        return list(self._TOOLS)

    def get_tool(self, name: str) -> ToolDefinition | None:
        for tool in self._TOOLS:
            if tool.name == name:
                return tool
        return None

    async def execute(
        self, name: str, arguments: dict[str, Any], driver: Any | None
    ) -> dict[str, Any]:
        """Execute a web-scraping tool."""
        if name == "http_get":
            url = arguments.get("url", "")
            blocked = _validate_url(url)
            if blocked is not None:
                return blocked
            headers = arguments.get("headers") or {}
            try:
                import httpx

                async with httpx.AsyncClient() as client:
                    response = await client.get(url, headers=headers, follow_redirects=False)
                return {"status": response.status_code, "body": response.text}
            except Exception as exc:
                return {"error": "http_error", "message": str(exc)}

        if name == "http_post":
            url = arguments.get("url", "")
            blocked = _validate_url(url)
            if blocked is not None:
                return blocked
            body = arguments.get("body", {})
            headers = arguments.get("headers") or {}
            try:
                import httpx

                async with httpx.AsyncClient() as client:
                    response = await client.post(url, json=body, headers=headers, follow_redirects=False)
                return {"status": response.status_code, "body": response.text}
            except Exception as exc:
                return {"error": "http_error", "message": str(exc)}

        if name == "scrape_page":
            url = arguments.get("url", "")
            blocked = _validate_url(url)
            if blocked is not None:
                return blocked
            selector = arguments.get("selector")
            try:
                import httpx

                async with httpx.AsyncClient() as client:
                    response = await client.get(url, follow_redirects=False)
                text = response.text
                if selector:
                    try:
                        from bs4 import BeautifulSoup

                        soup = BeautifulSoup(text, "html.parser")
                        elements = soup.select(selector)
                        text = "\n".join(el.get_text(strip=True) for el in elements)
                    except Exception:
                        pass
                return {"status": response.status_code, "content": text}
            except Exception as exc:
                return {"error": "scrape_error", "message": str(exc)}

        if name == "download_file":
            url = arguments.get("url", "")
            blocked = _validate_url(url)
            if blocked is not None:
                return blocked
            destination = arguments.get("destination", "")
            try:
                import httpx

                async with httpx.AsyncClient() as client:
                    response = await client.get(url, follow_redirects=False)
                with open(destination, "wb") as f:
                    f.write(response.content)
                return {"success": True, "path": destination, "size": len(response.content)}
            except Exception as exc:
                return {"error": "download_error", "message": str(exc)}

        return {"error": "tool_not_found", "tool_name": name}
