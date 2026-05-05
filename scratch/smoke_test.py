import asyncio
import sys
import os

# Add current dir to path to find 'acon' package
sys.path.append(os.getcwd())

async def smoke_test():
    try:
        from acon import SiteCrawlOrchestrator, CrawlConfig
        print("Import successful!")
        
        # Quick check of classes
        orchestrator = SiteCrawlOrchestrator()
        config = CrawlConfig()
        print(f"Class instantiation successful! (Max Pages: {config.max_pages})")
        
    except ImportError as e:
        print(f"Import failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)
    except Exception as e:
        print(f"Test failed: {e}")
        import traceback
        traceback.print_exc()
        sys.exit(1)

if __name__ == "__main__":
    asyncio.run(smoke_test())
