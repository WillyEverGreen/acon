"""
acon/utils/scrapling_adapter.py

Converts Acon discovery results into Scrapling-ready configurations.
"""

from typing import Any, Dict, List

def to_scrapling_jobs(acon_result: Dict[str, Any]) -> List[Dict[str, Any]]:
    """
    Transforms Acon SiteCrawlResult into a list of job configurations 
    that can be fed into Scrapling's Fetcher or Stealer.
    """
    jobs = []
    page_summaries = acon_result.get("page_summaries", [])
    
    for page in page_summaries:
        job = {
            "url": page["url"],
            "metadata": {
                "page_type": page.get("page_type"),
                "js_required": page.get("js_required", False),
                "parent_url": page.get("parent_url"),
                "topology": acon_result.get("topology")
            }
        }
        jobs.append(job)
        
    return jobs

def generate_scrapling_script(acon_result: Dict[str, Any], output_path: str = "run_scrapling.py"):
    """
    Generates a standalone Python script that uses Scrapling to 
    process the discovered URLs.
    """
    jobs = to_scrapling_jobs(acon_result)
    
    script_content = f"""
import asyncio
from scrapling import Stealer

async def main():
    # Structural DNA provided by Acon
    jobs = {jobs}
    
    print(f"Starting Scrapling turbo-extraction on {{len(jobs)}} pages...")
    
    # Using Scrapling's high-speed engine
    # In a real scenario, you'd use a pool or batch processing here
    for job in jobs:
        print(f"Fetching {{job['url']}}...")
        # Acon tells us if JS is needed
        engine = "playwright" if job['metadata']['js_required'] else "fetch"
        
        stealer = Stealer(url=job['url'], engine=engine)
        result = stealer.get()
        print(f"Done: {{len(result.text)}} chars")

if __name__ == "__main__":
    asyncio.run(main())
"""
    with open(output_path, "w", encoding="utf-8") as f:
        f.write(script_content)
    return output_path
