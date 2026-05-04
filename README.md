<h1 align="center">
  <img src="logo.png" width="55" style="vertical-align: middle; margin-bottom: 10px;"> Acon (Site Intelligence Engine)
</h1>

Acon is a template-aware web crawler designed to map site topology and sample unique content efficiently. Instead of a standard Breadth-First Search (BFS) that treats every URL as a unique data point, Acon classifies URLs into "templates" and prioritizes discovery over redundant extraction.

> **Status**: Beta. Benchmarked across 8 diverse domains with significant efficiency gains on hierarchical sites.

---

## 🏗️ The Core Thesis
Most modern web scrapers suffer from "URL Exhaustion"—they spend 90% of their bandwidth fetching identical product or blog pages. Acon introduces a **Topology Orchestrator** that:
1. **Maps the Site**: Identifies the architectural relationship between pages.
2. **Classifies Templates**: Recognizes that `/p/1` and `/p/999` belong to the same structural group.
3. **Samples Intelligently**: Samples enough instances to verify the template, then moves on to find new structural patterns.

> **"On hierarchical sites — e-commerce, blogs, documentation — Acon saves 57-77% of requests with zero loss of structural coverage."**

## Visualizing Discovery
Acon includes an **Interactive Visualizer** that generates a zoomable Mermaid.js site tree.
- **Interactivity**: Zoom, pan, and drag to explore deep hierarchies.
- **Intelligence**: Color-coded nodes (Home, Nav, Interaction, Standard).
- **Transparency**: Hover over any node to see the full discovery URL and metadata.

## 🔬 Credibility Benchmark (Honest Results)
We benchmarked Acon against a standard BFS crawler across diverse site types to verify its efficiency.

> Benchmarks run with a 30-page discovery budget. Acon requires sufficient budget to reach template saturation — results improve significantly at scale.

| Site | Type | Efficiency | Note |
| :--- | :--- | :--- | :--- |
| `quotes.toscrape.com` | Content | **76.7%** | ✅ Ideal use case |
| `books.toscrape.com` | E-commerce | **56.7%** | ✅ Grows with scale |
| `scrapethissite.com` | Directory | **19.0%** | ✅ Moderate templates |
| `news.ycombinator.com` | News | **0.0%** | Expected — flat structure |
| `wikipedia.org` | Wiki | **0.0%** | Expected — unique deep links |

### 💡 When to use Acon
- **✅ Use for**: E-commerce stores, Blogs, Documentation sites, and Hierarchical directories.
- **❌ Not for**: Real-time news feeds, Infinite-scrolling social feeds, or single-page apps with no internal links.

**The Scalability Factor:** On a site like `books.toscrape.com`, a standard crawler would hit 1000+ pages. Acon hits ~50 categories and samples a few books, resulting in **>90% savings** on large-scale crawls (projected based on template saturation behavior).

---

## 🚀 Getting Started

### Installation
```bash
git clone https://github.com/WillyEverGreen/acon
cd acon
pip install -e .
```

### Running the Demo
```bash
python example.py
```
This will crawl `quotes.toscrape.com`, generate a dense topology map, and save it to `topology_viz.html`.

## 🛠️ Comparison Approach

| Feature | Standard Crawlers | Acon |
| :--- | :--- | :--- |
| **Strategy** | URL-based BFS | **Topology-Aware Sampling** |
| **Primary Goal** | Total Extraction | **Structural Intelligence** |
| **Duplicate Handling** | URL Deduplication | **Structural Deduplication** |
| **Visual Output** | Logs / JSON | **Interactive Site Map** |

---
*Acon is a standalone module designed for high-efficiency site intelligence.*
