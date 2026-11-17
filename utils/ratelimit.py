"""
AgriSense AI - tiny in-memory rate limiter

Protects the endpoints that cost something on a public deployment - above all
`/api/chat`, which spends the site owner's LLM quota - without adding a
dependency or a database.

It is a sliding-window counter per (endpoint name, client IP), held in this
process's memory. That is deliberate and sufficient here: the app runs as ONE
gunicorn worker (see gunicorn.conf.py), so the counters are never split across
processes. If you scale to several workers/instances, each keeps its own
counters (the effective limit becomes limit x workers) - move to Redis-backed
limiting if you ever need strict global limits.

The client IP comes from `request.remote_addr`; behind a proxy, set
AGRISENSE_BEHIND_PROXY=1 so ProxyFix makes that the real visitor IP.
"""
import threading
import time
from collections import defaultdict, deque
from functools import wraps
from typing import Deque, Dict, Tuple

from flask import jsonify, request

from config.settings import RATE_LIMIT_ENABLED

_hits: Dict[Tuple[str, str], Deque[float]] = defaultdict(deque)
_lock = threading.Lock()
_last_sweep = 0.0
_SWEEP_EVERY_SECONDS = 300


def _sweep(now: float, horizon: float) -> None:
    """Drop idle keys so the dict can't grow without bound."""
    global _last_sweep
    if now - _last_sweep < _SWEEP_EVERY_SECONDS:
        return
    _last_sweep = now
    for key in [k for k, q in _hits.items() if not q or now - q[-1] > horizon]:
        del _hits[key]


def check(name: str, limit: int, window_seconds: int, client: str):
    """Record one hit. Returns (allowed, retry_after_seconds)."""
    now = time.monotonic()
    with _lock:
        _sweep(now, window_seconds)
        q = _hits[(name, client)]
        while q and now - q[0] > window_seconds:
            q.popleft()
        if len(q) >= limit:
            return False, max(1, int(window_seconds - (now - q[0])) + 1)
        q.append(now)
        return True, 0


def reset() -> None:
    """Forget all counters (used by tests)."""
    with _lock:
        _hits.clear()


_MESSAGE = "Too many requests - please wait a moment and try again."


def rate_limit(name: str, limit: int, window_seconds: int = 60):
    """Decorator: allow at most `limit` calls per `window_seconds` per client IP.

    The 429 body is `{"error": "<text>", "code": "RATE_LIMITED", ...}` - the same
    flat shape every other AgriSense endpoint uses, which is what the frontend
    displays directly (`data.error`).
    """

    def decorator(view):
        @wraps(view)
        def wrapper(*args, **kwargs):
            if RATE_LIMIT_ENABLED:
                allowed, retry_after = check(name, limit, window_seconds, request.remote_addr or "unknown")
                if not allowed:
                    resp = jsonify({"error": _MESSAGE, "code": "RATE_LIMITED",
                                    "retry_after_seconds": retry_after})
                    resp.status_code = 429
                    resp.headers["Retry-After"] = str(retry_after)
                    return resp
            return view(*args, **kwargs)

        return wrapper

    return decorator
