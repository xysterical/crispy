from __future__ import annotations

from dataclasses import dataclass


@dataclass(slots=True)
class FirecrawlScrapeResult:
    title: str
    url: str
    markdown: str
    metadata: dict


class FirecrawlClient:
    """Lightweight wrapper around Firecrawl Scrape API for AI agent use."""

    def __init__(self, api_key: str) -> None:
        from firecrawl import FirecrawlApp
        self._app = FirecrawlApp(api_key=api_key)

    def scrape(self, url: str) -> FirecrawlScrapeResult:
        """Scrape a single URL and return cleaned markdown content."""
        response = self._app.scrape_url(url, params={"formats": ["markdown"]})
        if not isinstance(response, dict):
            raise RuntimeError(f"Firecrawl scrape failed for {url}: unexpected response type")
        return FirecrawlScrapeResult(
            title=response.get("title", ""),
            url=url,
            markdown=response.get("markdown", "") or "",
            metadata=response.get("metadata", {}),
        )

    def scrape_raw(self, url: str) -> dict:
        """Return raw Firecrawl scrape response dict."""
        response = self._app.scrape_url(url, params={"formats": ["markdown"]})
        if not isinstance(response, dict):
            raise RuntimeError(f"Firecrawl scrape failed for {url}")
        return response
