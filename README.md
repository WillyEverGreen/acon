<div align="center">
  <img src="logo.png" width="120" alt="Acon Logo">
  <h1>Acon — The Intelligent Brain for Any Scraper</h1>
  <p>Acon doesn't replace Scrapling or Firecrawl. It tells them where to look.</p>
</div>

---

## Why Acon?

Most crawlers are dumb. They follow links blindly, return raw HTML, and break the moment a site changes its structure. Before you can extract anything useful, you need to understand what you're dealing with.

**Acon is a site intelligence engine.** It maps the structural "skeleton" of a website automatically — before any data extraction happens — so your scraper always knows where to look.

---

## 🏗️ The Core Thesis
Most modern web scrapers suffer from **"URL Exhaustion"**—they spend 90% of their bandwidth fetching identical product or blog pages. Acon introduces a **Topology Orchestrator** that maps, classifies, and samples site structures to find the "Skeleton" of a site before you spend a cent on proxies.

### 💰 Acon vs. Scrapling (The 1:1 Battle)

| Metric | Scrapling Alone (Blind) | Acon + Scrapling (Brain) |
| :--- | :--- | :--- |
| **Pages Crawled** | 1,000 | **40** |
| **Time Taken** | 870s (14.5 min) | **111s (1.8 min)** |
| **Bandwidth Used** | 20.72 MB | **1.39 MB** |
| **Est. Proxy Cost** | $1.000 | **$0.040** |
| **Structural DNA** | 4/4 Found | **4/4 Found** |

**96% less crawling. 25x faster structural discovery.**
*Measured on books.toscrape.com. Run it yourself:* `python benchmarks/acon_vs_scrapling.py`

---

## 🚀 Use Cases

**Price Monitoring & E-Commerce Intelligence**  
Acon detects pagination patterns and repeating product templates automatically. No manual selector configuration per site.

**Content Archival & Research**  
Feed Acon a publication's root URL. It identifies the site's content structure, prioritizes article pages over navigation noise, and hands you a clean discovery map.

**Site Auditing & SEO Analysis**  
Get an instant structural report — template count, link depth, topology classification (SPA vs static vs paginated) — in a single run.

---

## ⚡ What Makes Acon Different

| Capability | Typical Crawler | Acon |
|---|---|---|
| **JS-rendered sites** | Manual Playwright setup | **Autonomous escalation** |
| **Site structure** | Unknown until scraped | **Detected before extraction** |
| **Large site performance** | Degrades at scale | **O(log N) priority queue** |
| **Failed crawls** | Lost progress | **SQLite resumption (WAL)** |

---

## 🛠️ Installation

**Requirement**: Python >= 3.10

```bash
pip install acon
# To enable JS-rendering features
playwright install chromium
```

---

## ⚡ Quick Start

```python
import asyncio
import trafilatura
from acon import SiteCrawlOrchestrator, CrawlConfig

async def main():
    # Acon discovers the 'skeleton', Trafilatura extracts the 'flesh'
    config = CrawlConfig(
        max_pages=10,
        post_process=lambda html: trafilatura.extract(html, output_format="markdown")
    )
    
    brain = SiteCrawlOrchestrator()
    result = await brain.crawl_site("https://example.com", config)
    
    for page in result["page_summaries"]:
        print(f"URL: {page['url']}")
        print(f"Content: {page['result'][:200]}...") # Markdown from Trafilatura
```

### 📦 The Output Shape
Acon returns a structured `SiteCrawlResult` containing everything needed for downstream extraction:

```json
{
  "topology": "paginated",
  "pages_crawled": 42,
  "page_summaries": [
    {
      "url": "https://example.com/p/123",
      "page_type": "standard",
      "js_required": false,
      "parent_url": "https://example.com/list"
    }
  ],
  "crawl_meta": {
    "reflection": {
      "intelligence_score": 0.85,
      "advice": "Continue current strategy."
    }
  }
}
```

---

## 🚀 Hardened Features

- **💾 Enterprise Persistence**: SQLite/WAL state management. Resumable sessions.
- **🧠 Autonomous Fidelity Escalation**: Automatic switch to JS rendering if static fetch returns no signals.
- **🗼 Topology-Aware Prioritization**: $O(\log N)$ priority queue that adapts to site structure on-the-fly.
- **📊 Operational Reflection**: Real-time "Intelligence Score" and diagnostic advice.

---

## 🛣️ Roadmap
- [ ] **Stealth Integration**: Native support for **Camoufox** (Fingerprint bypass).
- [ ] **LLM-Ready Pipeline**: Native **Trafilatura** integration for high-fidelity Markdown output.
- [ ] **Discovery API**: Expose Acon as a standalone Discovery microservice for non-Python stacks.

---
*Acon is a standalone module designed for high-efficiency site intelligence.*
