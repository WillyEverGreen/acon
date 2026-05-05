import asyncio
import os
import json
from acon import SiteCrawlOrchestrator, CrawlConfig
from acon.utils.scrapling_adapter import generate_scrapling_script

async def run_alliance_demo():
    """
    Demonstrates the Acon Alliance:
    1. Content Pillar: Trafilatura for Markdown extraction
    2. Stealth Pillar: Camoufox for anti-bot bypass
    3. Speed Pillar: Scrapling adapter for high-speed export
    """
    print("🚀 Initializing Acon Alliance Demo...")
    
    # Target site (Hacker News is a good example of link-heavy/content-rich mix)
    target_url = "https://news.ycombinator.com"
    
    # 1. Configure the Alliance
    config = CrawlConfig(
        max_pages=3,           # Small crawl for demo
        extract_content=True,  # Pillar 1: Trafilatura
        use_stealth=True,      # Pillar 2: Camoufox
        scan_mode="fast"
    )
    
    brain = SiteCrawlOrchestrator()
    
    print(f"📡 Crawling {target_url} with full intelligence stack...")
    result = await brain.crawl_site(target_url, config)
    
    print("\n--- RESULTS ---")
    print(f"Total Pages: {result['pages_crawled']}")
    
    for i, page in enumerate(result["page_summaries"]):
        url = page.get("url")
        content = page.get("content")
        print(f"\n[Page {i+1}] {url}")
        if content:
            print(f"✅ Extracted Markdown ({len(content)} chars)")
            print(f"   Snippet: {content[:100].replace('\\n', ' ')}...")
        else:
            print("❌ No content extracted.")
            
    # 2. Pillar 3: Speed Export (Scrapling)
    # Generate a high-speed extraction script based on discovered topology
    export_path = "scrapling_export_demo.py"
    generate_scrapling_script(result, export_path)
    print(f"\n⚡ Pillar 3: Scrapling adapter script generated at: {export_path}")
    print("   You can run this script to perform high-speed mass extraction of the site.")

if __name__ == "__main__":
    # Ensure Playwright browsers are installed
    # os.system("playwright install chromium")
    
    asyncio.run(run_alliance_demo())
