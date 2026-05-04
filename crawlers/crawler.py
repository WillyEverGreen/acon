"""Core crawl queue and URL normalization primitives for Acon."""

from __future__ import annotations

from collections import deque
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


class CrawlSession:
    """Mutable crawl session state with deterministic Discovery queue semantics."""

    def __init__(self) -> None:
        self._queue: deque[CrawlQueueEntry] = deque()
        self.seen_urls: set[str] = set()

        self.pages_skipped_dedup: int = 0
        self.pages_skipped_depth: int = 0
        self.pages_skipped_exclusion: int = 0

    @property
    def has_pending(self) -> bool:
        return bool(self._queue)

    def __len__(self) -> int:
        return len(self._queue)

    def dequeue(self) -> Optional[CrawlQueueEntry]:
        if not self._queue:
            return None
        return self._queue.popleft()

    def dequeue_prioritized(self) -> Optional[CrawlQueueEntry]:
        """
        Pop the highest-priority entry with deterministic tie-breaking.
        Priority: 1. Rank (Page Type), 2. Depth (Shallow first), 3. URL (Alphabetical)
        """
        if not self._queue:
            return None

        # Deterministic selection: Find the best entry based on rank, depth, and URL
        best_index = 0
        best_entry = self._queue[0]
        best_rank = _page_type_rank(best_entry.page_type)

        for idx, entry in enumerate(self._queue):
            rank = _page_type_rank(entry.page_type)
            
            # Tie-breaking logic for determinism
            # Lower rank is better
            # If rank is same, lower depth is better (BFS-like)
            # If depth is same, alphabetical URL is better (Strict Stability)
            if (rank, entry.depth, entry.fetch_url) < (best_rank, best_entry.depth, best_entry.fetch_url):
                best_rank = rank
                best_entry = entry
                best_index = idx

        if best_index == 0:
            return self._queue.popleft()

        entry = self._queue[best_index]
        del self._queue[best_index]
        return entry

    def prepend(self, entry: CrawlQueueEntry) -> None:
        self._queue.appendleft(entry)

    def pending_count(self) -> int:
        return len(self._queue)

    def enqueue(
        self,
        fetch_url: str,
        depth: int,
        page_type: str,
        page_weight: float,
        parent_url: str | None = None,
    ) -> tuple[bool, str]:
        """Enqueue URL if dedup key has not been seen in this session."""
        clean_fetch_url = str(fetch_url or "").strip()
        dedup_key = normalize_url_for_dedup(clean_fetch_url)
        if not dedup_key:
            return False, ""

        if dedup_key in self.seen_urls:
            self.pages_skipped_dedup += 1
            return False, dedup_key

        self.seen_urls.add(dedup_key)
        self._queue.append(
            CrawlQueueEntry(
                fetch_url=clean_fetch_url,
                dedup_key=dedup_key,
                depth=int(depth),
                page_type=str(page_type),
                page_weight=float(page_weight),
                parent_url=parent_url,
            )
        )
        return True, dedup_key


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
