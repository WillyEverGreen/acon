import asyncio
import time
import sys
import os
import httpx
from typing import Any, List, Set, Tuple
from dataclasses import dataclass
from urllib.parse import urljoin, urlparse
from bs4 import BeautifulSoup

# Add the current directory to path
sys.path.append(os.path.dirname(os.path.abspath(__file__)))

from crawlers.crawl_orchestrator import SiteCrawlOrchestrator, CrawlConfig

@dataclass
class BenchmarkMetrics:
    pages_crawled: int
    time_taken: float
    bandwidth_mb: float
    templates_found: int
    efficiency: float
    proxy_cost: float

def classify_page_type(url: str) -> str:
    """Semantic page type classifier for honest template counting."""
    path = urlparse(url).path.lower()
    if path == '/' or path == '' or path == '/index.html':
        return 'home'
    elif 'page-' in path: # Check pagination first (it often sits inside categories)
        return 'pagination'
    elif 'category' in path:
        return 'category'
    elif 'catalogue/' in path:
        return 'product'
    else:
        return 'other'

async def run_blind_bfs(start_url: str, limit: int = 1000) -> Tuple[int, float, float, int]:
    """Real, honest Standard BFS crawler."""
    visited: Set[str] = set()
    queue: List[str] = [start_url]
    total_bytes = 0
    templates: Set[str] = set()
    start_time = time.perf_counter()
    domain = urlparse(start_url).netloc
    
    print(f"[Blind] Starting real BFS (Limit: {limit} pages)...")
    
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        while queue and len(visited) < limit:
            url = queue.pop(0)
            if url in visited:
                continue
            
            try:
                response = await client.get(url)
                if response.status_code != 200:
                    continue
                
                total_bytes += len(response.content)
                visited.add(url)
                
                templates.add(classify_page_type(url))
                
                soup = BeautifulSoup(response.text, 'html.parser')
                for a in soup.find_all('a', href=True):
                    href = a['href']
                    full_url = urljoin(url, href)
                    parsed_full = urlparse(full_url)
                    if parsed_full.netloc == domain and parsed_full.scheme in ('http', 'https'):
                        clean_url = full_url.split('#')[0].split('?')[0].rstrip('/')
                        if clean_url not in visited and clean_url not in queue:
                            queue.append(clean_url)
                
                if len(visited) % 100 == 0:
                    print(f" - [Blind] Progress: {len(visited)}/{limit} pages...")
                    
            except Exception:
                continue
                
    duration = time.perf_counter() - start_time
    return len(visited), duration, total_bytes / (1024 * 1024), len(templates)

async def run_acon_brain(start_url: str, budget: int = 40) -> Tuple[int, float, float, int]:
    """Acon Discovery run."""
    print(f"[Acon] Starting Acon Discovery (Budget: {budget} pages)...")
    brain = SiteCrawlOrchestrator()
    start_time = time.perf_counter()
    
    targets = await brain.recommend_targets(start_url, budget=budget)
    
    total_bytes = 0
    async with httpx.AsyncClient(timeout=10.0, follow_redirects=True) as client:
        tasks = [client.get(url) for url in targets]
        responses = await asyncio.gather(*tasks, return_exceptions=True)
        for res in responses:
            if isinstance(res, httpx.Response):
                total_bytes += len(res.content)
    
    duration = time.perf_counter() - start_time
    templates = {classify_page_type(u) for u in targets}
    
    return len(targets), duration, total_bytes / (1024 * 1024), len(templates)

async def main():
    TARGET_URL = "https://books.toscrape.com/"
    BLIND_LIMIT = 1000 
    ACON_BUDGET = 40
    
    print("=============================================")
    print("       HONEST ELITE BENCHMARK (LIVE)         ")
    print("=============================================\n")
    print("Note: Standard BFS will crawl up to 1000 pages to reach completion.")
    print(">>> THE WAIT IS THE POINT. <<<\n")

    # --- 1. RUN BLIND BFS ---
    blind_pages, blind_time, blind_mb, blind_templates = await run_blind_bfs(TARGET_URL, limit=BLIND_LIMIT)
    
    # --- 2. RUN ACON BRAIN ---
    print("\n" + "-"*45)
    acon_pages, acon_time, acon_mb, acon_templates = await run_acon_brain(TARGET_URL, budget=ACON_BUDGET)
    
    # --- 3. COMPARE ---
    print("\n" + "="*60)
    print(f"{'Metric':<25} | {'Standard BFS':<15} | {'Acon (Brain)'}")
    print("-" * 60)
    print(f"{'Pages Crawled':<25} | {blind_pages:<15} | {acon_pages}")
    print(f"{'Time Taken':<25} | {blind_time:<15.1f}s | {acon_time:.1f}s")
    print(f"{'Bandwidth Used':<25} | {blind_mb:<15.2f}MB | {acon_mb:.2f}MB")
    print(f"{'Est. Proxy Cost':<25} | ${blind_pages * 0.001:<14.3f} | ${acon_pages * 0.001:.3f}")
    print(f"{'Semantic Types Found':<25} | {blind_templates:<15} | {acon_templates}")
    print(f"{'Discovery Efficiency':<25} | {blind_templates/blind_pages*100:<14.1f}% | {acon_templates/acon_pages*100:.1f}%")
    print("-" * 60)
    
    reduction = (1 - (acon_pages / blind_pages)) * 100
    print(f"REDUCTION: {reduction:.1f}% less crawling.")
    print(f"DNA SPEED: Acon was { (acon_templates/acon_pages) / (blind_templates/blind_pages) :.1f}x more efficient at structural discovery.")
    print("="*60)

if __name__ == "__main__":
    asyncio.run(main())
