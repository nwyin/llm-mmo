"""Web client + web tools tests. No network: an httpx.MockTransport backs every call."""

from __future__ import annotations

import asyncio
import json
from typing import Any

import httpx
import pytest

from tools import build_web_tools
from web import WebClient, WebError, host_is_blocked, html_to_text, resolve_provider


def _resolver_to(ip: str):
    """A fake DNS resolver that maps every host to a single IP (no network)."""

    def resolve(host, *args, **kwargs):
        return [(2, 1, 6, "", (ip, 0))]

    return resolve


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


# ---- provider resolution / keyless fallback ---------------------------------


def test_keyed_provider_without_key_falls_back_to_ddgs() -> None:
    assert resolve_provider("exa", "") == "ddgs"
    assert resolve_provider("tavily", "  ") == "ddgs"


def test_keyed_provider_with_key_is_kept() -> None:
    assert resolve_provider("exa", "exa-key") == "exa"
    assert resolve_provider("tavily", "tav-key") == "tavily"


def test_keyless_and_unknown_providers_pass_through() -> None:
    assert resolve_provider("ddgs", "") == "ddgs"
    assert resolve_provider("EXA", "k") == "exa"  # normalized
    assert resolve_provider("", "") == "ddgs"  # empty -> default keyless


# ---- SSRF guard -------------------------------------------------------------


def test_host_is_blocked_for_literal_private_and_metadata_ips() -> None:
    for blocked in ["127.0.0.1", "0.0.0.0", "10.0.0.5", "192.168.1.1", "169.254.169.254", "::1", "::ffff:127.0.0.1"]:
        assert host_is_blocked(blocked, resolver=_resolver_to("8.8.8.8")) is True, blocked


def test_host_is_blocked_for_localhost_and_internal_names() -> None:
    assert host_is_blocked("localhost", resolver=_resolver_to("8.8.8.8")) is True
    assert host_is_blocked("db.internal", resolver=_resolver_to("8.8.8.8")) is True
    assert host_is_blocked("foo.local", resolver=_resolver_to("8.8.8.8")) is True
    assert host_is_blocked("", resolver=_resolver_to("8.8.8.8")) is True


def test_host_blocked_when_name_resolves_to_private_ip() -> None:
    # A public-looking name that resolves to a private address must still be blocked.
    assert host_is_blocked("evil.example", resolver=_resolver_to("10.1.2.3")) is True


def test_host_allowed_when_name_resolves_to_public_ip() -> None:
    assert host_is_blocked("acme.example", resolver=_resolver_to("93.184.216.34")) is False


def test_host_blocked_when_resolution_fails() -> None:
    def boom(host, *args, **kwargs):
        raise OSError("nxdomain")

    assert host_is_blocked("nope.example", resolver=boom) is True


def test_extract_blocks_request_to_private_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:  # pragma: no cover - must not run
        raise AssertionError("guard should block before any request is made")

    client = WebClient(
        provider="ddgs",
        transport=_mock(handler),
        block_private_addresses=True,
        resolver=_resolver_to("169.254.169.254"),
    )
    with pytest.raises(WebError):
        asyncio.run(client.extract("http://metadata.example/latest/meta-data/"))


def test_extract_blocks_redirect_to_private_host() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "public.example":
            return httpx.Response(302, headers={"location": "http://169.254.169.254/latest/"})
        raise AssertionError("must not follow the redirect to the metadata host")

    client = WebClient(
        provider="ddgs",
        transport=_mock(handler),
        block_private_addresses=True,
        resolver=_resolver_to("93.184.216.34"),  # public.example resolves public; literal IP self-blocks
    )
    with pytest.raises(WebError):
        asyncio.run(client.extract("http://public.example/start"))


def test_extract_follows_safe_redirect() -> None:
    def handler(request: httpx.Request) -> httpx.Response:
        if request.url.host == "a.example":
            return httpx.Response(301, headers={"location": "http://b.example/final"})
        return httpx.Response(200, text="<p>final page</p>")

    client = WebClient(
        provider="ddgs",
        transport=_mock(handler),
        block_private_addresses=True,
        resolver=_resolver_to("93.184.216.34"),
    )
    assert asyncio.run(client.extract("http://a.example/start")) == "final page"
