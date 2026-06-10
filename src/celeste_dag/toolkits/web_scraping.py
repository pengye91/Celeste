"""
Web Scraping Toolkit -- HTTP and web page extraction tools.

Provides tools for making HTTP requests, scraping page content,
and downloading files from the web.
"""

from __future__ import annotations

from celeste_dag.toolkits.base import BaseToolkit, ToolDefinition, ToolParameter


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
