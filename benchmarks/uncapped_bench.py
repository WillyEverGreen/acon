"""
The CORRECT Acon benchmark: uncapped budget test.

Question: How many pages does each engine need to FULLY MAP a site's structure?
  - BFS: crawls until its ceiling (200p) or queue exhaustion
  - Acon: crawls until low_information_gain fires (structure is fully mapped)

This reveals Acon's real value: it STOPS when the DNA is learned.
"""

import asyncio
import sys
import time

sys.stdout.reconfigure(encoding="utf-8")

from acon import SiteCrawlOrchestrator, CrawlConfig


SITES = [
    {
        "name": "books.toscrape.com",
        "url": "https://books.toscrape.com",
        "bfs_budget": 200,   # uncapped BFS ceiling
        "acon_budget": 200,  # Acon will early-stop long before this
    },
    {
        "name": "PyPI",
        "url": "https://pypi.org",
        "bfs_budget": 100,
        "acon_budget": 100,
    },
    {
        "name": "Hacker News",
        "url": "https://news.ycombinator.com",
        "bfs_budget": 50,
        "acon_budget": 50,
    },
    {
        "name": "Wikipedia",
        "url": "https://en.wikipedia.org/wiki/Main_Page",
        "bfs_budget": 100,
        "acon_budget": 100,
    },
]


async def run_bfs_uncapped(url: str, max_pages: int) -> dict:
    """BFS: no intelligence, no early stop. Runs until queue empty or budget hit."""
    from acon.crawlers.page_selector import LiveDOMLinkExtractor, select_links_for_enqueue
    from acon.crawlers.crawler import CrawlSession
    from urllib.parse import urlparse

    session = CrawlSession()
    extractor = LiveDOMLinkExtractor()
    await extractor.start()
    session.enqueue(url, depth=0, page_type="standard", page_weight=1.0)

    pages = 0
    templates: set[str] = set()
    start = time.perf_counter()

    try:
        while session.has_pending and pages < max_pages:
            entry = session.dequeue_prioritized()
            if not entry:
                break
            try:
                raw_links, _ = await asyncio.wait_for(
                    extractor.extract_links(entry.fetch_url, 10), timeout=12
                )
                pages += 1
                path = urlparse(entry.fetch_url).path
                segs = [s for s in path.split("/") if s]
                templates.add("/" + "/".join(segs[:2]) if len(segs) >= 2 else path or "/")

                links, _ = select_links_for_enqueue(
                    raw_links, current_fetch_url=entry.fetch_url,
                    seed_url=url, next_depth=entry.depth + 1, disable_sampling=True,
                )
                for link in links:
                    session.enqueue(link.fetch_url, depth=entry.depth + 1,
                                    page_type="standard", page_weight=0.5)
            except Exception:
                pass
    finally:
        await extractor.close()

    return {
        "pages": pages,
        "templates": len(templates),
        "elapsed_s": round(time.perf_counter() - start, 1),
        "stopped_by": "queue_empty" if not session.has_pending else "budget_cap",
    }


async def run_acon_uncapped(url: str, max_pages: int) -> dict:
    """Acon: full intelligence, will early-stop when structure is learned."""
    brain = SiteCrawlOrchestrator()
    config = CrawlConfig(
        max_pages=max_pages,
        scan_mode="fast",
        disable_sampling=False,
        # Low-information-gain detection is ON by default
        # It fires when new unique signals / total_unique < 5% over 3-page window
    )
    start = time.perf_counter()
    result = await brain.crawl_site(url, config)
    elapsed = round(time.perf_counter() - start, 1)

    from urllib.parse import urlparse
    templates: set[str] = set()
    for page in result.get("page_summaries", []):
        path = urlparse(page["url"]).path
        segs = [s for s in path.split("/") if s]
        templates.add("/" + "/".join(segs[:2]) if len(segs) >= 2 else path or "/")

    meta = result.get("crawl_meta", {})
    return {
        "pages": result.get("pages_crawled", 0),
        "templates": len(templates),
        "elapsed_s": elapsed,
        "topology": result.get("topology"),
        "stopped_by": meta.get("early_stop_reason") or "budget_cap",
    }


async def main():
    print("\n  THE RIGHT BENCHMARK: Uncapped budget, who stops first?\n")
    print(f"  {'Site':<22} {'Method':<10} {'Pages':>6} {'Time':>8}  {'Stopped by':<25} {'Tpl'}")
    print(f"  {'-'*80}")

    for site in SITES:
        print(f"\n  Testing {site['name']}...")

        # BFS first
        print("    Running BFS (no intelligence, no early stop)...")
        bfs = await run_bfs_uncapped(site["url"], site["bfs_budget"])
        print(f"    BFS done: {bfs['pages']}p / {bfs['elapsed_s']}s / {bfs['stopped_by']}")

        # Acon
        print("    Running Acon (intelligence ON, adaptive early stop)...")
        acon = await run_acon_uncapped(site["url"], site["acon_budget"])
        print(f"    Acon done: {acon['pages']}p / {acon['elapsed_s']}s / {acon['stopped_by']}")

        reduction = round((1 - acon["pages"] / bfs["pages"]) * 100, 1) if bfs["pages"] else 0
        time_saved = round((1 - acon["elapsed_s"] / bfs["elapsed_s"]) * 100, 1) if bfs["elapsed_s"] else 0

        print(f"\n  {site['name']:<22} {'BFS':<10} {bfs['pages']:>6} {bfs['elapsed_s']:>7}s  {bfs['stopped_by']:<25} {bfs['templates']}")
        print(f"  {'':<22} {'Acon':<10} {acon['pages']:>6} {acon['elapsed_s']:>7}s  {acon['stopped_by']:<25} {acon['templates']}")
        print(f"\n  => REQUEST REDUCTION: {reduction:+.1f}%   TIME SAVED: {time_saved:+.1f}%   TOPOLOGY: {acon['topology']}")


if __name__ == "__main__":
    asyncio.run(main())
