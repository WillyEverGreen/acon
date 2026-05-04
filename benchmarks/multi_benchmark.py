import asyncio
import sys
import os
import time
import json
from typing import Any, List, Dict

# Add the current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from crawlers.crawl_orchestrator import SiteCrawlOrchestrator, CrawlConfig

# Standard handler for the benchmark
async def benchmark_handler(url, **kwargs):
    # Minimal sleep to simulate real-world processing latency
    await asyncio.sleep(0.01)
    return {"fetch_status": "success", "url": url, "data": []}

SITES_TO_TEST = [
    {"url": "https://quotes.toscrape.com/", "type": "Content", "mode": "fast"},
    {"url": "https://books.toscrape.com/", "type": "E-commerce", "mode": "fast"},
    {"url": "http://crawler-test.com/", "type": "Crawler Specific", "mode": "fast"},
    {"url": "https://news.ycombinator.com/", "type": "News/Forum", "mode": "fast"},
    {"url": "https://en.wikipedia.org/wiki/Python_(programming_language)", "type": "Wiki", "mode": "fast"},
    {"url": "https://toscrape.com/", "type": "Scraping Sandbox", "mode": "fast"},
    {"url": "http://example.com/", "type": "Minimal", "mode": "fast"},
    {"url": "http://scrapethissite.com/pages/forms/", "type": "Directory", "mode": "fast"},
    # JS-heavy sites (using deep mode)
    {"url": "https://github.com/trending", "type": "Developer Tool", "mode": "deep"},
    {"url": "https://www.reddit.com/r/Python/", "type": "Social", "mode": "deep"},
]

async def run_single_benchmark(site_info: Dict[str, str], budget: int = 15) -> Dict[str, Any]:
    url = site_info["url"]
    print(f"\n[Benchmarking] {url} ({site_info['type']})")
    sys.stdout.flush()
    
    # 1. Run Standard BFS (Sampling Disabled)
    std_cfg = CrawlConfig(
        max_pages=budget,
        max_depth=3,
        disable_sampling=True,
        scan_mode=site_info["mode"]
    )
    orchestrator_std = SiteCrawlOrchestrator(fetch_callable=benchmark_handler)
    start_std = time.perf_counter()
    try:
        res_std = await asyncio.wait_for(orchestrator_std.crawl_site(url, std_cfg), timeout=120)
    except Exception as e:
        print(f"  Standard BFS Error: {e}")
        res_std = {"pages_crawled": 0, "crawl_status": "failed"}
    duration_std = time.perf_counter() - start_std

    # 2. Run Acon (Sampling Enabled)
    acon_cfg = CrawlConfig(
        max_pages=budget,
        max_depth=3,
        disable_sampling=False,
        scan_mode=site_info["mode"]
    )
    orchestrator_acon = SiteCrawlOrchestrator(fetch_callable=benchmark_handler)
    start_acon = time.perf_counter()
    try:
        res_acon = await asyncio.wait_for(orchestrator_acon.crawl_site(url, acon_cfg), timeout=120)
    except Exception as e:
        print(f"  Acon Error: {e}")
        res_acon = {"pages_crawled": 0, "crawl_status": "failed"}
    duration_acon = time.perf_counter() - start_acon

    # 3. Calculate Results
    req_std = res_std.get("pages_crawled", 0)
    req_acon = res_acon.get("pages_crawled", 0)
    
    saved = max(0, req_std - req_acon)
    efficiency = (saved / req_std * 100) if req_std > 0 else 0
    
    result = {
        "site": url,
        "type": site_info["type"],
        "mode": site_info["mode"],
        "req_std": req_std,
        "req_acon": req_acon,
        "saved": saved,
        "efficiency": f"{efficiency:.1f}%",
        "duration_std": f"{duration_std:.2f}s",
        "duration_acon": f"{duration_acon:.2f}s"
    }
    
    print(f"  Result: {req_std} std vs {req_acon} acon | Saved: {saved} ({result['efficiency']})")
    sys.stdout.flush()
    return result

async def main():
    budget_per_site = 30
    all_results = []
    
    print("=== Acon Multi-Site Credibility Benchmark ===")
    print(f"Testing {len(SITES_TO_TEST)} sites with budget of {budget_per_site} pages each.")
    sys.stdout.flush()
    
    for site in SITES_TO_TEST:
        try:
            res = await run_single_benchmark(site, budget=budget_per_site)
            all_results.append(res)
        except Exception as e:
            print(f"  Critical Failure for {site['url']}: {e}")
            sys.stdout.flush()

    # Output final summary table
    print("\n" + "="*80)
    print(f"{'Site':<30} | {'Type':<15} | {'Saved':<6} | {'Efficiency'}")
    print("-" * 80)
    
    valid_efficiencies = []
    for r in all_results:
        print(f"{r['site'][:30]:<30} | {r['type']:<15} | {r['saved']:<6} | {r['efficiency']}")
        if r['req_std'] > 0:
            eff = float(r['efficiency'].strip('%'))
            valid_efficiencies.append(eff)
    
    if valid_efficiencies:
        avg_eff = sum(valid_efficiencies) / len(valid_efficiencies)
        print("-" * 80)
        print(f"{'AVERAGE':<53} | {avg_eff:.1f}%")
    
    print("="*80)
    sys.stdout.flush()
    
    # Save to file
    with open("multi_site_benchmark.json", "w") as f:
        json.dump(all_results, f, indent=2)
    print("\nResults saved to multi_site_benchmark.json")

if __name__ == "__main__":
    try:
        asyncio.run(main())
    except KeyboardInterrupt:
        print("\nBenchmark aborted.")
