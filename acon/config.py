# acon/config.py

from enum import Enum
from typing import Final, Literal

class SiteTopology(str, Enum):
    SINGLE_PAGE    = "single_page"
    THIN           = "thin"
    DEEP_UNIFORM   = "deep_uniform"
    PAGINATED      = "paginated"
    MULTI_TEMPLATE = "multi_template"

TOPOLOGY_PAGES_PER_TEMPLATE: Final[dict[SiteTopology, int]] = {
    SiteTopology.SINGLE_PAGE:    1,
    SiteTopology.THIN:           5,
    SiteTopology.DEEP_UNIFORM:   3,
    SiteTopology.PAGINATED:      3,
    SiteTopology.MULTI_TEMPLATE: 2,
}

class Settings:
    metrics_window_size: int = 1000
    logs_dir: str = "./logs"
    telemetry_filename: str = "telemetry.jsonl"

settings = Settings()

CACHE_STATS: dict[str, int] = {
    "page_hits": 0, "page_misses": 0, "page_writes": 0,
    "dom_hits": 0, "dom_misses": 0, "dom_writes": 0,
    "cache_evictions": 0, "cache_stale_purges": 0, "cache_corrupt_entries": 0,
    "llm_hits": 0, "llm_misses": 0, "llm_writes": 0,
    "retrieval_hits": 0, "retrieval_misses": 0,
    "fix_hits": 0, "fix_misses": 0, "fix_writes": 0,
}

# -- Crawler Discovery Configuration --
CRAWLER_URL_RULES = {
    "binary_extensions": [
        ".pdf", ".jpg", ".jpeg", ".png", ".gif", ".svg", ".mp4", ".mp3",
        ".zip", ".gz", ".tar", ".woff", ".woff2", ".ttf", ".eot", ".ico",
    ],
    "tracking_params": [
        "fbclid", "gclid", "mc_eid", "_ga", "ref", "source",
    ],
    "skip_href_prefixes": [
        "mailto:", "tel:", "javascript:", "data:", "#",
    ],
    "skip_path_fragments": [
        "/cdn-cgi/", "/__webpack/", "/static/chunk", "/node_modules/", "/.well-known/",
    ],
    "priority_path_keywords": [
        "/checkout", "/cart", "/basket", "/payment", "/order",
        "/login", "/signin", "/signup", "/register", "/auth",
        "/contact", "/help", "/support", "/accessibility", "/faq",
        "/search", "/results", "/product", "/item", "/listing",
        "/form", "/apply", "/booking", "/schedule", "/subscribe",
        "/dashboard", "/account", "/profile", "/settings",
    ],
}

# -- Scan Mode Runtime Profiles & Page Budgets --
SCAN_MODES: Final[dict] = {
    "fast": {
        "max_pages_default":  5,
        "max_pages_sitemap":  8,
        "max_pages_ceiling":  10,
        "max_depth":          2,
        "timeout_ms":         15_000,
        "stage1_timeout":     12,
        "stage2_timeout":     4,
        "global_sla":         35,
        "concurrency":        5,
    },
    "deep": {
        "max_pages_default":  15,
        "max_pages_sitemap":  25,
        "max_pages_ceiling":  30,
        "max_depth":          4,
        "timeout_ms":         30_000,
        "stage1_timeout":     25,
        "stage2_timeout":     12,
        "global_sla":         120,
        "concurrency":        3,
    },
    "max": {
        "max_pages_default":  40,
        "max_pages_sitemap":  60,
        "max_pages_ceiling":  75,
        "max_depth":          6,
        "timeout_ms":         60_000,
        "stage1_timeout":     40,
        "stage2_timeout":     18,
        "global_sla":         240,
        "concurrency":        2,
    },
}

CRAWLER_CONFIG = {
    "sitemap": {
        "timeout_seconds": 8,
        "default_max_pages": 200,
        "fallback_paths": [
            "/sitemap.xml",
            "/sitemap_index.xml",
            "/sitemap-index.xml",
            "/sitemaps/sitemap.xml",
        ],
        "default_priority": 0.5,
        "priority_boost": 0.3,
    },
    "discovery": {
        "default_max_depth": 3,
        "default_max_pages": 100,
        "default_concurrency": 5,
        "timeout_seconds": 15,
        "default_priority": 0.5,
    },
    "dom": {
        "default_max_pages": 30,
        "concurrency": 2,
        "page_timeout_seconds": 20,
        "network_idle_timeout_ms": 12000,
        "ready_state_timeout_ms": 5000,
        "interaction_budget_per_page": 5,
        "early_stop_min_interactions": 2,
        "scroll_steps": 2,
        "interaction_wait_ms": 800,
        "scroll_wait_ms": 1000,
        "max_click_candidates": 10,
        "default_priority": 0.5,
    },
    "orchestrator": {
        "cross_crawler_agreement_boost": 0.2,
        "shallow_depth_boost": 0.1,
        "shallow_depth_threshold": 2,
    },
}

SITEMAP_MAX_DEPTH = 5
MAX_SITEMAP_DEPTH = SITEMAP_MAX_DEPTH  # alias used by sitemap_crawler.py
MAX_SCAN_GLOBAL_CAP = 80
MAX_CONCURRENT_SITE_AUDITS = 3

CRAWL_ADAPTIVE_STRATEGY = {
    "rate_limit_backoff_seconds": 5.0,
    "max_consecutive_failures": 3,
    "csp_static_fallback_enabled": True,
    "bot_wall_immediate_stop": True,
}
