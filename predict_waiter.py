# predict_waiter.py — pub/sub so /start_predict can wait for results
# Adds a sticky cache (TTL) to survive rare race conditions.

from __future__ import annotations
import threading, time
from typing import Any, Dict, List, Tuple

# ---- project logger (pylogger style: pass a single formatted string) ----
try:
    import pylogger as logger
except Exception:  # fallback for dev
    import logging
    logger = logging.getLogger("PredictWaiter")
    if not logger.handlers:
        logger.setLevel(logging.INFO)

# ---- config ----
_STICKY_TTL_S: float = 35.0  # a bit > 30s HTTP timeout

# ---- normalize gmcode to a comparable key (do NOT alter semantics) ----
def _norm(x: Any) -> str:
    s = (x.decode("ascii", "ignore") if isinstance(x, (bytes, bytearray)) else str(x))
    return s.replace("\x00", "").strip()

# ---- optional: track the most recent gmcode the HTTP side is waiting on ----
_current_gmcode_lock = threading.Lock()
_current_gmcode: str | None = None
def set_current_gmcode(x: Any) -> None:
    global _current_gmcode
    with _current_gmcode_lock:
        _current_gmcode = _norm(x)
def get_current_gmcode() -> str | None:
    with _current_gmcode_lock:
        return _current_gmcode

# ---- core hub ----
class _Hub:
    def __init__(self) -> None:
        self._lock = threading.Lock()
        # key -> list[(Event, box)]
        self._waiters: Dict[str, List[Tuple[threading.Event, Dict[str, Any]]]] = {}
        # sticky cache for race cases: key -> (result, ts)
        self._sticky: Dict[str, Tuple[Any, float]] = {}

    def _sticky_put(self, key: str, result: Any) -> None:
        self._sticky[key] = (result, time.time())

    def _sticky_get(self, key: str):
        item = self._sticky.get(key)
        if not item:
            return None
        result, ts = item
        if time.time() - ts <= _STICKY_TTL_S:
            return result
        # expired
        try:
            del self._sticky[key]
        except Exception:
            pass
        return None

    def register(self, gmcode: Any) -> Tuple[str, threading.Event, Dict[str, Any]]:
        key = _norm(gmcode)
        ev = threading.Event()
        box: Dict[str, Any] = {}
        with self._lock:
            self._waiters.setdefault(key, []).append((ev, box))
            # serve immediately if a sticky result is present
            sticky = self._sticky_get(key)
            if sticky is not None:
                box["result"] = sticky
                ev.set()
                # one-shot: remove from sticky after serving
                try:
                    del self._sticky[key]
                except Exception:
                    pass
                try:
                    logger.info(f"[WAITER] register key={key} served_from_cache=1")
                except Exception:
                    pass
                return key, ev, box
        try:
            logger.info(f"[WAITER] register key={key}")
        except Exception:
            pass
        return key, ev, box

    def notify(self, gmcode: Any, resultlist: Any) -> None:
        key = _norm(gmcode)
        delivered = 0
        with self._lock:
            pairs = self._waiters.pop(key, [])
            for ev, box in pairs:
                box["result"] = resultlist
                ev.set()
                delivered += 1
            # if nobody is waiting right now, cache it for late waiters
            if delivered == 0:
                self._sticky_put(key, resultlist)
        try:
            logger.info(f"[WAITER] notify key={key} delivered={delivered}")
        except Exception:
            pass

_HUB = _Hub()

# ---- public API ----
def wait_for(gmcode: Any, timeout_s: float):
    """Return (ok, result_or_None)."""
    _key, ev, box = _HUB.register(gmcode)
    ok = ev.wait(timeout_s)
    return ok, box.get("result")

def notify_result(gmcode: Any, resultlist: Any) -> None:
    _HUB.notify(gmcode, resultlist)
