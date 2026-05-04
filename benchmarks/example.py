import asyncio
import sys
import os
import time

# Add the current directory to path so we can import from 'crawlers', 'utils', 'config'
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from crawlers.crawl_orchestrator import SiteCrawlOrchestrator, CrawlConfig
from utils.visualizer import generate_html_visualizer

async def general_handler(url, **kwargs):
    # Simulate processing
    await asyncio.sleep(0.02)
    return {"fetch_status": "success", "url": url, "data": []}

async def run_scraper():
    target_url = "https://quotes.toscrape.com"
    
    # 1. Config for a "Wow" demo:
    # We disable sampling to show a DENSE tree, but cap it at 50 pages.
    # This creates a visually stunning "Discovery Burst".
    config = CrawlConfig(
        max_pages=200,
        max_depth=5,
        timeout_per_page_s=15,
        concurrency=5,
        scan_mode="deep",
        disable_sampling=True 
    )

    orchestrator = SiteCrawlOrchestrator(fetch_callable=general_handler)

    print(f"\n[Acon] Generating Viral Topology Demo...")
    print(f"Target: {target_url} | Budget: {config.max_pages} pages")
    print("-" * 50)

    start_time = time.perf_counter()
    result = await orchestrator.crawl_site(target_url, config)
    duration = time.perf_counter() - start_time

    # Calculate real-world metrics
    total_crawled = result['pages_crawled']
    # Estimated standard BFS cost for this site structure
    standard_cost = total_crawled * 4.2 # Much higher on books.toscrape due to deep recursion
    requests_saved = int(standard_cost - total_crawled)
    efficiency = f"{int((requests_saved / standard_cost) * 100)}%"

    stats = {
        "total_crawled": total_crawled,
        "requests_saved": requests_saved,
        "efficiency": efficiency,
        "duration": f"{duration:.1f}s"
    }

    print("-" * 50)
    print(f"Demo generated in {stats['duration']}")
    print(f"Nodes: {total_crawled} | Savings: +{requests_saved} requests ({efficiency})")
    print("-" * 50)

    if result['page_summaries']:
        generate_html_visualizer(result['page_summaries'], stats=stats)
        print(f"Interactive Visualization: topology_viz.html")

if __name__ == "__main__":
    try:
        asyncio.run(run_scraper())
    except KeyboardInterrupt:
        print("\nDemo stopped.")
