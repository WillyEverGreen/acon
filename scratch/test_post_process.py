import asyncio
import sys
import os

# Add current dir to path to find 'acon' package
sys.path.append(os.getcwd())

async def post_process_test():
    from acon import SiteCrawlOrchestrator, CrawlConfig
    
    # Mock post_process: just count characters
    def mock_extractor(html):
        return f"Length: {len(html)}"
    
    config = CrawlConfig(
        max_pages=2,
        post_process=mock_extractor
    )
    
    orchestrator = SiteCrawlOrchestrator()
    # Using a reliable site for testing
    result = await orchestrator.crawl_site("https://example.com", config)
    
    print(f"Status: {result['crawl_status']}")
    for page in result["page_summaries"]:
        print(f"URL: {page['url']}")
        print(f"Post-process Result: {page['result']}")
        if "Length:" not in str(page['result']):
            print("FAILED: Post-process result missing or incorrect")
            sys.exit(1)
            
    print("SUCCESS: Post-process verified!")

if __name__ == "__main__":
    asyncio.run(post_process_test())
