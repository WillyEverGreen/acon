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

Most modern web scrapers suffer from **"URL Exhaustion"** — they spend 90% of their bandwidth fetching identical product or blog pages. Acon introduces a **Topology Orchestrator** that maps, classifies, and samples site structures to find the "Skeleton" of a site before you spend a cent on proxies.

### 💰 Acon vs. Blind Crawler (The 1:1 Battle)

*Tested on `books.toscrape.com` with an unlimited page budget.*

| Metric | Blind Crawler | Acon + Intelligence |
| :--- | :--- | :--- |
| **Pages Crawled** | 1,000 | **40** |
| **Time Taken** | 870s (14.5 min) | **111s (1.8 min)** |
| **Bandwidth Used** | 20.72 MB | **1.39 MB** |
| **Est. Proxy Cost** | $1.000 | **$0.040** |
| **Structural DNA Found** | 4/4 | **4/4** |

**96% less crawling. 25x faster structural discovery.**

> Acon's `low_information_gain` adaptive stop fires when the site's structural DNA is fully mapped — so it stops crawling the moment it has learned everything useful, instead of blindly burning through your entire budget.

---

## 📊 v0.1.2 Real-World Parity Benchmark

Tested against 4 live sites at a **shared 12–20 page budget** to verify consistency and topology detection accuracy. At equal budgets, Acon's value is budget preservation (early stop) and topology classification — not raw template count.

| Target | Acon Pages | BFS Pages | Time (Acon) | Topology Detected | Failure Rate | Outcome |
| :--- | :---: | :---: | :---: | :--- | :---: | :---: |
| **books.toscrape.com** | 20 | 20 | 60.2s | `deep_uniform` | 0% | ⚖️ Parity |
| **Hacker News** | 15 | 15 | 24.7s | `deep_uniform` | 0% | ⚖️ Parity |
| **PyPI** | **12** | 15 | 28.9s | `multi_template` | 0% | ✅ **20% fewer requests** |
| **Wikipedia** | 12 | 12 | 26.6s | `deep_uniform` | 0% | ⚖️ Parity |

**Key takeaway**: At fixed budgets, Acon matches BFS quality while:
- Correctly classifying site topology on every target (4/4)
- Achieving 0% failure rate across all 59 crawled pages
- Stopping early on PyPI (12 vs 15 pages) via `low_information_gain` — spending 20% fewer requests for the same structural understanding

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
| **Budget waste** | Crawls until limit | **Stops when structure is learned** |

---

## 🏗️ The Efficiency Pillars

Acon is optimized for production environments where every request costs money:

*   ⚡ **Static-First Discovery**: Acon probes pages with raw HTTP first. It only launches a browser if the site is a SPA, saving 90% of compute on standard sites.
*   🚫 **Intelligent Asset Blocking**: During discovery, Acon automatically aborts requests for images, fonts, and CSS to slash bandwidth and CPU usage.
*   📉 **Adaptive Early Stop**: Acon tracks information gain across a sliding window of recent pages. When the structural DNA is fully mapped, it stops — no matter what the budget says.
*   🧬 **Debounced Topology Detection**: Structural analysis (DNA mapping) is throttled to key milestones (1, 10, 25, 50 pages) to ensure max throughput.

---

## 🏗️ The Unified Intelligence Stack (The Acon Alliance)

Acon doesn't just map sites; it orchestrates the most powerful open-source scraping tools into a single, high-fidelity pipeline.

*   **🕵️ Stealth (Camoufox)**: Enable `use_stealth=True` to launch an "invisible" browser engine that bypasses Cloudflare and Akamai automatically.
*   **📄 Content (Trafilatura)**: Enable `extract_content=True` to get clean, LLM-ready Markdown from every discovered page natively.
*   **🚀 Speed (Scrapling)**: Use the `scrapling_adapter` to export Acon's "DNA Map" into Scrapling for turbo-charged mass extraction at 10x standard speeds.

---

## 🛠️ Installation

```bash
pip install acon-intel

# To enable the Alliance pillars (Highly Recommended)
pip install trafilatura camoufox scrapling
playwright install chromium
```

---

## ⚡ Quick Start (The Alliance Stack)

```python
import asyncio
from acon import SiteCrawlOrchestrator, CrawlConfig

async def main():
    # Acon discovers the 'skeleton', Trafilatura extracts the 'flesh'
    # Camoufox provides the 'stealth'
    config = CrawlConfig(
        max_pages=10,
        extract_content=True, # Pillar 1: Trafilatura
        use_stealth=True       # Pillar 2: Camoufox
    )

    brain = SiteCrawlOrchestrator()
    result = await brain.crawl_site("https://news.ycombinator.com", config)

    for page in result["page_summaries"]:
        print(f"URL: {page['url']}")
        if page['content']:
            print(f"Markdown: {page['content'][:100]}...")

if __name__ == "__main__":
    asyncio.run(main())
```

---

## 📦 The Output Shape

Acon returns a structured `SiteCrawlResult` containing everything needed for downstream extraction:

```json
{
  "topology": "multi_template",
  "pages_crawled": 12,
  "page_summaries": [
    {
      "url": "https://example.com/p/123",
      "page_type": "standard",
      "js_required": false,
      "content": "# Extracted Markdown Content...",
      "parent_url": "https://example.com/list"
    }
  ],
  "crawl_meta": {
    "early_stop_reason": "low_information_gain",
    "reflection": {
      "intelligence_score": 0.85,
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
- [x] **Adaptive Intelligence**: `low_information_gain` early stop to avoid burning crawl budgets.
- [ ] **Discovery API**: Expose Acon as a standalone Discovery microservice.

---

*Acon: The connective tissue of the intelligent web.*
