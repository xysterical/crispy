from __future__ import annotations

from dataclasses import dataclass, field


@dataclass(slots=True)
class TavilySearchResult:
    title: str
    url: str
    content: str
    score: float = 0.0


@dataclass(slots=True)
class TavilySearchResponse:
    query: str
    results: list[TavilySearchResult] = field(default_factory=list)
    answer: str = ""


class TavilyClient:
    """Lightweight wrapper around Tavily Search API for AI agent use."""

    def __init__(self, api_key: str) -> None:
        from tavily import TavilyClient as _TavilyClient
        self._client = _TavilyClient(api_key=api_key)

    def search(self, query: str, *, max_results: int = 5, include_answer: bool = True) -> TavilySearchResponse:
        """Execute a semantic search query. Returns structured results with content snippets."""
        response = self._client.search(
            query=query,
            max_results=max_results,
            include_answer=include_answer,
            search_depth="basic",
        )
        results = [
            TavilySearchResult(
                title=r.get("title", ""),
                url=r.get("url", ""),
                content=r.get("content", ""),
                score=float(r.get("score", 0)),
            )
            for r in (response.get("results") or [])
        ]
        return TavilySearchResponse(
            query=response.get("query", query),
            results=results,
            answer=response.get("answer", ""),
        )

    def search_raw(self, query: str, *, max_results: int = 5) -> dict:
        """Return raw Tavily response dict for advanced use cases."""
        return self._client.search(query=query, max_results=max_results, search_depth="basic")
