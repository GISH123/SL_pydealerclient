# stream_resilience.py
from __future__ import annotations
import time, threading, logging, os
from urllib.parse import urlparse, urlunparse, parse_qsl, urlencode
import cv2

try:
    import pylogger as _pylog
except Exception:
    _pylog = None

# ---------------- logging ----------------
def _log_info(msg: str) -> None:
    if _pylog is not None:
        try:
            _pylog.info(msg); return
        except Exception:
            pass
    logging.getLogger("SafeCapture").info(msg)

def _log_warn(msg: str) -> None:
    if _pylog is not None:
        try:
            _pylog.warning(msg); return
        except Exception:
            pass
    logging.getLogger("SafeCapture").warning(msg)

# -------------- FFmpeg URL helpers --------------
_FF_RECONNECT_DEFAULTS = {
    "reconnect": "1",
    "reconnect_streamed": "1",
    "reconnect_on_network_error": "1",
    "reconnect_delay_max": "5",
}

def _merge_query(url: str, extra: dict[str, str]) -> str:
    try:
        u = urlparse(url)
        q = dict(parse_qsl(u.query, keep_blank_values=True))
        for k, v in extra.items():
            if k not in q:
                q[k] = v
        return urlunparse(u._replace(query=urlencode(q)))
    except Exception:
        return url

def add_ffmpeg_reconnect_params(url: str) -> str:
    scheme = urlparse(url).scheme.lower()
    if scheme in ("http", "https", "rtmp", "rtmps", "rtsp"):
        out = _merge_query(url, _FF_RECONNECT_DEFAULTS)
        if out != url:
            _log_info("FFmpegURL applied reconnect params: %s" % out)
        else:
            _log_info("FFmpegURL already had reconnect params: %s" % url)
        return out
    _log_info("FFmpegURL unchanged (scheme=%s): %s" % (scheme or "none", url))
    return url

# -------------- Windows QuickEdit off --------------
def disable_windows_quickedit() -> None:
    if os.name != "nt":
        return
    try:
        import ctypes
        kernel32 = ctypes.windll.kernel32
        hStdin = kernel32.GetStdHandle(-10)  # STD_INPUT_HANDLE
        mode = ctypes.c_uint()
        if kernel32.GetConsoleMode(hStdin, ctypes.byref(mode)) == 0:
            return
        new_mode = mode.value & ~0x40 & ~0x20  # clear QUICK_EDIT & INSERT
        kernel32.SetConsoleMode(hStdin, new_mode)
        _log_info("Disabled Windows QuickEdit on console input.")
    except Exception as e:
        _log_warn("disable_windows_quickedit failed: %s" % e)

# keep older import alias
_disable_windows_quickedit = disable_windows_quickedit

# -------------- Resilient cv2 capture --------------
class SafeCapture:
    """
    Resilient wrapper around cv2.VideoCapture with the same public API.

    Back-compat extra kwargs accepted:
      - max_open_retries: int
      - reopen_backoff_sec: float
      - set_small_buffer: bool
    Unknown kwargs are ignored.
    """

    def __init__(
        self,
        src: str,
        backend: int = cv2.CAP_FFMPEG,
        options: dict | None = None,
        # resilience knobs
        stall_timeout_s: float = 3.0,
        max_read_failures: int = 8,
        reopen_backoff_s: tuple[float, ...] = (1.0, 2.0, 3.0, 5.0),
        # back-compat extras (ok to pass from old call sites)
        max_open_retries: int | None = None,
        reopen_backoff_sec: float | None = None,
        set_small_buffer: bool | None = None,
        **_ignore,
    ) -> None:
        self.source = src
        self.backend = backend
        self.options = dict(options or {})
        self.stall_timeout_s = float(stall_timeout_s)
        self.max_read_failures = int(max_read_failures)

        # derive backoff policy
        base_backoff = tuple(float(x) for x in reopen_backoff_s)
        if reopen_backoff_sec is not None:
            n = int(max_open_retries) if max_open_retries is not None else max(4, len(base_backoff))
            self.backoff = tuple(float(reopen_backoff_sec) for _ in range(max(1, n)))
        elif max_open_retries is not None and max_open_retries > 0:
            # repeat/extend the provided tuple to requested length
            seq = []
            i = 0
            while len(seq) < int(max_open_retries):
                seq.append(base_backoff[i % len(base_backoff)])
                i += 1
            self.backoff = tuple(seq)
        else:
            self.backoff = base_backoff

        # optional small buffer hint (FFmpeg-backed OpenCV honors CAP_PROP_BUFFERSIZE)
        if set_small_buffer:
            try:
                self.options[cv2.CAP_PROP_BUFFERSIZE] = 2.0
            except Exception:
                pass

        self._cap: cv2.VideoCapture | None = None
        self._lock = threading.RLock()
        self._cache = {"width": 0.0, "height": 0.0, "fps": 0.0}
        self._last_ok_ts = 0.0
        self._fail_count = 0

        self._open_initial()

    # --- VideoCapture-like API ---
    def isOpened(self) -> bool:
        with self._lock:
            return bool(self._cap) and self._cap.isOpened()

    def read(self):
        with self._lock:
            if not self._ensure_open_locked():
                return False, None
            ret, frame = self._cap.read()
            if ret:
                self._last_ok_ts = time.time()
                self._fail_count = 0
                return True, frame
            self._fail_count += 1
            now = time.time()
            stalled = (now - self._last_ok_ts) > self.stall_timeout_s
            if stalled or self._fail_count >= self.max_read_failures:
                _log_warn("SafeCapture read() failed; reopening... src=%s" % self.source)
                self._reopen_locked()
            return False, None
    def grab(self) -> bool:
        """Thread-safe wrapper for VideoCapture.grab() with auto-reopen on stall."""
        with self._lock:
            if not self._ensure_open_locked():
                return False
            ok = False
            try:
                ok = bool(self._cap.grab())
            except Exception:
                ok = False
            if ok:
                self._last_ok_ts = time.time()
                self._fail_count = 0
                return True

            # failed
            self._fail_count += 1
            now = time.time()
            stalled = (now - self._last_ok_ts) > self.stall_timeout_s
            if stalled or self._fail_count >= self.max_read_failures:
                _log_warn("SafeCapture grab() failed; reopening... src=%s" % self.source)
                self._reopen_locked()
            return False

    def retrieve(self):
        """Thread-safe wrapper for VideoCapture.retrieve()."""
        with self._lock:
            if self._cap is None:
                return False, None
            try:
                ok, frame = self._cap.retrieve()
            except Exception:
                return False, None
            if ok and frame is not None:
                # retrieve itself doesn't mean network is healthy, but update last_ok_ts anyway
                self._last_ok_ts = time.time()
                self._fail_count = 0
                return True, frame
            return False, None



    def release(self) -> None:
        with self._lock:
            if self._cap is not None:
                try:
                    self._cap.release()
                except Exception:
                    pass
            self._cap = None

    def get(self, prop_id: int) -> float:
        with self._lock:
            val = 0.0
            if self._cap is not None:
                try:
                    val = float(self._cap.get(prop_id) or 0.0)
                except Exception:
                    val = 0.0
            if val <= 0.0:
                if prop_id == cv2.CAP_PROP_FRAME_WIDTH:
                    return float(self._cache.get("width", 0.0))
                if prop_id == cv2.CAP_PROP_FRAME_HEIGHT:
                    return float(self._cache.get("height", 0.0))
                if prop_id == cv2.CAP_PROP_FPS:
                    return float(self._cache.get("fps", 0.0))
            return float(val or 0.0)

    def set(self, prop_id: int, value: float) -> bool:
        with self._lock:
            if self._cap is None:
                return False
            try:
                return bool(self._cap.set(prop_id, value))
            except Exception:
                return False

    @property
    def width(self) -> int:
        return int(self.get(cv2.CAP_PROP_FRAME_WIDTH) or 0)

    @property
    def height(self) -> int:
        return int(self.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0)

    @property
    def fps(self) -> float:
        return float(self.get(cv2.CAP_PROP_FPS) or 0.0)

    # --- internals ---
    def _open_initial(self) -> None:
        with self._lock:
            self._open_locked()
            if self._cap is None or not self._cap.isOpened():
                _log_warn("SafeCapture initial open failed: %s" % self.source)
            else:
                _log_info("SafeCapture opened: %s" % self.source)

    def _apply_options_locked(self) -> None:
        if not self.options or self._cap is None:
            return
        for k, v in self.options.items():
            try:
                self._cap.set(k, float(v))
            except Exception:
                pass

    def _snapshot_props_locked(self) -> None:
        if self._cap is None:
            return
        try:
            self._cache["width"] = float(self._cap.get(cv2.CAP_PROP_FRAME_WIDTH) or 0.0)
            self._cache["height"] = float(self._cap.get(cv2.CAP_PROP_FRAME_HEIGHT) or 0.0)
            self._cache["fps"] = float(self._cap.get(cv2.CAP_PROP_FPS) or 0.0)
        except Exception:
            pass

    def _open_locked(self) -> None:
        if self._cap is not None:
            try:
                self._cap.release()
            except Exception:
                pass
            self._cap = None
        try:
            self._cap = cv2.VideoCapture(self.source, self.backend)
        except Exception:
            self._cap = None
        if self._cap is not None and self._cap.isOpened():
            self._apply_options_locked()
            self._snapshot_props_locked()
            self._last_ok_ts = time.time()
            self._fail_count = 0

    def _reopen_locked(self) -> None:
        attempts = max(1, len(self.backoff))
        for i, delay in enumerate(self.backoff[:attempts]):
            try:
                if self._cap is not None:
                    try:
                        self._cap.release()
                    except Exception:
                        pass
                self._cap = None
                _log_warn("SafeCapture reopen attempt %d/%d after %.1fs; src=%s" %
                          (i + 1, attempts, delay, self.source))
                time.sleep(delay)
                self._cap = cv2.VideoCapture(self.source, self.backend)
                if self._cap is not None and self._cap.isOpened():
                    self._apply_options_locked()
                    self._snapshot_props_locked()
                    self._last_ok_ts = time.time()
                    self._fail_count = 0
                    _log_info("SafeCapture reopened OK: %s" % self.source)
                    return
            except Exception:
                pass
        _log_warn("SafeCapture reopen failed; keeping closed: %s" % self.source)

    def _ensure_open_locked(self) -> bool:
        if self._cap is None or not self._cap.isOpened():
            self._reopen_locked()
        return bool(self._cap) and self._cap.isOpened()
    

    def read_latest(self, drain_grab_max: int = 200):
        """
        Drain internal buffered frames quickly (drop old), then retrieve the newest.
        This keeps us close to real-time on live streams by DROPPING old frames.

        Notes:
        - Uses grab()/retrieve() so intermediate frames are discarded.
        - If grab/retrieve is not behaving, falls back to read().
        """
        # Grab a bunch of frames to flush backlog
        grabbed = False
        for _ in range(max(0, int(drain_grab_max))):
            if not self.grab():
                break
            grabbed = True

        if grabbed:
            ok, frame = self.retrieve()
            if ok and frame is not None:
                return True, frame

        # fallback
        return self.read()

