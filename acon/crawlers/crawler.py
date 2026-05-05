"""Core crawl queue and URL normalization primitives for Acon."""

from __future__ import annotations

import heapq
from dataclasses import dataclass
from typing import Optional
from urllib.parse import parse_qsl, urlencode, urlparse, urlunparse

@dataclass(slots=True)
class CrawlQueueEntry:
    """Queue entry tracked by the Discovery crawler."""

    fetch_url: str
    dedup_key: str
    depth: int
    page_type: str
    page_weight: float
    parent_url: str | None = None
    js_required: bool = False  # If True, signals that this URL needs JS rendering for data
    fidelity_retry_count: int = 0  # Number of times this URL has been escalated


class CrawlSession:
    """Mutable crawl session state with deterministic Discovery queue semantics."""

    def __init__(self) -> None:
        self._heap: list[tuple[int, int, int, CrawlQueueEntry]] = []
        self._counter: int = 0  # Tie-breaker for deterministic FIFO within same priority
        self.seen_urls: set[str] = set()

        self.pages_skipped_dedup: int = 0
        self.pages_skipped_depth: int = 0
        self.pages_skipped_exclusion: int = 0
        
        # Optional topology context to influence prioritization
        self.topology: str = "UNKNOWN"

    def update_topology(self, topology: str) -> None:
        """Update topology and rebuild the heap to reflect new priorities."""
        if self.topology == topology:
            return
        
        self.topology = topology
        
        # Rebuild the heap with new ranks
        new_heap = []
        for _, depth, counter, entry in self._heap:
            new_rank = self._calculate_rank(entry.page_type, depth)
            heapq.heappush(new_heap, (new_rank, depth, counter, entry))
        
        self._heap = new_heap

    @property
    def has_pending(self) -> bool:
        return bool(self._heap)

    def __len__(self) -> int:
        return len(self._heap)

    def dequeue_prioritized(self) -> Optional[CrawlQueueEntry]:
        """
        Pop the highest-priority entry with deterministic tie-breaking.
        Priority: 1. Rank (Page Type), 2. Depth (Shallow first), 3. Counter (FIFO)
        Complexity: O(log N)
        """
        if not self._heap:
            return None

        _, _, _, entry = heapq.heappop(self._heap)
        return entry

    def pending_count(self) -> int:
        return len(self._heap)

    def enqueue(
        self,
        fetch_url: str,
        depth: int,
        page_type: str = "standard",
        page_weight: float = 0.7,
        parent_url: str | None = None,
        js_required: bool = False,
        fidelity_retry_count: int = 0,
        priority: int | None = None,
        is_discovery: bool = False,
    ) -> tuple[bool, str]:
        """Enqueue URL if dedup key has not been seen in this session."""
        clean_fetch_url = str(fetch_url or "").strip()
        dedup_key = normalize_url_for_dedup(clean_fetch_url)
        if not dedup_key:
            return False, ""

        # Handle deduplication and escalation retries
        # If already seen, we only allow re-enqueueing if it's an escalation (js_required=True)
        # AND we haven't exceeded the retry cap (default 1).
        if dedup_key in self.seen_urls:
            if not js_required or fidelity_retry_count > 1:
                self.pages_skipped_dedup += 1
                return False, dedup_key

        self.seen_urls.add(dedup_key)
        
        if priority is not None:
            rank = priority
        else:
            rank = self._calculate_rank(page_type, depth)
        
        # Discovery or JS-required entries get a priority boost (lower rank)
        if is_discovery:
            rank = min(rank, 0)  # Discovery is top priority
        elif js_required:
            rank = max(0, rank - 2)

        entry = CrawlQueueEntry(
            fetch_url=clean_fetch_url,
            dedup_key=dedup_key,
            depth=int(depth),
            page_type=str(page_type),
            page_weight=float(page_weight),
            parent_url=parent_url,
            js_required=js_required,
            fidelity_retry_count=fidelity_retry_count,
        )
        
        # Push to heap: (rank, depth, counter, entry)
        # Lower rank = higher priority
        # Lower depth = higher priority (BFS-like)
        # Lower counter = higher priority (FIFO tie-breaker)
        heapq.heappush(self._heap, (rank, int(depth), self._counter, entry))
        self._counter += 1
        
        return True, dedup_key

    def _calculate_rank(self, page_type: str, depth: int) -> int:
        """Calculate a priority rank influenced by site topology."""
        base_rank = _page_type_rank(page_type)
        
        # Topology-aware adjustments
        if self.topology == "PAGINATED" and page_type == "nav":
            # Prioritize pagination to find more items faster
            return base_rank - 1
        
        if self.topology == "SINGLE_PAGE" and depth == 0:
            # SPAs often need the homepage to be fully processed first
            return 0
            
        return base_rank


def normalize_url_for_dedup(url: str) -> str:
    """Normalize URL for deduplication while preserving fetch URLs separately."""
    raw = str(url or "").strip()
    if not raw:
        return ""

    parsed = urlparse(raw)
    if not parsed.scheme or not parsed.netloc:
        return ""

    scheme = parsed.scheme.lower()
    host = parsed.hostname.lower() if parsed.hostname else ""
    if not host:
        return ""

    if parsed.port is None:
        netloc = host
    else:
        default_port = (scheme == "http" and parsed.port == 80) or (scheme == "https" and parsed.port == 443)
        netloc = host if default_port else f"{host}:{parsed.port}"

    path = parsed.path or "/"
    if path != "/":
        path = path.rstrip("/") or "/"

    query_pairs = parse_qsl(parsed.query, keep_blank_values=True)
    query_pairs.sort(key=lambda item: (item[0], item[1]))
    query = urlencode(query_pairs, doseq=True)

    return urlunparse((scheme, netloc, path, "", query, ""))


def _page_type_rank(page_type: str) -> int:
    lowered = str(page_type or "").strip().lower()
    if lowered == "homepage":
        return 1
    if lowered == "interaction":
        return 2
    if lowered == "nav":
        return 3
    return 4
