"""Shared failure reason taxonomy and normalization helpers."""

from __future__ import annotations

from enum import Enum
from typing import Any, Final, Mapping


class DegradedReason(str, Enum):
    CONNECTIVITY_BLOCKED = "connectivity_blocked"
    BROWSER_NAV_FAILED = "browser_navigation_failed"
    EXTRACTION_FAILED = "extraction_failed"
    RENDER_TIMEOUT = "render_timeout"
    PARTIAL_CONTENT = "partial_content"
    ENGINE_ERROR = "engine_error"
    RATE_LIMITED = "rate_limited"
    CSP_BLOCKED = "csp_blocked"
    CSP_INJECTION_BLOCKED = "csp_injection_blocked"
    BOT_WALL = "bot_wall"


STANDARD_DEGRADED_REASONS: Final[frozenset[str]] = frozenset(reason.value for reason in DegradedReason)


_LEGACY_REASON_ALIASES: Final[dict[str, DegradedReason]] = {
    "browser_navigation_failed": DegradedReason.BROWSER_NAV_FAILED,
    "browser_timeout": DegradedReason.RENDER_TIMEOUT,
    "dom_parse_error": DegradedReason.EXTRACTION_FAILED,
    "dns_error": DegradedReason.CONNECTIVITY_BLOCKED,
    "dns_failure": DegradedReason.CONNECTIVITY_BLOCKED,
    "name_resolution_failed": DegradedReason.CONNECTIVITY_BLOCKED,
    "network_error": DegradedReason.CONNECTIVITY_BLOCKED,
    "script_failure": DegradedReason.CSP_INJECTION_BLOCKED,
    "extraction_failure": DegradedReason.EXTRACTION_FAILED,
    "blocked": DegradedReason.BOT_WALL,
    "blocked_request": DegradedReason.BOT_WALL,
    "access_denied": DegradedReason.BOT_WALL,
    "cloudflare_block": DegradedReason.BOT_WALL,
    "unknown": DegradedReason.ENGINE_ERROR,
}


def _text(raw: Any) -> str:
    if isinstance(raw, BaseException):
        return f"{type(raw).__name__}: {raw}".strip().lower()
    return str(raw or "").strip().lower()


def _headers_lower(headers: Mapping[str, Any] | None) -> dict[str, str]:
    if not headers:
        return {}
    lowered: dict[str, str] = {}
    for key, value in dict(headers).items():
        lowered[str(key).strip().lower()] = str(value or "").strip()
    return lowered


def _extract_status(raw: Any, http_status: int | None) -> int | None:
    if isinstance(http_status, int):
        return http_status
    if isinstance(raw, int):
        return raw
    return None


def _is_captcha_signature(raw: Any, headers: Mapping[str, Any] | None = None) -> bool:
    text = _text(raw)
    header_map = _headers_lower(headers)
    combined = " ".join(
        [
            text,
            header_map.get("server", ""),
            header_map.get("cf-ray", ""),
            header_map.get("x-datadome", ""),
            header_map.get("x-akamai-session-info", ""),
            header_map.get("x-amz-cf-id", ""),
        ]
    ).lower()
    tokens = (
        "captcha",
        "security check",
        "challenge",
        "turnstile",
        "are you human",
        "are you a robot",
        "bot protection",
        "cf-chl",
        "cloudflare",
        "datadome",
        "akamai",
        "access denied",
        "forbidden",
        "status code 403",
        "http status 403",
    )
    return any(token in combined for token in tokens)


def _has_csp_block_header(headers: Mapping[str, Any] | None = None) -> bool:
    header_map = _headers_lower(headers)
    csp = header_map.get("content-security-policy", "")
    if not csp:
        return False
    return _csp_blocks_inline_scripts(csp)


def _csp_blocks_inline_scripts(csp_header: str) -> bool:
    csp = str(csp_header or "")
    if not csp:
        return False
    directives: dict[str, str] = {}
    for token in csp.split(";"):
        cleaned = token.strip()
        if not cleaned:
            continue
        parts = cleaned.split()
        if not parts:
            continue
        directives[parts[0].lower()] = cleaned.lower()

    script_src = directives.get("script-src") or directives.get("default-src", "")
    if not script_src:
        return False
    return "'unsafe-inline'" not in script_src and "nonce-" not in script_src and "sha256-" not in script_src


def _is_csp_injection_error(raw: Any) -> bool:
    text = _text(raw)
    tokens = (
        "content security policy",
        "csp",
        "refused to execute inline script",
        "refused to load the script",
        "violates the following content security policy directive",
    )
    return any(token in text for token in tokens)


def _is_connect_error(raw: Any) -> bool:
    text = _text(raw)
    tokens = (
        "dns",
        "getaddrinfo",
        "name not resolved",
        "name resolution",
        "nxdomain",
        "eai_again",
        "temporary failure in name resolution",
        "connection reset",
        "connection refused",
        "connection aborted",
        "network is unreachable",
        "server disconnected",
        "socket",
        "ssl",
        "tls",
        "certificate",
        "proxy",
        "connecterror",
        "net::err_connection",
    )
    return any(token in text for token in tokens)


def _is_nav_error(raw: Any) -> bool:
    text = _text(raw)
    tokens = (
        "navigation",
        "page.goto",
        "execution context",
        "target closed",
        "frame was detached",
        "net::err",
    )
    return any(token in text for token in tokens)


def _is_timeout(raw: Any) -> bool:
    text = _text(raw)
    tokens = ("timeout", "timed out", "navigation timeout", "render timeout")
    return any(token in text for token in tokens)


def _is_extraction_error(raw: Any) -> bool:
    text = _text(raw)
    tokens = (
        "parse",
        "parser",
        "lxml",
        "beautifulsoup",
        "dom",
        "html",
        "selector",
        "snapshot",
        "extraction",
        "content",
    )
    return any(token in text for token in tokens)


def normalize_failure(
    raw: str | Exception | int | None,
    *,
    http_status: int | None = None,
    headers: Mapping[str, Any] | None = None,
) -> DegradedReason:
    """Single source of truth for failure -> DegradedReason translation."""
    if isinstance(raw, DegradedReason):
        return raw

    header_map = _headers_lower(headers)
    status = _extract_status(raw, http_status)
    text = _text(raw)

    if text in STANDARD_DEGRADED_REASONS:
        return DegradedReason(text)
    if text in _LEGACY_REASON_ALIASES:
        return _LEGACY_REASON_ALIASES[text]

    if status == 429 or "status code 429" in text or "http status 429" in text:
        return DegradedReason.RATE_LIMITED

    if status == 403 or _is_captcha_signature(raw, header_map):
        return DegradedReason.BOT_WALL

    if _has_csp_block_header(header_map):
        return DegradedReason.CSP_BLOCKED
    if _is_csp_injection_error(raw):
        return DegradedReason.CSP_INJECTION_BLOCKED

    if _is_connect_error(raw):
        return DegradedReason.CONNECTIVITY_BLOCKED

    if _is_nav_error(raw):
        return DegradedReason.BROWSER_NAV_FAILED

    if _is_timeout(raw):
        return DegradedReason.RENDER_TIMEOUT

    if _is_extraction_error(raw):
        return DegradedReason.EXTRACTION_FAILED

    if status is not None and status >= 500:
        return DegradedReason.CONNECTIVITY_BLOCKED

    if status is not None and 400 <= status < 500:
        return DegradedReason.BOT_WALL

    return DegradedReason.ENGINE_ERROR


def classify_failure_reason(exc: Exception | str | None) -> str:
    """Backward-compatible wrapper that returns canonical reason code string."""
    return normalize_failure(exc).value


def normalize_reason(reason: Any) -> str:
    """Backward-compatible wrapper for canonical reason string normalization."""
    text = str(reason or "").strip()
    if not text:
        return ""
    return normalize_failure(reason).value


def reason_message(reason_code: str, detail: str | None = None) -> str:
    """Return user-readable message for a standard degraded reason."""
    normalized = normalize_failure(reason_code)
    messages = {
        DegradedReason.CONNECTIVITY_BLOCKED: "Network connectivity failed while reaching the target page.",
        DegradedReason.BROWSER_NAV_FAILED: "Browser navigation failed before the page could be audited.",
        DegradedReason.EXTRACTION_FAILED: "Rendered DOM extraction failed and only partial analysis could run.",
        DegradedReason.RENDER_TIMEOUT: "Rendering exceeded timeout budget and partial data was used.",
        DegradedReason.PARTIAL_CONTENT: "Only partial page content was available for this scan.",
        DegradedReason.ENGINE_ERROR: "An internal scan engine error occurred.",
        DegradedReason.RATE_LIMITED: "The target site rate-limited the scanner (HTTP 429).",
        DegradedReason.CSP_BLOCKED: "Content Security Policy prevented full browser probing.",
        DegradedReason.CSP_INJECTION_BLOCKED: "Content Security Policy blocked script injection during probing.",
        DegradedReason.BOT_WALL: "The target site blocked automated traffic or presented a bot challenge.",
    }
    base = messages.get(normalized, messages[DegradedReason.ENGINE_ERROR])
    if detail:
        return f"{base} ({detail})"
    return base


def csp_blocks_inline_scripts(csp_header: str) -> bool:
    """Public helper for CSP checks at script injection points."""
    return _csp_blocks_inline_scripts(csp_header)
