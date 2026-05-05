"""Shared URL normalization, filtering, and discovery helpers for crawlers."""

from __future__ import annotations

import asyncio
from typing import Iterable, Literal, Optional
from urllib.parse import parse_qsl, urlencode, urljoin, urlparse, urlunparse

from bs4 import BeautifulSoup
from curl_cffi import AsyncSession
from curl_cffi.requests import Response

from ..config import CRAWLER_CONFIG, CRAWLER_URL_RULES


_TRACKING_PARAMS = {p.lower() for p in CRAWLER_URL_RULES["tracking_params"]}
_BINARY_EXTENSIONS = tuple(ext.lower() for ext in CRAWLER_URL_RULES["binary_extensions"])
_SKIP_PREFIXES = tuple(prefix.lower() for prefix in CRAWLER_URL_RULES["skip_href_prefixes"])
_SKIP_FRAGMENTS = tuple(fragment.lower() for fragment in CRAWLER_URL_RULES["skip_path_fragments"])
_PRIORITY_KEYWORDS = tuple(k.lower() for k in CRAWLER_URL_RULES["priority_path_keywords"])


ScanMode = Literal["fast", "deep", "max"]


def _normalized_netloc(parsed) -> str:
    scheme = parsed.scheme.lower()
    host = (parsed.hostname or "").lower()
    port = parsed.port

    if not host:
        return parsed.netloc.lower()

    host_for_url = host
    if ":" in host and not host.startswith("["):
        host_for_url = f"[{host}]"

    if port is None:
        return host_for_url

    if (scheme == "http" and port == 80) or (scheme == "https" and port == 443):
        return host_for_url

    return f"{host_for_url}:{port}"


def clamp(value: float, minimum: float, maximum: float) -> float:
    return max(minimum, min(maximum, value))


def normalize_scan_mode(raw: str | None) -> ScanMode:
    """Single source of truth for scan mode normalization."""
    mode = str(raw or "").strip().lower()
    if mode in {"fast", "minimal", "light"}:
        return "fast"
    if mode in {"deep", "standard"}:
        return "deep"
    if mode in {"max", "full", "thorough"}:
        return "max"
    raise ValueError(f"Unrecognised scan_mode: {raw!r}. Expected fast | deep | max.")


def safe_float(value: Optional[str], default: float) -> float:
    if value is None:
        return default
    try:
        return float(str(value).strip())
    except (TypeError, ValueError):
        return default


def get_origin(url: str) -> str:
    parsed = urlparse(url)
    return f"{parsed.scheme.lower()}://{_normalized_netloc(parsed)}"


def is_same_origin(url: str, origin: str) -> bool:
    return get_origin(url) == origin


def path_depth(url: str) -> int:
    path = urlparse(url).path
    if not path or path == "/":
        return 0
    return len([segment for segment in path.split("/") if segment])


def has_binary_extension(url: str) -> bool:
    path = urlparse(url).path.lower()
    return path.endswith(_BINARY_EXTENSIONS)


def should_skip_href(href: str) -> bool:
    raw = (href or "").strip()
    if not raw:
        return True

    lowered = raw.lower()
    if lowered.startswith(_SKIP_PREFIXES):
        return True

    parsed = urlparse(raw)
    path = parsed.path.lower()
    if any(fragment in path for fragment in _SKIP_FRAGMENTS):
        return True

    return False


def remove_tracking_params(query_items: Iterable[tuple[str, str]]) -> list[tuple[str, str]]:
    cleaned: list[tuple[str, str]] = []
    for key, value in query_items:
        lowered = key.lower()
        if lowered.startswith("utm_"):
            continue
        if lowered in _TRACKING_PARAMS:
            continue
        cleaned.append((key, value))
    return cleaned


def normalize_url(url: str) -> str:
    parsed = urlparse(url.strip())
    scheme = parsed.scheme.lower()
    netloc = _normalized_netloc(parsed)
    path = parsed.path or "/"
    if path != "/" and path.endswith("/"):
        path = path.rstrip("/")

    query_items = parse_qsl(parsed.query, keep_blank_values=True)
    cleaned_query_items = remove_tracking_params(query_items)
    normalized_query = urlencode(sorted(cleaned_query_items, key=lambda item: (item[0], item[1])), doseq=True)

    return urlunparse((scheme, netloc, path, "", normalized_query, ""))


def resolve_url(base_url: str, href: str) -> str:
    return urljoin(base_url, href)


def extract_anchor_hrefs(html: str) -> list[str]:
    soup = BeautifulSoup(html or "", "html.parser")
    hrefs: list[str] = []
    for anchor in soup.find_all("a", href=True):
        href = anchor.get("href")
        if isinstance(href, str):
            hrefs.append(href)
    return hrefs


def priority_path_boost(url: str) -> float:
    path = urlparse(url).path.lower()
    if any(keyword in path for keyword in _PRIORITY_KEYWORDS):
        return float(CRAWLER_CONFIG["sitemap"]["priority_boost"])
    return 0.0


def detect_critical_page_type(url: str) -> Optional[str]:
    path = urlparse(url).path.lower()
    if any(token in path for token in ("/login", "/signin", "/signup", "/register", "/auth")):
        return "auth"
    if any(token in path for token in ("/form", "/apply", "/booking", "/schedule", "/subscribe", "/contact")):
        return "form"
    if any(token in path for token in ("/product", "/item", "/listing", "/search", "/results", "/checkout", "/cart")):
        return "product"
    return None


def parse_robots_disallow(robots_text: str) -> frozenset[str]:
    """Return disallowed path prefixes from robots.txt for matching user-agent blocks."""
    disallowed: set[str] = set()
    capture = False
    for raw in str(robots_text or "").splitlines():
        line = raw.strip()
        if not line or line.startswith("#"):
            continue
        lowered = line.lower()
        if lowered.startswith("user-agent:"):
            agent = line.split(":", 1)[1].strip().lower()
            capture = agent in {"*", "acon", "beaconbot"}
            continue
        if capture and lowered.startswith("disallow:"):
            path = line.split(":", 1)[1].strip()
            if path:
                disallowed.add(path)
    return frozenset(disallowed)


def is_disallowed(url: str, disallow_set: frozenset[str]) -> bool:
    if not disallow_set:
        return False
    path = urlparse(url).path or "/"
    return any(path.startswith(prefix) for prefix in disallow_set)


async def http_get_with_backoff(
    url: str,
    *,
    client: AsyncSession,
    max_retries: int = 2,
    timeout_seconds: float | None = None,
) -> Response:
    """GET with Retry-After/exponential backoff handling for HTTP 429 responses."""
    response: Response | None = None
    for attempt in range(max_retries + 1):
        response = await client.get(url, timeout=timeout_seconds)
        if int(response.status_code) != 429:
            return response

        if attempt >= max_retries:
            return response

        retry_after_raw = str(response.headers.get("Retry-After", "") or "").strip()
        try:
            wait_seconds = float(retry_after_raw) if retry_after_raw else float(2 ** (attempt + 1))
        except ValueError:
            wait_seconds = float(2 ** (attempt + 1))
        await asyncio.sleep(min(wait_seconds, 15.0))

    return response if response is not None else await client.get(url, timeout=timeout_seconds)
