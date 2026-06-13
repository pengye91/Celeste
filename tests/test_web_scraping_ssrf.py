"""SEC-003: SSRF protection in WebScrapingToolkit.

Tests demonstrate that:
- http_get, http_post, scrape_page, download_file must reject URLs whose
  host resolves to a private/loopback/link-local address
- Non-HTTP(S) schemes (file://, gopher://, ftp://, dict://, etc.) must be
  rejected
- Direct IP literals targeting private ranges (127.0.0.0/8, 10.0.0.0/8,
  172.16.0.0/12, 192.168.0.0/16, 169.254.0.0/16) must be rejected

The fix MUST return a structured error with `error == "ssrf_blocked"` so
that operators can distinguish a deliberate security block from a generic
network error.
"""

from __future__ import annotations

import pytest


def _assert_ssrf_blocked(result: dict, url: str) -> None:
    """Helper: the toolkit must return a structured ssrf_blocked error.

    We require the specific error key so we can distinguish a deliberate
    security block from a generic network error.
    """
    assert "error" in result, (
        f"SEC-003: http_get did not return an error for {url} — possible SSRF"
    )
    assert result.get("error") == "ssrf_blocked", (
        f"SEC-003: expected error='ssrf_blocked' for {url}, got {result!r}"
    )
    assert result.get("status") is None


# ===========================================================================
# SEC-003: SSRF protection
# ===========================================================================


class TestSSRFSchemeRejection:
    """Non-HTTP(S) schemes must be rejected before any HTTP call."""

    @pytest.mark.asyncio
    async def test_http_get_rejects_file_scheme(self):
        from celeste.toolkits.web_scraping import WebScrapingToolkit

        tk = WebScrapingToolkit()
        result = await tk.execute("http_get", {"url": "file:///etc/passwd"}, driver=None)
        _assert_ssrf_blocked(result, "file:///etc/passwd")

    @pytest.mark.asyncio
    async def test_http_get_rejects_ftp_scheme(self):
        from celeste.toolkits.web_scraping import WebScrapingToolkit

        tk = WebScrapingToolkit()
        result = await tk.execute("http_get", {"url": "ftp://example.com/x"}, driver=None)
        _assert_ssrf_blocked(result, "ftp://example.com/x")

    @pytest.mark.asyncio
    async def test_http_get_rejects_gopher_scheme(self):
        from celeste.toolkits.web_scraping import WebScrapingToolkit

        tk = WebScrapingToolkit()
        result = await tk.execute("http_get", {"url": "gopher://example.com/0"}, driver=None)
        _assert_ssrf_blocked(result, "gopher://example.com/0")


class TestSSRFPrivateIPRejection:
    """URLs whose host is a private IP literal must be rejected."""

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/x",
            "http://127.1.2.3/x",
            "http://10.0.0.1/x",
            "http://10.255.255.255/x",
            "http://172.16.0.1/x",
            "http://172.31.255.255/x",
            "http://192.168.1.1/x",
            "http://169.254.169.254/latest/meta-data/",
        ],
    )
    async def test_http_get_rejects_private_ips(self, url):
        from celeste.toolkits.web_scraping import WebScrapingToolkit

        tk = WebScrapingToolkit()
        result = await tk.execute("http_get", {"url": url}, driver=None)
        _assert_ssrf_blocked(result, url)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/x",
            "http://10.0.0.1/x",
            "http://192.168.0.1/x",
        ],
    )
    async def test_http_post_rejects_private_ips(self, url):
        from celeste.toolkits.web_scraping import WebScrapingToolkit

        tk = WebScrapingToolkit()
        result = await tk.execute(
            "http_post", {"url": url, "body": {"x": 1}}, driver=None
        )
        _assert_ssrf_blocked(result, url)

    @pytest.mark.asyncio
    @pytest.mark.parametrize(
        "url",
        [
            "http://127.0.0.1/x",
            "http://10.0.0.1/x",
            "http://169.254.169.254/latest/",
        ],
    )
    async def test_scrape_page_rejects_private_ips(self, url):
        from celeste.toolkits.web_scraping import WebScrapingToolkit

        tk = WebScrapingToolkit()
        result = await tk.execute("scrape_page", {"url": url}, driver=None)
        _assert_ssrf_blocked(result, url)

    @pytest.mark.asyncio
    async def test_download_file_rejects_private_ips(self, tmp_path):
        from celeste.toolkits.web_scraping import WebScrapingToolkit

        tk = WebScrapingToolkit()
        dest = str(tmp_path / "out.bin")
        result = await tk.execute(
            "download_file",
            {"url": "http://169.254.169.254/latest/", "destination": dest},
            driver=None,
        )
        _assert_ssrf_blocked(result, "http://169.254.169.254/latest/")


class TestSSRFInvalidURLs:
    """Garbage URLs should be rejected, not raise uncaught exceptions."""

    @pytest.mark.asyncio
    async def test_empty_url_rejected(self):
        from celeste.toolkits.web_scraping import WebScrapingToolkit

        tk = WebScrapingToolkit()
        result = await tk.execute("http_get", {"url": ""}, driver=None)
        _assert_ssrf_blocked(result, "")

    @pytest.mark.asyncio
    async def test_garbage_url_rejected(self):
        from celeste.toolkits.web_scraping import WebScrapingToolkit

        tk = WebScrapingToolkit()
        result = await tk.execute("http_get", {"url": "not a url"}, driver=None)
        _assert_ssrf_blocked(result, "not a url")


class TestSSRFSourceAudit:
    """Source-level audit: WebScrapingToolkit must use a URL validator."""

    def test_source_uses_url_validator(self):
        """The toolkit must call a host/IP validator before sending any request."""
        import inspect

        from celeste.toolkits import web_scraping as mod

        source = inspect.getsource(mod)
        # The validator symbol we expect after the fix:
        assert "_validate_url" in source or "_ssrf_safe" in source, (
            "SEC-003: WebScrapingToolkit has no URL validator helper. "
            "URLs must be checked for scheme + private IPs before httpx calls."
        )