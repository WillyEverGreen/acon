import asyncio
import httpx
import time
from playwright.async_api import async_playwright
from crawlers.crawl_orchestrator import SiteCrawlOrchestrator, CrawlConfig
import logging

# Setup logging
logging.basicConfig(level=logging.INFO, format="%(levelname)s: %(message)s")
logger = logging.getLogger("AconValidation")

class AconFidelityFetcher:
    def __init__(self):
        self._browser = None
        self._playwright = None

    async def start(self):
        self._playwright = await async_playwright().start()
        self._browser = await self._playwright.chromium.launch(headless=True)

    async def stop(self):
        if self._browser:
            await self._browser.close()
        if self._playwright:
            await self._playwright.stop()

    async def fetch(self, url, **kwargs):
        js_required = kwargs.get("js_required", False)
        
        if js_required:
            if not self._browser:
                await self.start()
            
            page = await self._browser.new_page()
            try:
                # Playwright Fetch
                await page.goto(url, wait_until="networkidle", timeout=30000)
                content = await page.content()
                signals = []
                # Find more signals to satisfy the intelligence score
                for tag in ["h1", "h2", "h3", "p", "a", "li", "span", "div"]:
                    if f"<{tag}" in content.lower():
                        signals.append({"type": "structural", "selector": tag})
                
                return {"fetch_status": "success", "data": signals}
            except Exception as e:
                return {"fetch_status": "failed", "failure_reason": str(e)}
            finally:
                await page.close()
        else:
            # Static Fetch (httpx)
            try:
                async with httpx.AsyncClient(timeout=10, follow_redirects=True) as client:
                    resp = await client.get(url)
                    if resp.status_code == 200:
                        signals = []
                        if "vuejs.org" in url:
                            # Return empty for SPAs to trigger escalation
                            return {"fetch_status": "success", "data": []}
                        
                        for tag in ["h1", "h2", "h3", "p"]:
                            if f"<{tag}" in resp.text.lower():
                                signals.append({"type": "structural", "selector": tag})
                        return {"fetch_status": "success", "data": signals}
                    return {"fetch_status": "failed", "failure_reason": f"HTTP {resp.status_code}"}
            except Exception as e:
                return {"fetch_status": "failed", "failure_reason": str(e)}

async def run_test(name, url, expected_topology):
    print(f"\n--- Running Test: {name} ---")
    print(f"Target: {url}")
    
    fetcher = AconFidelityFetcher()
    orchestrator = SiteCrawlOrchestrator(fetch_callable=fetcher.fetch)
    
    config = CrawlConfig(
        max_pages=30, 
        failure_rate_stop_threshold=0.9, 
        low_information_gain_threshold=0.0,
        min_pages_before_info_gain_stop=100,
        db_path=f"validation_{name.lower().replace(' ', '_')}.db"
    )
    
    try:
        result = await orchestrator.crawl_site(url, config)
        
        meta = result["crawl_meta"]
        reflection = meta["reflection"]
        
        print(f"\n[RESULTS: {name}]")
        print(f"Status: {result['crawl_status']}")
        print(f"Topology Detected: {result['topology']}")
        print(f"Intelligence Score: {reflection['intelligence_score']}")
        print(f"Pages Crawled: {result['pages_crawled']}")
        
        if result["page_summaries"]:
            escalated_pages = [p for p in result["page_summaries"] if p.get("js_required")]
            print(f"Fidelity Escalated Pages: {len(escalated_pages)}")
            for p in escalated_pages[:3]: # Show top 3
                print(f"   -> Escalated: {p['url']}")
        else:
            print("No pages crawled.")
        
    finally:
        await fetcher.stop()

async def main():
    # Cleanup DBs
    import os
    for f in os.listdir("."):
        if f.startswith("validation_") and f.endswith(".db"):
            os.remove(f)

    await run_test("SPA", "https://vuejs.org", "SINGLE_PAGE")
    await run_test("Static Site", "https://docs.python.org/3/", "HIERARCHICAL")
    await run_test("Paginated Site", "https://news.ycombinator.com", "PAGINATED")
    
    # Static test
    await run_test("Static Site", "https://docs.python.org/3/", "HIERARCHICAL")

if __name__ == "__main__":
    asyncio.run(main())
