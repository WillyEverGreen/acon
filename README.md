<div align="center">
  <img src="https://raw.githubusercontent.com/WillyEverGreen/acon/main/logo.png" width="120" alt="Acon Logo">
  <h1>Acon — The Intelligent Brain for Any Scraper</h1>
  <p>Acon doesn't replace Scrapling or Firecrawl. It tells them where to look.</p>
</div>

---

## Why Acon?

Most crawlers are dumb. They follow links blindly, return raw HTML, and break the moment a site changes its structure. Before you can extract anything useful, you need to understand what you're dealing with.

**Acon is a site intelligence engine.** It maps the structural "skeleton" of a website automatically — before any data extraction happens — so your scraper always knows where to look.

---

## 🏗️ The Core Thesis

Most modern web scrapers suffer from **"URL Exhaustion"** — they spend 90% of their bandwidth fetching identical product or blog pages. Acon introduces a **Topology Orchestrator** that maps, classifies, and samples site structures, then **stops the moment it has fully learned the site's DNA** — no wasted requests.

---

## 📊 Real-World Benchmark Results (v0.1.2 - Final 10/10 Polish)

**The correct question**: How many pages does each engine need to fully map a site's structure?

Both crawlers given an **uncapped budget**. BFS runs until exhaustion. Acon stops the moment `low_information_gain` fires — meaning the site's structural DNA is fully mapped.

### Comparison Summary (4 Representative Sites)

| Site | BFS Pages | **Acon Pages** | **Request Reduction** | **Time Saved** | Stopped By |
| :--- | :---: | :---: | :---: | :---: | :--- |
| **books.toscrape.com** | 200 | **6** | **97.0%** | **93.7%** | `low_information_gain` |
| **Hacker News** | 50 | **9** | **82.0%** | **89.0%** | `low_information_gain` |
| **Wikipedia** | 100 | **8** | **92.0%** | **93.7%** | `low_information_gain` |
| **PyPI** | 100 | **20** | **80.0%** | **93.4%** | `queue_exhausted` |

---

### Deep Dive: books.toscrape.com (E-Commerce)

| | Blind BFS | Acon |
| :--- | :---: | :---: |
| **Pages Crawled** | 200 | **6** |
| **Time Taken** | 54.1s | **3.4s** |
| **Stopped by** | budget cap | `low_information_gain` |
| **Topology Detected** | — | `deep_uniform` |

**97% fewer requests. Acon stopped at 6 pages because it detected that the structural DNA (product pages, category pages) was already fully mapped.**

---

### Deep Dive: PyPI (Multi-Template Registry)

| | Blind BFS | Acon |
| :--- | :---: | :---: |
| **Pages Crawled** | 100 | **20** |
| **Time Taken** | 100.7s | **6.6s** |
| **Stopped by** | budget cap | `queue_exhausted` |
| **Topology Detected** | — | `thin` |

**80% fewer requests. Acon classified the site and exhausted the relevant discovery queue in just 20 pages.**

---

> The key insight: a blind crawler keeps crawling because it doesn't know what it doesn't know. Acon tracks information gain in a sliding window — once new pages stop adding structural novelty, it stops and hands you the map.

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
| **Bandwidth efficiency** | Downloads everything | **Asset blocking (Discovery mode)** |
| **Discovery Latency** | Static only | **Static-First Hybrid Escalation** |
| **Failed crawls** | Lost progress | **SQLite resumption (WAL)** |
| **Budget waste** | Crawls until cap | **Stops when structure is learned** |

---

## 🏗️ The Efficiency Pillars

Acon is optimized for production environments where every request costs money:

*   ⚡ **Static-First Discovery**: Acon probes pages with raw HTTP first. It only launches a browser if the site is a SPA, saving 90% of compute on standard sites.
*   🚫 **Intelligent Asset Blocking**: During discovery, Acon automatically aborts requests for images, fonts, and CSS to slash bandwidth and CPU usage.
*   📉 **Adaptive Early Stop (`low_information_gain`)**: Acon tracks structural novelty across a sliding window. When new pages stop adding unique signal, crawling stops — before the budget is spent.
*   🧬 **Debounced Topology Detection**: Structural analysis (DNA mapping) is throttled to key milestones (1, 10, 25, 50 pages) to ensure max throughput.

---

## 🏗️ The Unified Intelligence Stack (The Acon Alliance)

Acon doesn't just map sites; it orchestrates the most powerful open-source scraping tools into a single, high-fidelity pipeline.

*   **🕵️ Stealth (Camoufox)**: Enable `use_stealth=True` to launch an "invisible" browser engine that bypasses Cloudflare and Akamai automatically.
*   **📄 Content (Trafilatura)**: Enable `extract_content=True` to get clean, LLM-ready Markdown from every discovered page natively.
*   **🚀 Speed (Scrapling)**: Use the `scrapling_adapter` to export Acon's "DNA Map" into Scrapling for turbo-charged mass extraction.

---

## 🛠️ Installation

```bash
pip install acon-intel

# To enable the Alliance pillars (Highly Recommended)
pip install trafilatura camoufox scrapling
playwright install chromium
```

---

## ⚡ Quick Start

```python
import asyncio
from acon import SiteCrawlOrchestrator, CrawlConfig

async def main():
    config = CrawlConfig(
        max_pages=50,          # Hard ceiling
        extract_content=True,  # Trafilatura: clean Markdown per page
        use_stealth=True       # Camoufox: bypass bot detection
    )

    brain = SiteCrawlOrchestrator()
    result = await brain.crawl_site("https://news.ycombinator.com", config)

    print(f"Topology: {result['topology']}")
    print(f"Pages crawled: {result['pages_crawled']}")
    print(f"Stopped by: {result['crawl_meta']['early_stop_reason']}")

    for page in result["page_summaries"]:
        print(f"  {page['url']} — {page['page_type']}")
        if page['content']:
            print(f"    {page['content'][:80]}...")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 📦 The Output Shape

```json
{
  "topology": "multi_template",
  "pages_crawled": 12,
  "pages_failed": 0,
  "page_summaries": [
    {
      "url": "https://pypi.org/project/requests/",
      "page_type": "standard",
      "js_required": false,
      "content": "# requests 2.31.0...",
      "parent_url": "https://pypi.org"
    }
  ],
  "crawl_meta": {
    "early_stop_reason": "low_information_gain",
    "crawl_duration_s": 29.5,
    "reflection": {
      "intelligence_score": 0.33,
      "failure_rate": 0.0,
      "advice": "Continue current strategy."
    }
  }
}
```

---

## 🛣️ Roadmap
- [x] **Stealth Integration**: Native support for **Camoufox** (Fingerprint bypass).
- [x] **LLM-Ready Pipeline**: Native **Trafilatura** integration for high-fidelity Markdown output.
- [x] **Speed Pillar**: Official **Scrapling** adapter for mass extraction.
- [x] **Session Persistence**: SQLite WAL-mode crawl resumption across process restarts.
- [x] **Adaptive Intelligence**: `low_information_gain` early stop — avoids burning crawl budgets.
- [ ] **Discovery API**: Expose Acon as a standalone Discovery microservice.

---

*Acon: The connective tissue of the intelligent web.*
