"""Shared HTTP(S) proxy resolution for OKX calls.

Some networks reach OKX only through a local proxy (observed on this machine:
``http://127.0.0.1:17891`` configured in the OS registry) while a truly direct
socket times out. ``PublicDataDownloader`` / ``LiquidationCollector`` already
resolve this per call; this module exposes the same resolution so newer
services behave identically instead of silently connecting direct.

Resolution order: explicit setting -> environment -> OS/registry -> the
well-known local proxy. The result is memoised (positive 5 min, negative 20 s)
so a long-lived server probes at most occasionally.
"""

from __future__ import annotations

import os
import time
import urllib.request

import requests


OKX_TIME_URL = "https://www.okx.com/api/v5/public/time"
LOCAL_PROXY = "http://127.0.0.1:17891"
_ENV_KEYS = (
    "FTDESK_HTTP_PROXY", "HTTPS_PROXY", "https_proxy", "HTTP_PROXY",
    "http_proxy", "ALL_PROXY", "all_proxy",
)

# key -> (checked_at_monotonic, ttl, value)
_cache: dict[str, tuple[float, float, str | None]] = {}
_POSITIVE_TTL = 300.0
_NEGATIVE_TTL = 20.0


def candidate_proxies(explicit: str | None = None) -> list[str]:
    """Proxy URLs to try, in priority order (may be empty)."""
    out: list[str] = []
    if explicit and explicit.strip():
        out.append(explicit.strip())
    for key in _ENV_KEYS:
        value = os.environ.get(key)
        if value:
            out.append(value)
    try:
        registry = urllib.request.getproxies()
        for key in ("https", "http"):
            value = registry.get(key)
            if value:
                out.append(value)
    except Exception:  # noqa: BLE001 - registry lookup is best-effort
        pass
    out.append(LOCAL_PROXY)
    return list(dict.fromkeys(out))


def _probe(proxy: str, timeout: float) -> bool:
    try:
        response = requests.get(
            OKX_TIME_URL,
            proxies={"http": proxy, "https": proxy},
            timeout=timeout,
        )
        return response.status_code == 200
    except Exception:  # noqa: BLE001 - a failed probe just means "try the next"
        return False


def resolve_proxy(
    explicit: str | None = None, *, timeout: float = 4.0, ttl: float | None = None
) -> str | None:
    """First proxy that actually reaches OKX, or ``None`` to connect directly.

    Memoised so the probe cost is paid rarely, not on every request.
    """
    key = (explicit or "").strip()
    now = time.monotonic()
    cached = _cache.get(key)
    if cached is not None and (now - cached[0]) < cached[1]:
        return cached[2]

    found: str | None = None
    for candidate in candidate_proxies(key):
        if _probe(candidate, timeout):
            found = candidate
            break
    _cache[key] = (now, ttl if ttl is not None else (found and _POSITIVE_TTL) or _NEGATIVE_TTL, found)
    return found


def proxy_mapping(proxy: str | None) -> dict[str, str] | None:
    return {"http": proxy, "https": proxy} if proxy else None


def clear_cache() -> None:
    _cache.clear()
