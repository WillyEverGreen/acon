"""
Real-world benchmark for acon-intel v0.1.2
Tests 4 live sites and measures discovery quality, speed, topology detection, and efficiency.
Compares Acon (intelligent) vs Blind BFS (same budget) for each site.
"""

import asyncio
import json
import time
import sys
from dataclasses import dataclass, field, asdict
from typing import Optional

# Force UTF-8 output on Windows
sys.stdout.reconfigure(encoding="utf-8")

from acon import SiteCrawlOrchestrator, CrawlConfig, SiteTopology


# ---------------------------------------------------------------------------
# Blind BFS baseline (same budget, no intelligence)
# ---------------------------------------------------------------------------

async def blind_bfs(seed_url: str, max_pages: int) -> dict:
    """Simulate a blind BFS crawl: fetch pages, extract links, no topology awareness."""
    from acon.crawlers.page_selector import LiveDOMLinkExtractor, select_links_for_enqueue
    from acon.crawlers.crawler import CrawlSession

    session = CrawlSession()
    extractor = LiveDOMLinkExtractor()
    await extractor.start()   # no stealth kwarg - plain browser

    session.enqueue(seed_url, depth=0, page_type="standard", page_weight=1.0)

    pages_crawled = 0
    pages_failed = 0
    templates_seen: set[str] = set()
    start = time.perf_counter()

    try:
        while session.has_pending and pages_crawled < max_pages:
            entry = session.dequeue_prioritized()
            if entry is None:
                break

            try:
                raw_links, _ = await asyncio.wait_for(
                    extractor.extract_links(entry.fetch_url, 10),
                    timeout=12
                )
                pages_crawled += 1

                from urllib.parse import urlparse
                path = urlparse(entry.fetch_url).path
                segs = [s for s in path.split("/") if s]
                template = "/" + "/".join(segs[:2]) if len(segs) >= 2 else (path or "/")
                templates_seen.add(template)

                links, _ = select_links_for_enqueue(
                    raw_links,
                    current_fetch_url=entry.fetch_url,
                    seed_url=seed_url,
                    next_depth=entry.depth + 1,
                    disable_sampling=True  # BFS: follow everything
                )
                for link in links:
                    session.enqueue(
                        fetch_url=link.fetch_url,
                        depth=entry.depth + 1,
                        page_type="standard",
                        page_weight=0.5
                    )
            except Exception:
                pages_failed += 1
    finally:
        await extractor.close()

    elapsed = round(time.perf_counter() - start, 2)
    return {
        "pages_crawled": pages_crawled,
        "pages_failed": pages_failed,
        "elapsed_s": elapsed,
        "templates_found": len(templates_seen),
    }


# ---------------------------------------------------------------------------
# Benchmark targets
# ---------------------------------------------------------------------------

SITES = [
    {
        "name": "Books to Scrape",
        "url": "https://books.toscrape.com",
        "budget": 20,
        "scan_mode": "fast",
        "description": "Static paginated e-commerce (golden benchmark)",
    },
    {
        "name": "Hacker News",
        "url": "https://news.ycombinator.com",
        "budget": 15,
        "scan_mode": "fast",
        "description": "Link-heavy news aggregator",
    },
    {
        "name": "PyPI",
        "url": "https://pypi.org",
        "budget": 15,
        "scan_mode": "fast",
        "description": "Complex multi-template package registry",
    },
    {
        "name": "Wikipedia (Python)",
        "url": "https://en.wikipedia.org/wiki/Python_(programming_language)",
        "budget": 12,
        "scan_mode": "fast",
        "description": "Deep-uniform encyclopedia structure",
    },
]


# ---------------------------------------------------------------------------
# Acon runner
# ---------------------------------------------------------------------------

async def run_acon_benchmark(site: dict) -> dict:
    brain = SiteCrawlOrchestrator()
    config = CrawlConfig(
        max_pages=site["budget"],
        scan_mode=site["scan_mode"],
        disable_sampling=False,
    )
    start = time.perf_counter()
    result = await brain.crawl_site(site["url"], config)
    elapsed = round(time.perf_counter() - start, 2)

    from urllib.parse import urlparse
    templates_seen: set[str] = set()
    for page in result.get("page_summaries", []):
        path = urlparse(page["url"]).path
        segs = [s for s in path.split("/") if s]
        t = "/" + "/".join(segs[:2]) if len(segs) >= 2 else (path or "/")
        templates_seen.add(t)

    meta = result.get("crawl_meta", {})
    reflection = meta.get("reflection", {})

    return {
        "pages": result.get("pages_crawled", 0),
        "failed": result.get("pages_failed", 0),
        "elapsed_s": elapsed,
        "topology": result.get("topology", "UNKNOWN"),
        "templates": len(templates_seen),
        "stop_reason": meta.get("early_stop_reason"),
        "intelligence_score": reflection.get("intelligence_score", 0.0),
        "failure_rate": reflection.get("failure_rate", 0.0),
        "advice": reflection.get("advice", ""),
    }


# ---------------------------------------------------------------------------
# Result dataclass
# ---------------------------------------------------------------------------

@dataclass
class SiteResult:
    name: str
    url: str
    description: str

    acon_pages: int = 0
    acon_failed: int = 0
    acon_elapsed_s: float = 0.0
    acon_topology: str = "UNKNOWN"
    acon_templates: int = 0
    acon_stop_reason: Optional[str] = None
    acon_intelligence_score: float = 0.0
    acon_failure_rate: float = 0.0
    acon_advice: str = ""

    bfs_pages: int = 0
    bfs_failed: int = 0
    bfs_elapsed_s: float = 0.0
    bfs_templates: int = 0

    request_reduction_pct: float = 0.0
    time_reduction_pct: float = 0.0
    template_advantage: int = 0
    outcome: str = ""


def compute_outcome(r: SiteResult) -> str:
    if r.request_reduction_pct >= 40 and r.template_advantage >= 0:
        return "ELITE"
    if r.request_reduction_pct >= 20 and r.template_advantage >= 0:
        return "PASS"
    if r.template_advantage > 0:
        return "PASS"
    if r.request_reduction_pct >= 0:
        return "STABLE"
    return "REGRESSED"


# ---------------------------------------------------------------------------
# Main runner
# ---------------------------------------------------------------------------

async def main():
    results: list[SiteResult] = []

    for site in SITES:
        print(f"\n{'='*60}")
        print(f"  Testing: {site['name']} ({site['url']})")
        print(f"  Budget:  {site['budget']} pages | Mode: {site['scan_mode']}")
        print(f"{'='*60}")

        r = SiteResult(
            name=site["name"],
            url=site["url"],
            description=site["description"],
        )

        print("  [1/2] Running Acon (intelligent)...")
        try:
            acon = await run_acon_benchmark(site)
            r.acon_pages = acon["pages"]
            r.acon_failed = acon["failed"]
            r.acon_elapsed_s = acon["elapsed_s"]
            r.acon_topology = acon["topology"]
            r.acon_templates = acon["templates"]
            r.acon_stop_reason = acon["stop_reason"]
            r.acon_intelligence_score = acon["intelligence_score"]
            r.acon_failure_rate = acon["failure_rate"]
            r.acon_advice = acon["advice"]
            print(f"     pages={r.acon_pages}  failed={r.acon_failed}  time={r.acon_elapsed_s}s  topology={r.acon_topology}  templates={r.acon_templates}")
        except Exception as e:
            print(f"     ERROR (Acon): {e}")

        print("  [2/2] Running Blind BFS (baseline)...")
        try:
            bfs = await blind_bfs(site["url"], site["budget"])
            r.bfs_pages = bfs["pages_crawled"]
            r.bfs_failed = bfs["pages_failed"]
            r.bfs_elapsed_s = bfs["elapsed_s"]
            r.bfs_templates = bfs["templates_found"]
            print(f"     pages={r.bfs_pages}  failed={r.bfs_failed}  time={r.bfs_elapsed_s}s  templates={r.bfs_templates}")
        except Exception as e:
            print(f"     ERROR (BFS): {e}")

        if r.bfs_pages > 0:
            r.request_reduction_pct = round((1 - r.acon_pages / r.bfs_pages) * 100, 1)
        r.time_reduction_pct = round(
            (1 - r.acon_elapsed_s / r.bfs_elapsed_s) * 100, 1
        ) if r.bfs_elapsed_s > 0 else 0.0
        r.template_advantage = r.acon_templates - r.bfs_templates
        r.outcome = compute_outcome(r)

        results.append(r)
        print(f"  => Req reduction: {r.request_reduction_pct:+.1f}%  Time reduction: {r.time_reduction_pct:+.1f}%  Template advantage: {r.template_advantage:+d}  [{r.outcome}]")

    print(f"\n\n{'='*80}")
    print("  FINAL BENCHMARK RESULTS - acon-intel v0.1.2")
    print(f"{'='*80}")
    print(f"{'Site':<22} {'Req.Red%':>9} {'Time Red%':>10} {'Tpl+':>6} {'Topology':<18} {'Result'}")
    print(f"{'-'*80}")
    for r in results:
        print(
            f"{r.name:<22} {r.request_reduction_pct:>+8.1f}%"
            f" {r.time_reduction_pct:>+9.1f}%"
            f" {r.template_advantage:>+6d}"
            f"  {r.acon_topology:<18}"
            f"  {r.outcome}"
        )
    print(f"{'='*80}")

    with open("benchmark_results.json", "w", encoding="utf-8") as f:
        json.dump([asdict(r) for r in results], f, indent=2)
    print("\nRaw results saved to benchmark_results.json")

    return results


if __name__ == "__main__":
    results = asyncio.run(main())
