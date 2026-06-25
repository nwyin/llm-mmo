"""Web research: a small, provider-abstracted search + extract client.

Two operations the agent needs to research the market, competitors, and clients:

  • search(query)  → ranked (title, url, snippet) results
  • extract(url)   → the page's main text, cleaned and length-capped

Provider is pluggable. The default backend is **keyless** (DuckDuckGo) so the bot runs and
the tests pass with no API key; set WEB_SEARCH_PROVIDER=tavily|exa plus the matching API key
to use a paid backend. All network I/O goes through one httpx call site; tests inject an
``httpx.MockTransport`` so nothing here ever touches the real network under pytest.
"""

from __future__ import annotations

import html
import re
import urllib.parse
from dataclasses import dataclass

import httpx

DEFAULT_PROVIDER = "ddgs"
PROVIDERS = ("ddgs", "tavily", "exa")

_DDGS_URL = "https://lite.duckduckgo.com/lite/"
_TAVILY_URL = "https://api.tavily.com/search"
_EXA_URL = "https://api.exa.ai/search"

_TAG_RE = re.compile(r"<[^>]+>")
_SCRIPT_STYLE_RE = re.compile(r"<(script|style)\b[^>]*>.*?</\1>", re.IGNORECASE | re.DOTALL)
_WS_RE = re.compile(r"[ \t\f\v]+")
_BLANK_LINES_RE = re.compile(r"\n\s*\n\s*\n+")
_DDGS_ANCHOR_RE = re.compile(r'<a\b[^>]*class="result-link"[^>]*href="([^"]+)"[^>]*>(.*?)</a>', re.IGNORECASE | re.DOTALL)
_DDGS_SNIPPET_RE = re.compile(r'<td\b[^>]*class="result-snippet"[^>]*>(.*?)</td>', re.IGNORECASE | re.DOTALL)


class WebError(Exception):
    """Raised for any provider/transport failure; callers turn it into a tool error string."""


@dataclass(frozen=True)
class SearchResult:
    title: str
    url: str
    snippet: str


class WebClient:
    """A thin async client over one of several search providers, plus a generic page extractor."""

    def __init__(
        self,
        *,
        provider: str = DEFAULT_PROVIDER,
        api_key: str | None = None,
        timeout: int = 20,
        max_chars: int = 8000,
        transport: httpx.AsyncBaseTransport | None = None,
    ) -> None:
        provider = (provider or DEFAULT_PROVIDER).strip().lower()
        if provider not in PROVIDERS:
            raise WebError(f"unknown web provider {provider!r}; choose one of {', '.join(PROVIDERS)}")
        if provider in {"tavily", "exa"} and not (api_key or "").strip():
            raise WebError(f"web provider {provider!r} requires an API key")
        self.provider = provider
        self.api_key = (api_key or "").strip()
        self.timeout = timeout
        self.max_chars = max_chars
        self._transport = transport

    def _client(self) -> httpx.AsyncClient:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; llm-mmo-bot/1.0)"}
        return httpx.AsyncClient(timeout=self.timeout, headers=headers, transport=self._transport, follow_redirects=True)

    async def search(self, query: str, *, k: int = 5) -> list[SearchResult]:
        query = (query or "").strip()
        if not query or k <= 0:
            return []
        try:
            if self.provider == "ddgs":
                return await self._search_ddgs(query, k)
            if self.provider == "tavily":
                return await self._search_tavily(query, k)
            return await self._search_exa(query, k)
        except httpx.HTTPError as exc:
            raise WebError(f"search transport error: {exc}") from exc

    async def extract(self, url: str, *, max_chars: int | None = None) -> str:
        url = (url or "").strip()
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"} or not parsed.netloc:
            raise WebError("extract requires an http(s) URL")
        budget = self.max_chars if max_chars is None else max_chars
        try:
            async with self._client() as client:
                resp = await client.get(url)
                resp.raise_for_status()
                body = resp.text
        except httpx.HTTPError as exc:
            raise WebError(f"extract transport error: {exc}") from exc
        return _truncate(html_to_text(body), budget)

    async def _search_ddgs(self, query: str, k: int) -> list[SearchResult]:
        async with self._client() as client:
            resp = await client.post(_DDGS_URL, data={"q": query})
            resp.raise_for_status()
            return _parse_ddgs(resp.text, k)

    async def _search_tavily(self, query: str, k: int) -> list[SearchResult]:
        payload = {"api_key": self.api_key, "query": query, "max_results": k}
        async with self._client() as client:
            resp = await client.post(_TAVILY_URL, json=payload)
            resp.raise_for_status()
            data = resp.json()
        results = []
        for item in (data.get("results") or [])[:k]:
            results.append(
                SearchResult(
                    title=str(item.get("title", "")).strip(),
                    url=str(item.get("url", "")).strip(),
                    snippet=_truncate(str(item.get("content", "")).strip(), 400),
                )
            )
        return results

    async def _search_exa(self, query: str, k: int) -> list[SearchResult]:
        payload = {"query": query, "numResults": k}
        headers = {"x-api-key": self.api_key}
        async with self._client() as client:
            resp = await client.post(_EXA_URL, json=payload, headers=headers)
            resp.raise_for_status()
            data = resp.json()
        results = []
        for item in (data.get("results") or [])[:k]:
            snippet = item.get("text") or item.get("snippet") or item.get("summary") or ""
            results.append(
                SearchResult(
                    title=str(item.get("title", "")).strip(),
                    url=str(item.get("url", "")).strip(),
                    snippet=_truncate(str(snippet).strip(), 400),
                )
            )
        return results


def _parse_ddgs(body: str, k: int) -> list[SearchResult]:
    anchors = _DDGS_ANCHOR_RE.findall(body)
    snippets = _DDGS_SNIPPET_RE.findall(body)
    results: list[SearchResult] = []
    for index, (href, raw_title) in enumerate(anchors[:k]):
        title = _clean_inline(raw_title)
        url = _unwrap_ddgs_url(html.unescape(href))
        snippet = _clean_inline(snippets[index]) if index < len(snippets) else ""
        if url:
            results.append(SearchResult(title=title, url=url, snippet=_truncate(snippet, 400)))
    return results


def _unwrap_ddgs_url(href: str) -> str:
    """DuckDuckGo wraps outbound links as /l/?uddg=<encoded>; return the real target."""
    parsed = urllib.parse.urlparse(href)
    if parsed.path.endswith("/l/") or "uddg" in parsed.query:
        params = urllib.parse.parse_qs(parsed.query)
        target = params.get("uddg", [""])[0]
        if target:
            return urllib.parse.unquote(target)
    if href.startswith("//"):
        return "https:" + href
    return href


def html_to_text(body: str) -> str:
    """Strip a chunk of HTML down to readable text (scripts/styles removed, tags dropped)."""
    without_blocks = _SCRIPT_STYLE_RE.sub(" ", body)
    text = _TAG_RE.sub(" ", without_blocks)
    text = html.unescape(text)
    text = _WS_RE.sub(" ", text)
    text = "\n".join(line.strip() for line in text.splitlines())
    return _BLANK_LINES_RE.sub("\n\n", text).strip()


def _clean_inline(fragment: str) -> str:
    return _WS_RE.sub(" ", html.unescape(_TAG_RE.sub(" ", fragment))).strip()


def _truncate(text: str, max_chars: int) -> str:
    if max_chars <= 0 or len(text) <= max_chars:
        return text
    return text[:max_chars].rstrip() + "\n…[truncated]"


def format_results(results: list[SearchResult]) -> str:
    if not results:
        return "no web results"
    lines = []
    for result in results:
        title = result.title or "(untitled)"
        lines.append(f"- {title}\n    {result.url}\n    {result.snippet}".rstrip())
    return "\n".join(lines)
