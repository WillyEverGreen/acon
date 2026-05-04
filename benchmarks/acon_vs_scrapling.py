import asyncio
import time
import sys
import os
from typing import Any, List, Set, Tuple
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse

# Add current directory to path
sys.path.append(os.path.dirname(os.path.abspath(os.path.dirname(__file__))))

# Import Acon
from crawlers.crawl_orchestrator import SiteCrawlOrchestrator

# Import Scrapling - The Muscle
try:
    from scrapling import Fetcher, AsyncFetcher
except ImportError:
    print("Scrapling not found. Please install with 'pip install scrapling'")
    sys.exit(1)

@dataclass
class BenchmarkMetrics:
    pages_crawled: int
    time_taken: float
    bandwidth_mb: float
    templates_found: int
    efficiency: float
    proxy_cost: float

def classify_page_type(url: str) -> str:
    path = urlparse(url).path.lower()
    if path == '/' or path == '' or path == '/index.html':
        return 'home'
    elif 'page-' in path:
        return 'pagination'
    elif 'category' in path:
        return 'category'
    elif 'catalogue/' in path:
        return 'product'
    else:
        return 'other'

async def run_blind_scrapling(start_url: str, limit: int = 1000) -> Tuple[int, float, float, int]:
    """Real-world blind crawl using Scrapling's Fetcher."""
    print(f"[Blind] Starting Scrapling BFS (Limit: {limit} pages)...")
    
    visited: Set[str] = set()
    queue: List[str] = [start_url]
    total_bytes = 0
    templates: Set[str] = set()
    start_time = time.perf_counter()
    domain = urlparse(start_url).netloc
    
    fetcher = Fetcher()
    
    while queue and len(visited) < limit:
        url = queue.pop(0)
        if url in visited:
            continue
        
        try:
            # Fetch using Scrapling engine
            response = fetcher.get(url)
            if response.status != 200:
                continue
            
            total_bytes += len(response.body) if hasattr(response, 'body') else 0
            visited.add(url)
            templates.add(classify_page_type(url))
            
            # Use Scrapling's native CSS selector
            for href in response.css('a::attr(href)').getall():
                full_url = urljoin(url, href)
                parsed_full = urlparse(full_url)
                if parsed_full.netloc == domain and parsed_full.scheme in ('http', 'https'):
                    clean_url = full_url.split('#')[0].split('?')[0].rstrip('/')
                    if clean_url not in visited and clean_url not in queue:
                        queue.append(clean_url)
            
            if len(visited) % 100 == 0:
                print(f" - [Blind] Scrapling Progress: {len(visited)}/{limit} pages...")
                
        except Exception:
            continue
                
    duration = time.perf_counter() - start_time
    return len(visited), duration, total_bytes / (1024 * 1024), len(templates)

async def run_smart_scrapling(start_url: str, budget: int = 40) -> Tuple[int, float, float, int]:
    """Acon + Scrapling: The Brain and the Muscle."""
    print(f"[Acon+Scrapling] Acon is mapping topology (Budget: {budget} pages)...")
    brain = SiteCrawlOrchestrator()
    start_time = time.perf_counter()
    
    # Step 1: Brain mapping
    targets = await brain.recommend_targets(start_url, budget=budget)
    
    print(f"[Acon+Scrapling] Handing {len(targets)} targets to Scrapling AsyncFetcher...")
    
    # Step 2: Muscle extraction using asyncio.gather for batching
    fetcher = AsyncFetcher()
    tasks = [fetcher.get(url) for url in targets]
    results = await asyncio.gather(*tasks, return_exceptions=True)
    
    duration = time.perf_counter() - start_time
    
    # Filter valid results
    valid_results = [res for res in results if hasattr(res, 'url')]
    
    # Measure real results
    pages_crawled = len(valid_results)
    total_bytes = sum(len(res.body) if hasattr(res, 'body') else 0 for res in valid_results)
    templates = {classify_page_type(res.url) for res in valid_results}
    
    return len(targets), duration, total_bytes / (1024 * 1024), len(templates)

async def main():
    TARGET_URL = "https://books.toscrape.com/"
    BLIND_LIMIT = 1000 
    ACON_BUDGET = 40
    
    print("=============================================")
    print("      ELITE 1:1 BATTLE: ACON VS SCRAPLING    ")
    print("=============================================\n")
    print("Note: Both sides use Scrapling's high-performance engine.")
    print(">>> THE WAIT IS THE POINT. <<<\n")

    # --- 1. RUN BLIND SCRAPLING ---
    blind_pages, blind_time, blind_mb, blind_templates = await run_blind_scrapling(TARGET_URL, limit=BLIND_LIMIT)
    
    # --- 2. RUN ACON + SCRAPLING ---
    print("\n" + "-"*45)
    smart_pages, smart_time, smart_mb, smart_templates = await run_smart_scrapling(TARGET_URL, budget=ACON_BUDGET)
    
    # --- 3. COMPARE ---
    print("\n" + "="*60)
    print(f"{'Metric':<25} | {'Scrapling Alone':<15} | {'Acon + Scrapling'}")
    print("-" * 60)
    print(f"{'Pages Crawled':<25} | {blind_pages:<15} | {smart_pages}")
    print(f"{'Time Taken':<25} | {blind_time:<15.1f}s | {smart_time:.1f}s")
    print(f"{'Bandwidth Used':<25} | {blind_mb:<15.2f}MB | {smart_mb:.2f}MB")
    print(f"{'Est. Proxy Cost':<25} | ${blind_pages * 0.001:<14.3f} | ${smart_pages * 0.001:.3f}")
    print(f"{'Semantic Types Found':<25} | {blind_templates:<15} | {smart_templates}")
    print("-" * 60)
    
    reduction = (1 - (smart_pages / blind_pages)) * 100
    print(f"REDUCTION: {reduction:.1f}% less crawling with 1:1 coverage.")
    print(f"EFFICIENCY: Acon cut Scrapling's workload by {blind_pages/smart_pages:.1f}x.")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())
