"""Live web research smoke test (network-dependent; NOT part of pytest).

Performs one real search + extract against the configured provider (default: keyless DuckDuckGo).

    uv run --no-project python web_smoke.py "claude code pricing"
    WEB_SEARCH_PROVIDER=tavily TAVILY_API_KEY=... uv run --no-project python web_smoke.py "ai agent startups"
"""

from __future__ import annotations

import asyncio
import os
import sys

from web import WebClient, format_results


async def main() -> None:
    query = sys.argv[1] if len(sys.argv) > 1 else "early stage startup tools"
    provider = os.environ.get("WEB_SEARCH_PROVIDER", "ddgs").strip().lower()
    api_key = os.environ.get("TAVILY_API_KEY" if provider == "tavily" else "EXA_API_KEY", "").strip()

    client = WebClient(provider=provider, api_key=api_key)
    print(f"provider={provider!r} query={query!r}\n")

    results = await client.search(query, k=5)
    print(format_results(results))

    if results:
        url = results[0].url
        print(f"\n--- extract of {url} ---\n")
        print((await client.extract(url))[:1000])


if __name__ == "__main__":
    asyncio.run(main())
