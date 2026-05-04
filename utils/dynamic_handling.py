"""Dynamic site handling primitives for deep/max page auditing."""

from __future__ import annotations

import hashlib
from typing import Any, Optional
from urllib.parse import urlparse


def auth_fallback_urls(seed_url: str) -> list[str]:
    from urllib.parse import urljoin, urlparse
    parsed = urlparse(seed_url)
    if parsed.scheme and parsed.netloc:
        base = f"{parsed.scheme}://{parsed.netloc}"
    else:
        base = seed_url.rstrip("/")
    paths = ("/about", "/explore", "/features", "/pricing")
    return [urljoin(f"{base}/", path.lstrip("/")) for path in paths]


STABLE_AUDIT_USER_AGENT = (
    "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 "
    "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
)


_ANTI_BOT_USER_AGENTS = [
    STABLE_AUDIT_USER_AGENT,
    (
        "Mozilla/5.0 (Macintosh; Intel Mac OS X 14_4) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/124.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (X11; Linux x86_64) AppleWebKit/537.36 "
        "(KHTML, like Gecko) Chrome/123.0.0.0 Safari/537.36"
    ),
    (
        "Mozilla/5.0 (Windows NT 10.0; Win64; x64; rv:124.0) "
        "Gecko/20100101 Firefox/124.0"
    ),
]

_TRACKER_HOST_PATTERNS = (
    "googletagmanager.com",
    "google-analytics.com",
    "doubleclick.net",
    "googlesyndication.com",
    "facebook.net",
    "facebook.com",
    "hotjar.com",
    "mixpanel.com",
    "segment.io",
    "intercom.io",
)

_HEAVY_HOST_HINTS = (
    "facebook.",
    "instagram.",
    "x.com",
    "twitter.",
    "linkedin.",
    "reddit.",
    "nytimes.",
    "pinterest.",
    "amazon.",
    "target.",
    "bestbuy.",
    "etsy.",
    "bankofamerica.",
    "chase.",
    "paypal.",
    "webmd.",
    "cdc.",
    "who.",
)

_HEAVY_PATH_TOKENS = (
    "/checkout",
    "/cart",
    "/basket",
    "/payment",
    "/account",
    "/login",
    "/signin",
    "/auth",
    "/feed",
    "/timeline",
)

_MODERATE_PATH_TOKENS = (
    "/search",
    "/product",
    "/listing",
    "/results",
    "/news",
    "/article",
)

_WHITELIST_HOSTS = (
    "fonts.googleapis.com",
    "fonts.gstatic.com",
    "cdn.jsdelivr.net",
)

_LOGIN_URL_TOKENS = ("/login", "/signin", "/auth", "/oauth", "/sso", "/accounts")
_COOKIE_ACCEPT_TOKENS = (
    "accept all",
    "accept",
    "i agree",
    "ok",
    "agree",
    "got it",
    "allow all",
    "consent",
)
_COOKIE_CONTEXT_TOKENS = ("cookie", "consent", "privacy")


def _hostname(url: str) -> str:
    try:
        parsed = urlparse(url)
        return (parsed.hostname or "").lower()
    except Exception:
        return ""


def rotate_user_agent_for_url(seed_url: str, attempt_index: int = 0) -> str:
    """Rotate user-agent deterministically per host with optional attempt offset."""
    if not _ANTI_BOT_USER_AGENTS:
        return STABLE_AUDIT_USER_AGENT

    host = _hostname(seed_url) or str(seed_url or "")
    digest = hashlib.sha256(host.encode("utf-8", errors="ignore")).hexdigest()
    base_index = int(digest[:8], 16) % len(_ANTI_BOT_USER_AGENTS)
    rotated_index = (base_index + max(0, int(attempt_index or 0))) % len(_ANTI_BOT_USER_AGENTS)
    return _ANTI_BOT_USER_AGENTS[rotated_index]


def stable_request_headers(seed_url: str = "", attempt_index: int = 0) -> dict[str, str]:
    _ = seed_url
    return {
        "User-Agent": rotate_user_agent_for_url(seed_url, attempt_index=attempt_index),
        "Accept-Language": "en-US,en;q=0.9",
        "Accept": "text/html,application/xhtml+xml,application/xml;q=0.9,*/*;q=0.8",
        "Cache-Control": "no-cache",
        "Pragma": "no-cache",
    }


def anti_bot_delay_ms(seed_url: str) -> int:
    host = _hostname(seed_url) or seed_url
    if not host:
        return 400
    digest = hashlib.sha256(host.encode("utf-8", errors="ignore")).hexdigest()
    value = int(digest[:8], 16)
    return 400 + (value % 801)


def classify_page_complexity(seed_url: str) -> str:
    """Classify URL complexity to drive adaptive timeout policies."""
    lowered = (seed_url or "").lower()
    host = _hostname(seed_url)

    try:
        parsed = urlparse(seed_url)
        path = (parsed.path or "").lower()
        query = (parsed.query or "").lower()
    except Exception:
        path = ""
        query = ""

    score = 0

    if any(token in host for token in _HEAVY_HOST_HINTS):
        score += 2

    if any(token in path for token in _HEAVY_PATH_TOKENS):
        score += 2
    elif any(token in path for token in _MODERATE_PATH_TOKENS):
        score += 1

    if query:
        score += 1
        if len(query) > 64:
            score += 1

    path_depth = len([part for part in path.split("/") if part])
    if path_depth >= 4:
        score += 1

    if "?" in lowered and "utm_" in lowered:
        score += 1

    if score >= 4:
        return "heavy"
    if score >= 2:
        return "moderate"
    return "simple"


def resolve_adaptive_timeouts(
    seed_url: str,
    scan_mode: str,
    *,
    page_timeout_seconds: int,
    network_idle_timeout_ms: int,
    ready_state_timeout_ms: int,
) -> dict[str, int | str]:
    """Return complexity-aware timeout values bounded for reliability."""
    mode = (scan_mode or "fast").lower()
    if mode not in {"fast", "deep", "max"}:
        mode = "fast"

    complexity = classify_page_complexity(seed_url)

    page_multipliers = {
        "fast": {"simple": 0.6, "moderate": 0.8, "heavy": 1.0},
        "deep": {"simple": 0.7, "moderate": 1.0, "heavy": 1.3},
        "max": {"simple": 0.8, "moderate": 1.1, "heavy": 1.4},
    }
    io_multipliers = {
        "simple": 0.65,
        "moderate": 1.0,
        "heavy": 1.25,
    }

    page_timeout = int(round(float(page_timeout_seconds) * page_multipliers[mode][complexity]))
    net_timeout = int(round(float(network_idle_timeout_ms) * io_multipliers[complexity]))
    ready_timeout = int(round(float(ready_state_timeout_ms) * io_multipliers[complexity]))

    page_min = {"fast": 6, "deep": 15, "max": 20}[mode]
    page_max = {"fast": 10, "deep": 40, "max": 60}[mode]
    page_timeout = max(page_min, min(page_max, page_timeout))

    net_timeout = max(2500, min(22000, net_timeout))
    ready_timeout = max(2000, min(12000, ready_timeout))

    return {
        "complexity": complexity,
        "page_timeout_seconds": page_timeout,
        "network_idle_timeout_ms": net_timeout,
        "ready_state_timeout_ms": ready_timeout,
    }


async def _safe_wait(page: Any, timeout_ms: int) -> None:
    try:
        await page.wait_for_timeout(int(timeout_ms))
    except Exception:
        return


async def _safe_query_selector_all(page: Any, selector: str) -> list[Any]:
    try:
        values = await page.query_selector_all(selector)
        return values if isinstance(values, list) else []
    except Exception:
        return []


async def _safe_inner_text(handle: Any) -> str:
    try:
        value = await handle.inner_text()
        return value if isinstance(value, str) else ""
    except Exception:
        return ""


async def _safe_get_attribute(handle: Any, attribute: str) -> str:
    try:
        value = await handle.get_attribute(attribute)
        return value if isinstance(value, str) else ""
    except Exception:
        return ""


async def _safe_click(handle: Any) -> bool:
    try:
        try:
            await handle.click(timeout=1500, no_wait_after=True)
        except TypeError:
            await handle.click(timeout=1500)
        return True
    except Exception:
        return False


async def apply_anti_bot_headers(page: Any, seed_url: str) -> dict[str, str]:
    headers = stable_request_headers(seed_url)
    try:
        set_headers = getattr(page, "set_extra_http_headers", None)
        if callable(set_headers):
            result = set_headers(headers)
            if hasattr(result, "__await__"):
                await result
    except Exception:
        return {}
    return headers


async def apply_anti_bot_delay(page: Any, seed_url: str) -> int:
    delay = anti_bot_delay_ms(seed_url)
    await _safe_wait(page, delay)
    return delay


async def detect_spa_framework(page: Any) -> Optional[str]:
    script = """
        () => {
            const hasReact = Boolean(
                (window.__REACT_DEVTOOLS_GLOBAL_HOOK__ &&
                 window.__REACT_DEVTOOLS_GLOBAL_HOOK__.renderers &&
                 window.__REACT_DEVTOOLS_GLOBAL_HOOK__.renderers.size > 0) ||
                document.querySelector('[data-reactroot], #root, #__next')
            );
            const hasVue3 = Boolean(window.__VUE_DEVTOOLS_GLOBAL_HOOK__ && window.__VUE_DEVTOOLS_GLOBAL_HOOK__.Vue);
            const hasVue2 = Boolean(window.Vue);
            const hasNext = Boolean(window.__NEXT_DATA__ || document.querySelector('#__next'));
            const hasNuxt = Boolean(window.__NUXT__ || document.querySelector('#__nuxt'));
            const hasAngular = Boolean(
                (window.getAllAngularRootElements && window.getAllAngularRootElements().length > 0) ||
                document.querySelector('[ng-version], app-root')
            );

            return {
                hasReact,
                hasVue3,
                hasVue2,
                hasNext,
                hasNuxt,
                hasAngular,
            };
        }
    """
    try:
        flags = await page.evaluate(script)
    except Exception:
        return None

    if not isinstance(flags, dict):
        return None

    framework_hits: list[str] = []
    if flags.get("hasNext"):
        framework_hits.append("next")
    if flags.get("hasNuxt"):
        framework_hits.append("vue")
    if flags.get("hasReact"):
        framework_hits.append("react")
    if flags.get("hasVue3") or flags.get("hasVue2"):
        framework_hits.append("vue")
    if flags.get("hasAngular"):
        framework_hits.append("angular")

    unique_hits = list(dict.fromkeys(framework_hits))
    if len(unique_hits) > 1:
        return "hybrid"
    if unique_hits:
        return unique_hits[0]
    return None


async def wait_for_hydration(
    page: Any,
    detected_framework: Optional[str],
    *,
    network_idle_timeout_ms: int,
    ready_state_timeout_ms: int,
) -> str:
    network_or_dom_ready = False
    document_ready = False

    try:
        await page.wait_for_load_state("networkidle", timeout=int(network_idle_timeout_ms))
        network_or_dom_ready = True
    except Exception:
        try:
            await page.wait_for_load_state("domcontentloaded", timeout=5000)
            network_or_dom_ready = True
        except Exception:
            network_or_dom_ready = False

    try:
        await page.wait_for_function("document.readyState === 'complete'", timeout=int(ready_state_timeout_ms))
        document_ready = True
    except Exception:
        document_ready = False

    if detected_framework:
        await _safe_wait(page, 1500)
        return "hydrated" if network_or_dom_ready or document_ready else "uncertain"

    return "uncertain"


async def detect_framework_and_wait(
    page: Any,
    *,
    network_idle_timeout_ms: int,
    ready_state_timeout_ms: int,
) -> tuple[Optional[str], str]:
    framework = await detect_spa_framework(page)
    hydration_status = await wait_for_hydration(
        page,
        framework,
        network_idle_timeout_ms=network_idle_timeout_ms,
        ready_state_timeout_ms=ready_state_timeout_ms,
    )
    return framework, hydration_status


def should_block_third_party_request(
    request_url: str,
    seed_url: str,
    resource_type: str,
    *,
    allow_intercom: bool = False,
) -> bool:
    if (resource_type or "").lower() != "script":
        return False

    request_host = _hostname(request_url)
    seed_host = _hostname(seed_url)
    if not request_host or not seed_host:
        return False

    if request_host == seed_host or request_host.endswith(f".{seed_host}"):
        return False

    if request_host in _WHITELIST_HOSTS or request_host.endswith(".cloudfront.net"):
        return False

    lowered_url = (request_url or "").lower()
    for pattern in _TRACKER_HOST_PATTERNS:
        if pattern not in request_host:
            continue
        if allow_intercom and "intercom" in pattern:
            return False
        if "facebook.com" in request_host and "/tr" not in lowered_url:
            continue
        return True

    return False


def should_block_request_for_performance(
    request_url: str,
    seed_url: str,
    resource_type: str,
    *,
    allow_intercom: bool = False,
) -> bool:
    """Decide whether a request should be blocked to reduce scan overhead."""
    resource = (resource_type or "").lower()
    if resource in {"image", "font", "media"}:
        return True

    request_host = _hostname(request_url)
    seed_host = _hostname(seed_url)
    lowered_url = (request_url or "").lower()
    third_party = bool(
        request_host
        and seed_host
        and request_host != seed_host
        and not request_host.endswith(f".{seed_host}")
    )

    if resource == "script":
        if should_block_third_party_request(
            request_url,
            seed_url,
            resource,
            allow_intercom=allow_intercom,
        ):
            return True

        if third_party:
            if allow_intercom and "intercom" in request_host:
                return False

            if any(token in request_host for token in _TRACKER_HOST_PATTERNS):
                return True

            if any(
                token in lowered_url
                for token in (
                    "analytics",
                    "collect",
                    "gtm.js",
                    "fbevents",
                    "segment",
                    "mixpanel",
                    "hotjar",
                    "pixel",
                )
            ):
                return True

    if resource in {"xhr", "fetch"} and third_party:
        if any(token in request_host for token in _TRACKER_HOST_PATTERNS):
            return True

    return False


async def install_request_interception(
    page: Any,
    seed_url: str,
    *,
    allow_intercom: bool = False,
) -> dict[str, Any]:
    """Install request routing that blocks expensive non-essential resources."""
    route_method = getattr(page, "route", None)
    stats: dict[str, Any] = {
        "installed": False,
        "blocked_total": 0,
        "blocked_by_type": {
            "image": 0,
            "font": 0,
            "media": 0,
            "script": 0,
            "xhr": 0,
            "fetch": 0,
            "other": 0,
        },
    }

    if not callable(route_method):
        return stats

    async def _handler(route: Any, request: Any) -> None:
        request_url = str(getattr(request, "url", ""))
        resource_type = str(getattr(request, "resource_type", "other") or "other").lower()
        should_block = should_block_request_for_performance(
            request_url,
            seed_url,
            resource_type,
            allow_intercom=allow_intercom,
        )

        try:
            if should_block:
                abort_fn = getattr(route, "abort", None)
                if callable(abort_fn):
                    maybe_awaitable = abort_fn()
                    if hasattr(maybe_awaitable, "__await__"):
                        await maybe_awaitable
                stats["blocked_total"] = int(stats.get("blocked_total", 0)) + 1
                bucket = stats["blocked_by_type"]
                key = resource_type if resource_type in bucket else "other"
                bucket[key] = int(bucket.get(key, 0)) + 1
                return

            continue_fn = getattr(route, "continue_", None)
            if callable(continue_fn):
                maybe_awaitable = continue_fn()
                if hasattr(maybe_awaitable, "__await__"):
                    await maybe_awaitable
        except Exception:
            return

    try:
        maybe_awaitable = route_method("**/*", _handler)
        if hasattr(maybe_awaitable, "__await__"):
            await maybe_awaitable
        stats["installed"] = True
    except Exception:
        stats["installed"] = False

    return stats


async def install_third_party_script_blocking(
    page: Any,
    seed_url: str,
    *,
    allow_intercom: bool = False,
) -> bool:
    stats = await install_request_interception(
        page,
        seed_url,
        allow_intercom=allow_intercom,
    )
    return bool(stats.get("installed", False))


async def dismiss_cookie_banner(page: Any, settle_ms: int = 800) -> bool:
    priority_selectors = [
        "button[id*='accept' i], button[class*='accept' i]",
        "button, [role='button'], a",
        "[aria-label*='accept' i], [aria-label*='cookie' i] button",
    ]

    for selector_index, selector in enumerate(priority_selectors):
        handles = await _safe_query_selector_all(page, selector)
        for handle in handles[:20]:
            if selector_index == 1:
                text = (await _safe_inner_text(handle)).lower()
                if not any(token in text for token in _COOKIE_ACCEPT_TOKENS):
                    continue

                if text and not any(token in text for token in _COOKIE_CONTEXT_TOKENS):
                    # Keep fuzzy matching conservative to avoid random CTA clicks.
                    continue

            if selector_index == 2:
                aria_label = (await _safe_get_attribute(handle, "aria-label")).lower()
                if not aria_label:
                    continue
                if not any(token in aria_label for token in ("accept", "cookie", "consent")):
                    continue

            clicked = await _safe_click(handle)
            if not clicked:
                continue

            await _safe_wait(page, settle_ms)
            return True

    return False


async def detect_login_wall(page: Any, current_url: str = "") -> dict[str, Any]:
    observed_url = current_url or str(getattr(page, "url", "") or "")
    lowered_url = observed_url.lower()
    if any(token in lowered_url for token in _LOGIN_URL_TOKENS):
        return {"requires_auth": True, "reason": "url_login_redirect"}

    script = """
        () => {
            const hasPassword = Boolean(document.querySelector("input[type='password']"));
            const hasLoginForm = Boolean(
                document.querySelector("form[action*='login' i], form[action*='signin' i], form[action*='auth' i], form[action*='sso' i]")
            );
            const robotsNoIndex = Boolean(document.querySelector("meta[name='robots'][content*='noindex' i]"));
            const hasMainContent = Boolean(document.querySelector("main, [role='main'], article"));
            const bodyText = (document.body?.innerText || '').toLowerCase();
            const loginText = ['sign in', 'log in', 'create account', 'continue with', 'join now']
                .some(token => bodyText.includes(token));

            return {
                hasPassword,
                hasLoginForm,
                robotsNoIndex,
                hasMainContent,
                loginText,
            };
        }
    """
    try:
        signals = await page.evaluate(script)
    except Exception:
        signals = {}

    if not isinstance(signals, dict):
        signals = {}

    if signals.get("hasPassword"):
        return {"requires_auth": True, "reason": "password_field_present", "signals": signals}
    if signals.get("hasLoginForm"):
        return {"requires_auth": True, "reason": "login_form_present", "signals": signals}
    if signals.get("robotsNoIndex") and not signals.get("hasMainContent"):
        return {"requires_auth": True, "reason": "robots_noindex_without_main", "signals": signals}
    if signals.get("loginText") and not signals.get("hasMainContent"):
        return {"requires_auth": True, "reason": "auth_prompt_without_main", "signals": signals}

    return {"requires_auth": False, "reason": "none", "signals": signals}


async def attempt_public_fallback_scan(page: Any, seed_url: str, max_attempts: int = 4) -> dict[str, Any]:
    candidates = auth_fallback_urls(seed_url)[: max(1, int(max_attempts))]
    checked: list[str] = []
    partial_html = ""

    for candidate in candidates:
        checked.append(candidate)
        try:
            await page.goto(candidate, wait_until="domcontentloaded")
            await _safe_wait(page, 250)
            html = await page.content()
            if isinstance(html, str) and len(html.strip()) > 40:
                partial_html = html

            auth_state = await detect_login_wall(page, current_url=candidate)
            if auth_state.get("requires_auth"):
                continue

            if isinstance(html, str) and len(html.strip()) > 40:
                return {
                    "used": True,
                    "fallback_url": candidate,
                    "html": html,
                    "checked_urls": checked,
                }
        except Exception:
            continue

    if not partial_html:
        try:
            current_html = await page.content()
            if isinstance(current_html, str) and current_html.strip():
                partial_html = current_html
        except Exception:
            partial_html = ""

    if not partial_html:
        partial_html = (
            "<html><body><main>"
            "Partial coverage only: authenticated routes blocked content extraction."
            "</main></body></html>"
        )

    return {
        "used": False,
        "fallback_url": "",
        "html": partial_html,
        "checked_urls": checked,
    }
