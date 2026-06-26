"""Web research: a small, provider-abstracted search + extract client.

Two operations the agent needs to research the market, competitors, and clients:

  • search(query)  → ranked (title, url, snippet) results
  • extract(url)   → the page's main text, cleaned and length-capped

Provider is pluggable. **Exa** is the recommended backend (set EXA_API_KEY); Tavily is an
alternative, and keyless DuckDuckGo is the zero-config fallback used when no key is set, so the
bot and tests run with no API key. All network I/O goes through one httpx call site; tests
inject an ``httpx.MockTransport`` so nothing here ever touches the real network under pytest.
"""

from __future__ import annotations

import asyncio
import html
import ipaddress
import re
import socket
import urllib.parse
from collections.abc import Callable
from dataclasses import dataclass

import httpx

DEFAULT_PROVIDER = "ddgs"
KEYLESS_PROVIDER = "ddgs"
KEYED_PROVIDERS = ("tavily", "exa")
PROVIDERS = ("ddgs", "tavily", "exa")


def resolve_provider(provider: str, api_key: str) -> str:
    """The provider to actually use. A keyed provider (exa/tavily) with no key configured
    falls back to keyless DuckDuckGo so the bot still has web search out of the box."""
    provider = (provider or DEFAULT_PROVIDER).strip().lower()
    if provider in KEYED_PROVIDERS and not (api_key or "").strip():
        return KEYLESS_PROVIDER
    return provider


# Cap how many redirects extract() will follow; each hop is re-validated against the SSRF guard.
_MAX_REDIRECTS = 5

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
        block_private_addresses: bool | None = None,
        resolver: Callable[..., list] | None = None,
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
        self._resolver = resolver
        # The SSRF guard resolves hostnames to IPs, which needs the real network, so by default
        # it is active only in production (no injected transport). Tests can force it on while
        # injecting a fake resolver to exercise the guard without touching the network.
        self._guard_enabled = transport is None if block_private_addresses is None else block_private_addresses

    def _client(self, *, follow_redirects: bool = True) -> httpx.AsyncClient:
        headers = {"User-Agent": "Mozilla/5.0 (compatible; llm-mmo-bot/1.0)"}
        return httpx.AsyncClient(timeout=self.timeout, headers=headers, transport=self._transport, follow_redirects=follow_redirects)

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
            # follow_redirects=False so we can re-validate the host on every hop; a page can
            # otherwise redirect a public URL to a private/metadata address.
            async with self._client(follow_redirects=False) as client:
                body = await self._fetch_guarded(client, url)
        except httpx.HTTPError as exc:
            raise WebError(f"extract transport error: {exc}") from exc
        return _truncate(html_to_text(body), budget)

    async def _fetch_guarded(self, client: httpx.AsyncClient, url: str) -> str:
        current = url
        for _ in range(_MAX_REDIRECTS + 1):
            await self._guard_url(current)
            resp = await client.get(current)
            if resp.is_redirect and resp.next_request is not None:
                current = str(resp.next_request.url)
                continue
            resp.raise_for_status()
            return resp.text
        raise WebError("too many redirects while extracting page")

    async def _guard_url(self, url: str) -> None:
        """Block requests to private/internal/metadata addresses (SSRF defense)."""
        if not self._guard_enabled:
            return
        parsed = urllib.parse.urlparse(url)
        if parsed.scheme not in {"http", "https"}:
            raise WebError(f"refusing to follow a non-http(s) redirect: {url}")
        host = parsed.hostname or ""
        if await asyncio.to_thread(host_is_blocked, host, resolver=self._resolver):
            raise WebError(f"refusing to fetch a private or internal address: {host or url!r}")

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


_IPAddress = ipaddress.IPv4Address | ipaddress.IPv6Address


def _ip_is_blocked(ip: _IPAddress) -> bool:
    """True for any address an external fetch must never reach.

    Covers loopback, private RFC1918/ULA, link-local (incl. the 169.254.169.254 cloud
    metadata endpoint), multicast, reserved, and unspecified ranges. IPv4-mapped IPv6
    addresses are unwrapped first so e.g. ::ffff:127.0.0.1 is caught.
    """
    if isinstance(ip, ipaddress.IPv6Address) and ip.ipv4_mapped is not None:
        ip = ip.ipv4_mapped
    return ip.is_private or ip.is_loopback or ip.is_link_local or ip.is_multicast or ip.is_reserved or ip.is_unspecified


def host_is_blocked(host: str, *, resolver: Callable[..., list] | None = None) -> bool:
    """Resolve ``host`` and return True if it points at a non-public address.

    ``resolver`` defaults to ``socket.getaddrinfo`` (real DNS); tests inject a fake so the
    check runs without touching the network. An unresolvable or malformed host is blocked.
    """
    resolve = resolver or socket.getaddrinfo
    host = (host or "").strip().rstrip(".").lower()
    if host.startswith("[") and host.endswith("]"):
        host = host[1:-1]
    if not host or host == "localhost" or host.endswith((".local", ".internal", ".localhost")):
        return True
    # Literal IP — no DNS needed.
    try:
        return _ip_is_blocked(ipaddress.ip_address(host))
    except ValueError:
        pass
    try:
        infos = resolve(host, None)
    except (OSError, UnicodeError):
        return True
    if not infos:
        return True
    for info in infos:
        addr = str(info[4][0]).split("%", 1)[0]
        try:
            if _ip_is_blocked(ipaddress.ip_address(addr)):
                return True
        except ValueError:
            return True  # unparseable resolved address → fail closed
    return False


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
