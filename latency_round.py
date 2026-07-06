# latency_round.py — writes latency_<YYYYMMDD>_<HHMMSS>.csv under project/log/<YYYY-MM-DD>/
from __future__ import annotations

import csv, logging, time, re
import pylogger as logger   # ← 跟 videomanager/dealerclient 一樣用法
from datetime import datetime
from pathlib import Path
from typing import Optional, Any, Dict
import re

import xml.etree.ElementTree as ET
import threading

# Encoding (dealer html ?perf=2 uses epoch_q10; ?perf=1 uses tick_10hz)
PERF_ENCODING: str = "EPOCH_Q10"  # "EPOCH_Q10" or "TICK_10HZ"

# ---- video url state ----
_current_video_url: str = ""

def set_video_url(url: str) -> None:
    global _current_video_url
    try:
        _current_video_url = str(url or "")
    except Exception:
        _current_video_url = ""

def get_video_url() -> str:
    return _current_video_url

# ---------- locate project/log/<YYYY-MM-DD>/ ----------
_DATE_RE = re.compile(r"^\d{4}-\d{2}-\d{2}$")
def _today_str() -> str: return datetime.now().strftime("%Y-%m-%d")

def _detect_log_date_dir() -> Path:
    def _from_handler(h):
        bf = getattr(h, "baseFilename", None)
        if not bf: return None
        p = Path(bf).resolve()
        if _DATE_RE.match(p.parent.name) and p.parent.parent.name == "log":
            return p.parent
        parts = list(p.parts)
        if "log" in parts:
            return Path(*parts[:parts.index("log")+1]) / _today_str()
        return None
    for h in logging.getLogger().handlers:
        d = _from_handler(h)
        if d: return d
    for _, lg in logging.Logger.manager.loggerDict.items():
        if isinstance(lg, logging.Logger):
            for h in lg.handlers:
                d = _from_handler(h)
                if d: return d
    return Path.cwd() / "log" / _today_str()

_LOG_DIR = _detect_log_date_dir()
_TS_FILE = datetime.now().strftime("%Y%m%d_%H%M%S")
CSV_PATH: Path = (_LOG_DIR / f"latency_{_TS_FILE}.csv").resolve()
CSV_PATH.parent.mkdir(parents=True, exist_ok=True)

# ---------- CSV 開關（由 config.xml 控制） ----------

def _load_csv_enabled_from_config() -> bool:
    """
    從 config.xml 讀取 <latency_csv> 設定：
      - 1 / true / yes / on → True
      - 0 / false / no / off → False
    若沒找到或發生錯誤，一律視為 True（維持原本會寫 CSV 的行為）。
    """
    try:
        # config.xml 與 main.exe/py 同目錄
        cfg_path = Path(__file__).resolve().parent / "config.xml"
        if not cfg_path.exists():
            return True

        tree = ET.parse(str(cfg_path))
        root = tree.getroot()
        node = root.find("latency_csv")
        if node is None or node.text is None:
            return True

        txt = node.text.strip().lower()
        if txt in ("0", "false", "no", "off"):
            return False
        if txt in ("1", "true", "yes", "on"):
            return True

        # 其他值一律當 True（避免誤關）
        return True
    except Exception as e:
        try:
            logger.error("latency_round: failed to read <latency_csv> from config.xml: %s" % e)
        except Exception:
            pass
        return True

# 是否寫 CSV 到磁碟（JSON / in-memory 狀態永遠可用）
CSV_ENABLED: bool = _load_csv_enabled_from_config()

# ---------- state ----------
_rounds: Dict[str, Dict[str, Any]] = {}

# Latest gmcode seen from *start_predict* (packet start or HTTP /start_predict).
# This is for **display only** (e.g., stop_predict response) and MUST NOT affect
# the stop/start matching logic.
_last_start_gmcode: Optional[str] = None

# 最新一筆 latency 資料（給 HTTP JSON 用；避免一直重讀 CSV）
_latest_latency_row: Optional[Dict[str, Any]] = None

# 上一局 dealer latency（秒），給 latency_Ndelta_s 用
_last_dealer_latency_s: Optional[float] = None

# thread-safety: HTTP stop + packet stop can arrive nearly at same time
_LOCK = threading.RLock()

# If a STOP comes again very soon (e.g. HTTP_STOP then packet STOP with empty gmcode), ignore it
_DUP_STOP_WINDOW_MS: int = 500
_last_stop_wall_ms: Optional[int] = None
_last_stop_code: Optional[str] = None

# ---------- config (optional) ----------
def configure(csv_path: Optional[str | Path] = None,
              perf_encoding: Optional[str] = None,
              log_dir: Optional[str | Path] = None) -> None:
    global CSV_PATH, PERF_ENCODING
    if perf_encoding: PERF_ENCODING = perf_encoding.upper()
    if csv_path:
        CSV_PATH = Path(csv_path).resolve()
        CSV_PATH.parent.mkdir(parents=True, exist_ok=True)
        return
    if log_dir:
        base = Path(log_dir).resolve()
        if base.name == "log": base = base / _today_str()
        base.mkdir(parents=True, exist_ok=True)
        ts = datetime.now().strftime("%Y%m%d_%H%M%S")
        CSV_PATH = (base / f"latency_{ts}.csv").resolve()

def _table_id_from_gmcode(gmcode: Optional[str]) -> str:
    """
    From gmcode like 'GN00725C0030545' extract the table id 'GN007'.
    Logic: find 'GN' followed by 3 digits; return that prefix.
    """
    if not gmcode:
        return ""
    m = re.search(r"GN\d{3}", gmcode, flags=re.IGNORECASE)
    return m.group(0).upper() if m else ""

# ---------- helpers ----------
def _csv_time_str(dt: Optional[datetime] = None) -> str:
    """CSV-visible timestamp format: YYYYMMDD HH:MM:SS."""
    dt = dt or datetime.now()
    return dt.strftime("%Y%m%d %H:%M:%S")

_CSV_HEADER = [
    "now", "gmcode", "start_t0", "stop_t1",
    "inference_latency_s", "dealer_latency_s", "latency_Ndelta_s", "video_url", "tableID"
]


def _csv_pending_path(p: Path) -> Path:
    """Rows are queued here when Excel locks the real CSV file."""
    return p.with_name(p.name + ".pending")


def _csv_write_header_if_needed(f, p: Path) -> None:
    try:
        need_header = (not p.exists()) or p.stat().st_size == 0
    except OSError:
        need_header = True
    if need_header:
        csv.writer(f).writerow(_CSV_HEADER)


def _csv_append_direct(p: Path, row: list[str]) -> None:
    """Append one row to the real CSV. Raises PermissionError/OSError if Excel locks it."""
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", newline="", encoding="utf-8") as f:
        _csv_write_header_if_needed(f, p)
        csv.writer(f).writerow(row)


def _csv_queue_pending(p: Path, row: list[str]) -> None:
    """Queue one CSV row to a sidecar file so pydealer can continue running."""
    pending = _csv_pending_path(p)
    pending.parent.mkdir(parents=True, exist_ok=True)
    with pending.open("a", newline="", encoding="utf-8") as f:
        csv.writer(f).writerow(row)


def _csv_flush_pending(p: Path) -> int:
    """Try moving pending rows back into the real CSV. Returns flushed row count."""
    pending = _csv_pending_path(p)
    if not pending.exists() or pending.stat().st_size == 0:
        return 0

    with pending.open("r", newline="", encoding="utf-8") as f:
        rows = [row for row in csv.reader(f) if row]
    if not rows:
        try:
            pending.unlink()
        except OSError:
            pass
        return 0

    # Write all pending rows in one open. If Excel locks the CSV, this raises and
    # the pending file is intentionally kept for the next retry.
    p.parent.mkdir(parents=True, exist_ok=True)
    with p.open("a", newline="", encoding="utf-8") as f:
        _csv_write_header_if_needed(f, p)
        csv.writer(f).writerows(rows)

    try:
        pending.unlink()
    except OSError:
        # Not fatal: duplicate prevention is less important than keeping pydealer alive.
        pass
    return len(rows)


def _csv_append_nonblocking(p: Path, row: list[str]) -> bool:
    """Append CSV without allowing Excel file locks to stop pydealer threads.

    Returns True if row reached the real CSV now. Returns False if queued to
    <csv>.pending because the real CSV is locked/unavailable.
    """
    try:
        flushed = _csv_flush_pending(p)
        if flushed:
            try:
                logger.info("latency_round: flushed %d pending CSV rows into %s" % (flushed, p))
            except Exception:
                pass
        _csv_append_direct(p, row)
        return True
    except (PermissionError, OSError) as e:
        try:
            _csv_queue_pending(p, row)
            try:
                logger.error(
                    "latency_round: CSV file is locked/unavailable, queued row instead. csv=%s pending=%s error=%s"
                    % (p, _csv_pending_path(p), e)
                )
            except Exception:
                pass
        except Exception as qe:
            try:
                logger.error(
                    "latency_round: failed to write CSV and also failed to queue pending row. csv=%s error=%s queue_error=%s"
                    % (p, e, qe)
                )
            except Exception:
                pass
        return False


def _csv_ensure_header(p: Path) -> None:
    """Backward-compatible helper. Never lets Excel locks crash caller."""
    try:
        p.parent.mkdir(parents=True, exist_ok=True)
        if (not p.exists()) or p.stat().st_size == 0:
            with p.open("a", newline="", encoding="utf-8") as f:
                csv.writer(f).writerow(_CSV_HEADER)
    except (PermissionError, OSError) as e:
        try:
            logger.error("latency_round: cannot ensure CSV header now; likely opened by Excel. csv=%s error=%s" % (p, e))
        except Exception:
            pass

def _as_gmcode_str(gmcode: Any) -> str:
    if isinstance(gmcode, (bytes, bytearray)):
        return gmcode.decode("ascii","ignore").rstrip("\x00")
    return str(gmcode)

# epoch_q10 reconstruction: choose nearest 10.9-min cycle
def _reconstruct_epoch_ms_from_code(t0_wall_ms: int, code_u16: int) -> int:
    q = int(code_u16) & 0xFFFF
    now_q = t0_wall_ms // 10
    k = ((now_q - q) + 32768) // 65536
    return int((q + 65536 * k) * 10)

# ---------- public API ----------
def mark_start(
    gmcode: Any,
    perf16: Optional[int] = None,
    gmstate: Optional[int] = None,
    external_epoch_ms: Optional[int] = None,
) -> None:
    global _last_start_gmcode
    code = _as_gmcode_str(gmcode)
    t0_dt = datetime.now()
    t0_wall_ms = int(time.time() * 1000)

    entry: Dict[str, Any] = {
        "t0_dt": t0_dt,
        "t0_wall_ms": t0_wall_ms,
        "recon_start_epoch_ms": None,  # internal only
    }

    # external_epoch_ms（來自 HTTP 接口等）優先於 perf16 重建
    if external_epoch_ms is not None:
        try:
            entry["recon_start_epoch_ms"] = int(external_epoch_ms)
        except Exception:
            entry["recon_start_epoch_ms"] = None

    # 若沒有 external_epoch_ms，且有 perf16 + EPOCH_Q10，就依照舊邏輯重建
    if (
        entry["recon_start_epoch_ms"] is None
        and perf16 is not None
        and PERF_ENCODING.upper() == "EPOCH_Q10"
    ):
        code_u16 = int(perf16) & 0xFFFF
        entry["recon_start_epoch_ms"] = _reconstruct_epoch_ms_from_code(t0_wall_ms, code_u16)
    with _LOCK:
        _rounds[code] = entry
        # record latest start gmcode (ignore empty)
        if code and code.strip():
            _last_start_gmcode = code.strip()


def get_last_start_gmcode() -> Optional[str]:
    """Return the latest gmcode seen from start_predict.

    This can be a finished round (already stopped) — it's meant for UI display.
    """
    with _LOCK:
        return str(_last_start_gmcode) if _last_start_gmcode else None


def _pick_latest_active_round() -> tuple[Optional[str], Optional[Dict[str, Any]]]:
    """Pick the most recent active round from _rounds (started but not yet stopped)."""
    if not _rounds:
        return (None, None)

    # Prefer the newest t0_wall_ms
    try:
        latest_code, latest_info = max(
            _rounds.items(),
            key=lambda kv: int(kv[1].get("t0_wall_ms", 0)),
        )
        if latest_code is not None:
            return (latest_code, latest_info)
    except Exception as e:
        try:
            logger.info("unable to fetch lastest gmcode from _pick_latest_active_round, messsage:%s" % e)
        except Exception:
            pass

    # Fallback: return any one (prefer non-empty key)
    for k, v in _rounds.items():
        if k:
            return (k, v)
    for k, v in _rounds.items():
        return (k, v)

    return (None, None)
    try:
        latest_code, latest_info = max(
            _rounds.items(),
            key=lambda kv: int(kv[1].get("t0_wall_ms", 0)),
        )
        if latest_code:
            return (latest_code, latest_info)
    except Exception as e :
        logger.info("unable to fetch lastest gmcode from _pick_latest_active_round, messsage:%s" % e)
        pass

    return (None, None)

def mark_stop_and_write(gmcode: Any, csv_path: Optional[str | Path] = None) -> str:
    """在 STOP_PREDICT 之後呼叫：寫一行到 latency_xxx.csv，並在主 log 打一行 [Latency]..."""
    global _latest_latency_row, _last_dealer_latency_s, _last_stop_wall_ms, _last_stop_code

    p = Path(csv_path).resolve() if csv_path else CSV_PATH
    # CSV write is handled later by _csv_append_nonblocking().
    # This avoids letting Excel file locks interrupt pydealer threads.

    t1_dt = datetime.now()
    t1_wall_ms = int(time.time() * 1000)

    raw_code = _as_gmcode_str(gmcode)
    req_code = (raw_code or "").strip()

    with _LOCK:
        # ---- Duplicate STOP suppression (very common: HTTP_STOP then packet STOP with empty gmcode) ----
        if (not req_code) and (_last_stop_wall_ms is not None):
            try:
                if t1_wall_ms - int(_last_stop_wall_ms) <= _DUP_STOP_WINDOW_MS:
                    try:
                        logger.info(
                            "STOP gmcode=%r arrives within %dms after last stop(gmcode=%r); ignore (duplicate)"
                            % (req_code, _DUP_STOP_WINDOW_MS, _last_stop_code)
                        )
                    except Exception:
                        pass
                    return str(p)
            except Exception:
                # if anything goes weird, just continue normal logic
                pass

        # 1) Prefer exact match if provided
        code = req_code
        info = _rounds.get(code) if code else None

        # 2) If missing/empty/mismatch, fallback to latest active round (most recent start)
        if info is None:
            latest_code, latest_info = _pick_latest_active_round()
            if latest_code is not None and latest_info is not None:
                if latest_code != code:
                    try:
                        logger.info(
                            "STOP gmcode=%r not found/empty; fallback to latest active gmcode=%s"
                            % (code, latest_code)
                        )
                    except Exception:
                        pass
                code, info = latest_code, latest_info
            else:
                # IMPORTANT: don't create fake start==stop rows (that produces the 0-latency duplicate rows).
                try:
                    logger.info("STOP gmcode=%r but no active round; ignore (no CSV write)" % (code,))
                except Exception:
                    pass
                return str(p)

        try:
            logger.info("STOP final gmcode=%r, and the related info is %s" % (code, info))
        except Exception:
            pass

        # ----- 計算毫秒差 -----
        inference_delta_ms = t1_wall_ms - int(info["t0_wall_ms"])
        recon_ms = info.get("recon_start_epoch_ms")
        if recon_ms is not None:
            dealer_delta_ms = t1_wall_ms - int(recon_ms)
        else:
            dealer_delta_ms = inference_delta_ms

        # ----- 轉成秒（3 位小數）-----
        inference_latency_s = inference_delta_ms / 1000.0
        dealer_latency_s    = dealer_delta_ms / 1000.0

        # ----- latency_Ndelta_s: 與「上一局 dealer_latency_s」的差 -----
        if _last_dealer_latency_s is None:
            latency_Ndelta_s = 0.0  # 第一局一定是 0
        else:
            latency_Ndelta_s = dealer_latency_s - _last_dealer_latency_s

        # 更新上一局
        _last_dealer_latency_s = dealer_latency_s

        now_str   = _csv_time_str()
        start_str = _csv_time_str(info["t0_dt"])
        stop_str  = _csv_time_str(t1_dt)
        video_url = get_video_url()

        # table_id = _table_id_from_gmcode(code) # 20251218 目前還未確定tableID的格式，先取前五碼
        table_id = code[:5]

        # ----- 更新 in-memory snapshot（給 HTTP /latency 用；不碰 CSV）-----
        _latest_latency_row = {
            "now": now_str,
            "gmcode": code,
            "start_t0": start_str,
            "stop_t1": stop_str,
            "inference_latency_s": round(inference_latency_s, 3),
            "dealer_latency_s": round(dealer_latency_s, 3),
            "latency_Ndelta_s": round(latency_Ndelta_s, 3),
            "video_url": video_url,
            "tableID": table_id,
        }

        # ----- 寫入 CSV（若開啟的話）-----
        # If Excel is opening/locking the CSV on Windows, do NOT crash or block
        # the pydealer flow. Queue to <csv>.pending and retry on future writes.
        if CSV_ENABLED:
            csv_row = [
                now_str,
                code,
                start_str,
                stop_str,
                f"{inference_latency_s:.3f}",
                f"{dealer_latency_s:.3f}",
                f"{latency_Ndelta_s:.3f}",
                video_url,
                table_id,
            ]
            _csv_append_nonblocking(p, csv_row)

        # ----- 用「同一個 pylogger」打一行 latency log -----
        try:
            logger.info(
                "[Latency]now=%s, gmcode=%s, start_t0=%s, stop_t1=%s, "
                "inference_latency_s=%.3f, dealer_latency_s=%.3f, latency_Ndelta_s=%.3f, video_url = %s, tableID=%s"
                % (now_str, code, start_str, stop_str,
                   inference_latency_s, dealer_latency_s, latency_Ndelta_s, video_url, table_id)
            )
        except Exception:
            pass

        # record last STOP (for duplicate-stop suppression)
        _last_stop_wall_ms = t1_wall_ms
        _last_stop_code = code

        # clear active round
        _rounds.pop(code, None)

    return str(p)


def clear_active_round(gmcode: Any) -> bool:
    """Clear an active round WITHOUT writing CSV.

    Used by HTTP /stop_predict when mark=0 (manual stop without recording).
    Returns True if an active round existed and was cleared.
    """
    global _last_stop_wall_ms, _last_stop_code
    code = _as_gmcode_str(gmcode)
    if not code:
        return False
    now_ms = int(time.time() * 1000)
    with _LOCK:
        existed = code in _rounds
        if existed:
            _rounds.pop(code, None)
        # update duplicate-stop guard so later STOPs (packet/HTTP) can be ignored in a short window
        _last_stop_wall_ms = now_ms
        _last_stop_code = code
    return existed

def get_latest_latency_inmemory() -> Optional[Dict[str, Any]]:
    """回傳記憶體中的最新一筆 latency（不做任何 CSV I/O）。"""
    if _latest_latency_row is None:
        return None
    # shallow copy，避免外部修改內部狀態
    return dict(_latest_latency_row)

def get_latest_latency(csv_path: Optional[str | Path] = None) -> Optional[Dict[str, Any]]:
    """Return the latest latency row from the CSV as a dict.

    Keys correspond to the CSV header:
        now, gmcode, start_t0, stop_t1,
        inference_latency_s, dealer_latency_s, latency_Ndelta_s

    Values for the *_latency_s columns are converted to float when possible.
    Returns None if the CSV file does not exist or has no data yet.
    """
    p = Path(csv_path).resolve() if csv_path else CSV_PATH
    if not p.exists():
        return None

    last_row: Optional[Dict[str, Any]] = None
    try:
        with p.open("r", encoding="utf-8", newline="") as f:
            reader = csv.DictReader(f)
            for row in reader:
                # 不斷覆蓋，就會留下「最後一筆」
                last_row = dict(row)  # make a shallow copy
    except Exception as e:
        try:
            logger.error("get_latest_latency failed reading %s: %s" % (p, e))
        except Exception:
            pass
        return None

    if last_row is None:
        return None

    # Convert numeric columns to float when possible
    for key in ("inference_latency_s", "dealer_latency_s", "latency_Ndelta_s"):
        if key in last_row:
            try:
                last_row[key] = float(last_row[key])
            except (TypeError, ValueError):
                # 如果轉 float 失敗，就保留原本字串
                pass

    return last_row
