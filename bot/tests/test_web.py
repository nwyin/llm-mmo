"""Web client + web tools tests. No network: an httpx.MockTransport backs every call."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from tools import build_web_tools
from web import WebClient, WebError, html_to_text

_DDGS_HTML = """
<html><body><table>
<tr><td><a class="result-link" href="//duckduckgo.com/l/?uddg=https%3A%2F%2Facme.example%2Fpricing">Acme Pricing</a></td></tr>
<tr><td class="result-snippet">Acme offers three tiers for startups.</td></tr>
<tr><td><a class="result-link" href="https://beta.example/about">Beta About</a></td></tr>
<tr><td class="result-snippet">Beta is a competitor in the same space.</td></tr>
</table></body></html>
"""


def _mock(handler) -> httpx.MockTransport:
    return httpx.MockTransport(handler)


def test_ddgs_search_parses_and_unwraps_urls() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        assert request.url.host == "lite.duckduckgo.com"
        return httpx.Response(200, text=_DDGS_HTML)

    client = WebClient(provider="ddgs", transport=_mock(handler))
    results = asyncio.run(client.search("acme pricing", k=5))

    assert len(results) == 2
    assert results[0].title == "Acme Pricing"
    assert results[0].url == "https://acme.example/pricing"
    assert "three tiers" in results[0].snippet
    assert results[1].url == "https://beta.example/about"


def test_search_routes_to_tavily_with_api_key() -> None:
    seen: dict[str, Any] = {}

    def handler(request: httpx.Request) -> httpx.Response:
        seen["host"] = request.url.host
        seen["body"] = json.loads(request.content)
        return httpx.Response(
            200,
            json={"results": [{"title": "T", "url": "https://t.example", "content": "snippet"}]},
        )

    client = WebClient(provider="tavily", api_key="secret", transport=_mock(handler))
    results = asyncio.run(client.search("market size", k=3))

    assert seen["host"] == "api.tavily.com"
    assert seen["body"]["api_key"] == "secret"
    assert results[0].url == "https://t.example"


def test_tavily_without_key_is_rejected_at_construction() -> None:
    with pytest.raises(WebError):
        WebClient(provider="tavily")


def test_unknown_provider_is_rejected() -> None:
    with pytest.raises(WebError):
        WebClient(provider="nope")


def test_empty_query_skips_the_provider() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("provider should not be called for an empty query")

    client = WebClient(provider="ddgs", transport=_mock(handler))
    assert asyncio.run(client.search("   ", k=5)) == []


def test_extract_rejects_non_http_urls() -> None:
    client = WebClient(provider="ddgs")
    with pytest.raises(WebError):
        asyncio.run(client.extract("file:///etc/passwd"))
    with pytest.raises(WebError):
        asyncio.run(client.extract("ftp://x/y"))


def test_extract_strips_html_and_truncates() -> None:
    page = "<html><head><style>p{color:red}</style></head><body><h1>Title</h1>" + "<p>word</p>" * 200 + "</body></html>"

    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(200, text=page)

    client = WebClient(provider="ddgs", max_chars=120, transport=_mock(handler))
    text = asyncio.run(client.extract("https://example.com/post"))

    assert "color:red" not in text
    assert "<" not in text
    assert text.endswith("…[truncated]")
    assert len(text) <= 120 + len("\n…[truncated]")


def test_extract_surfaces_http_errors_as_weberror() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(503, text="down")

    client = WebClient(provider="ddgs", transport=_mock(handler))
    with pytest.raises(WebError):
        asyncio.run(client.extract("https://example.com"))


def test_web_search_tool_returns_error_string_on_failure() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(500, text="boom")

    client = WebClient(provider="ddgs", transport=_mock(handler))
    web_search = next(tool for tool in build_web_tools(client) if tool.name == "web_search")

    result = asyncio.run(web_search.handler({"query": "anything"}))
    assert result.startswith("error:")


def test_html_to_text_collapses_whitespace() -> None:
    assert html_to_text("<p>hello   world</p>") == "hello world"
