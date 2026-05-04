import asyncio
import sys
import os
import time
from typing import Any

# Add the current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from crawlers.crawl_orchestrator import SiteCrawlOrchestrator, CrawlConfig

async def benchmark_handler(url, **kwargs):
    # Simulate processing
    await asyncio.sleep(0.05)
    return {
        "fetch_status": "success",
        "url": url,
        "data": []
    }

async def run_benchmark():
    target_url = "https://quotes.toscrape.com/"
    max_pages = 25
    
    print(f"Starting Acon Benchmark")
    print(f"Target: {target_url}")
    print(f"Budget: {max_pages} pages")
    print("-" * 50)

    # 1. Run Standard BFS (Acon with sampling DISABLED)
    print("Running Standard BFS (Sampling Disabled)...")
    standard_cfg = CrawlConfig(
        max_pages=max_pages,
        max_depth=3,
        disable_sampling=True,
        scan_mode="fast"
    )
    orchestrator_std = SiteCrawlOrchestrator(fetch_callable=benchmark_handler)
    
    start_std = time.perf_counter()
    res_std = await orchestrator_std.crawl_site(target_url, standard_cfg)
    end_std = time.perf_counter()
    
    # 2. Run Acon (Sampling ENABLED)
    print("\nRunning Acon (Topology-Aware Sampling Enabled)...")
    acon_cfg = CrawlConfig(
        max_pages=max_pages,
        max_depth=3,
        disable_sampling=False,
        scan_mode="fast"
    )
    orchestrator_acon = SiteCrawlOrchestrator(fetch_callable=benchmark_handler)
    
    start_acon = time.perf_counter()
    res_acon = await orchestrator_acon.crawl_site(target_url, acon_cfg)
    end_acon = time.perf_counter()

    # 3. Analyze Results
    print("\n" + "="*50)
    print("BENCHMARK RESULTS")
    print("="*50)
    
    def analyze_diversity(results):
        types = {}
        for p in results['page_summaries']:
            ptype = p['page_type']
            types[ptype] = types.get(ptype, 0) + 1
        return types

    div_std = analyze_diversity(res_std)
    div_acon = analyze_diversity(res_acon)

    print(f"{'Metric':<25} | {'Standard BFS':<15} | {'Acon'}")
    print("-" * 55)
    print(f"{'Total Requests':<25} | {res_std['pages_crawled']:<15} | {res_acon['pages_crawled']}")
    print(f"{'Duration (s)':<25} | {end_std-start_std:<15.2f} | {end_acon-start_acon:.2f}")
    
    print("\nPage Type Discovery (Diversity):")
    all_types = sorted(set(list(div_std.keys()) + list(div_acon.keys())))
    for t in all_types:
        print(f" - {t:<22} | {div_std.get(t, 0):<15} | {div_acon.get(t, 0)}")

    print("\nAnalysis:")
    if res_acon['pages_crawled'] < res_std['pages_crawled']:
        saved = ((res_std['pages_crawled'] - res_acon['pages_crawled']) / res_std['pages_crawled']) * 100
        print(f"Acon saved {saved:.1f}% in requests by avoiding redundant templates.")
    else:
        print("Acon visited the same number of pages (site structure might be small or budget reached).")

    print("\nNote: Acon prioritizes discovering new page types (Nav, Interaction) over deep standard page crawling.")
    print("="*50)

if __name__ == "__main__":
    try:
        asyncio.run(run_benchmark())
    except KeyboardInterrupt:
        print("\nBenchmark stopped.")
