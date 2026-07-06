# latency_http_service.py — HTTP/HTTPS JSON service for latency & control
from __future__ import annotations

import json, threading, time
from http.server import BaseHTTPRequestHandler, HTTPServer
from urllib.parse import urlparse, parse_qs
from typing import Optional, Dict, Any

try:
    from http.server import ThreadingHTTPServer as _BaseServer
except ImportError:  # pragma: no cover
    _BaseServer = HTTPServer

from datetime import datetime
import latency_round
import pylogger as logger
from datamanager import DataMgrInstance

# 小型橋接：HTTP 等候預測結果
try:
    from predict_waiter import wait_for as _wait_for_result
except Exception:
    _wait_for_result = None  # 若未安裝，仍可啟動，只是無法等待同步結果

HTTP_PORT = 8880
HTTPS_PORT = 8881
PREDICT_TIMEOUT_MS = 30_000  # 30s
DEFAULT_GMSTATE = 2          # 可不傳 gmstate 時的預設
AUTO_STOP_GMSTATE = 0        # 內部自動停止一律用 0，才能真正停局

# ----------------------- utils -----------------------
def _parse_external_t0_ms(t0_str: str) -> Optional[int]:
    """YYYYMMDDhhmmss.nnn 或 YYYYMMDD hhmmss.nnn 轉 epoch_ms。允許 'T' 或 '_' 取代空白。"""
    if not t0_str:
        return None
    s = t0_str.strip().replace("T", " ").replace("_", " ")
    if " " in s:
        date_part, time_part = s.split(" ", 1)
    else:
        if len(s) < 8:
            return None
        date_part, time_part = s[:8], s[8:]

    if len(date_part) != 8:
        return None
    try:
        y, m, d = int(date_part[:4]), int(date_part[4:6]), int(date_part[6:8])
    except ValueError:
        return None

    if "." in time_part:
        hhmmss, frac = time_part.split(".", 1)
    else:
        hhmmss, frac = time_part, "0"
    if len(hhmmss) != 6:
        return None
    try:
        hh, mm, ss = int(hhmmss[:2]), int(hhmmss[2:4]), int(hhmmss[4:6])
        ms = int((frac + "000")[:3])
    except ValueError:
        return None

    try:
        dt = datetime(y, m, d, hh, mm, ss, ms * 1000)
    except ValueError:
        return None
    return int(dt.timestamp() * 1000)

def _get_latest_latency() -> Optional[Dict[str, Any]]:
    try:
        if hasattr(latency_round, "get_latest_latency_inmemory"):
            return latency_round.get_latest_latency_inmemory()
        return latency_round.get_latest_latency()
    except Exception as e:
        try:
            logger.error("Latency JSON service failed to load latest: %s" % e)
        except Exception:
            pass
        return None

def _latency_rounds_dict() -> Dict[str, Any]:
    """Return latency_round._rounds if present, else empty dict."""
    r = getattr(latency_round, "_rounds", None)
    return r if isinstance(r, dict) else {}

def _pick_latest_active_round_code() -> Optional[str]:
    """Pick latest active gmcode from latency_round._rounds based on t0_wall_ms."""
    rounds = _latency_rounds_dict()
    if not rounds:
        return None
    try:
        latest_code, latest_info = max(
            rounds.items(),
            key=lambda kv: int((kv[1] or {}).get("t0_wall_ms", 0)),
        )
        code = (latest_code or "")
        code = str(code).replace("\x00", "").strip()
        return code or None
    except Exception:
        for k in rounds.keys():
            if k:
                code = str(k).replace("\x00", "").strip()
                if code:
                    return code
        for k in rounds.keys():
            code = str(k).replace("\x00", "").strip()
            return code or None
    return None

def _latency_has_active_round(gmcode: str) -> bool:
    rounds = _latency_rounds_dict()
    if not rounds:
        return False
    return (gmcode in rounds)

def _resolve_current_gmcode(dm: Any) -> tuple[Optional[str], str]:
    """Resolve the *current* gmcode for stop_predict.

    IMPORTANT: "current" means an **active latency round** (started but not yet stopped)
    in latency_round._rounds. We intentionally DO NOT fall back to the last known
    datamanager gmcode unless it matches an active latency round, to avoid returning
    the latest stopped gmcode.
    """
    # 1) Source-of-truth: newest active latency round
    g = _pick_latest_active_round_code()
    if g and _latency_has_active_round(g):
        return (g, "latency_round_active")

    # 2) predict_waiter sticky gmcode (only if still active)
    try:
        from predict_waiter import get_current_gmcode
        g2 = get_current_gmcode()
        g2 = str(g2).replace("\x00", "").strip() if g2 else ""
        if g2 and _latency_has_active_round(g2):
            return (g2, "predict_waiter")
    except Exception:
        pass

    # 3) datamanager gmcode (only if still active)
    try:
        g3 = dm.getGamecode()
        g3 = str(g3).replace("\x00", "").strip() if g3 else ""
        if g3 and _latency_has_active_round(g3):
            return (g3, "datamanager")
    except Exception:
        pass

    return (None, "none")

# --------------------- HTTP handler -------------------
class _Handler(BaseHTTPRequestHandler):
    def _send_json(self, code: int, payload: Dict[str, Any], extra_headers: Dict[str, str] | None = None):
        body = json.dumps(payload, ensure_ascii=False).encode("utf-8")
        self.send_response(code)
        self.send_header("Content-Type", "application/json; charset=utf-8")
        self.send_header("Content-Length", str(len(body)))
        if extra_headers:
            for k, v in extra_headers.items():
                self.send_header(k, v)
        self.end_headers()
        self.wfile.write(body)

    # ---- HTTP 接口2 latency read-only (舊功能保留)  ----
    def _handle_latency_json(self):
        row = _get_latest_latency()
        if row is None:
            self._send_json(200, {}, {"X-Latency-Status": "no_record", "X-Latency-Message": "no latency record"})
            try: logger.info("Latency JSON service: no latency record")
            except Exception: pass
            return
        self._send_json(200, row, None)

    # ---- HTTP 接口 1：start_predict（含 index=1、同步等待、成功後自動 stop + 寫 latency） ----
    def _handle_start_predict(self, method: str):
        gmcode: Optional[str] = None
        t0_str: Optional[str] = None
        gmstate: int = DEFAULT_GMSTATE

        # -------- parse input --------
        try:
            if method == "GET":
                qs = parse_qs(urlparse(self.path).query)
                gmcode = (qs.get("gmcode") or [None])[0]
                gmcode_provided = bool(gmcode)
                if "mark" in qs:
                    mark_provided = True
                t0_str = (qs.get("t0") or [None])[0]
                if "gmstate" in qs and (qs["gmstate"][0] or "").strip():
                    try:
                        gmstate = int(qs["gmstate"][0])
                    except:
                        gmstate = DEFAULT_GMSTATE
            else:
                length = int(self.headers.get("Content-Length") or "0")
                raw = self.rfile.read(length) if length > 0 else b""
                data = json.loads(raw.decode("utf-8","replace")) if raw else {}
                gmcode = data.get("gmcode")
                t0_str = data.get("t0")
                try:
                    gmstate = int(data.get("gmstate", DEFAULT_GMSTATE))
                except:
                    gmstate = DEFAULT_GMSTATE
        except Exception as e:
            self._send_json(
                400,
                {"status":"error","action":"start_predict","message":"bad request: %s" % e},
                {"X-Latency-Status":"error"},
            )
            logger.error("start_predict parse error: %s" % e)
            return

        if not gmcode or not t0_str:
            self._send_json(
                400,
                {"status":"error","action":"start_predict","message":"gmcode and t0 are required"},
                {"X-Latency-Status":"error"},
            )
            logger.error("start_predict missing gmcode or t0: gmcode=%r t0=%r" % (gmcode, t0_str))
            return

        epoch_ms = _parse_external_t0_ms(t0_str)
        if epoch_ms is None:
            self._send_json(
                400,
                {"status":"error","action":"start_predict","message":"invalid t0; expected YYYYMMDDhhmmss.nnn"},
                {"X-Latency-Status":"error"},
            )
            logger.error("start_predict invalid t0: %s" % t0_str)
            return

        # ---- START：標記並送 start/dispatch ----
        logger.info("[HTTP_START] gmcode=%s gmstate=%s t0_str=%s epoch_ms=%s" % (gmcode, gmstate, t0_str, epoch_ms))

        dm = DataMgrInstance()
        try:
            try:
                latency_round.mark_start(gmcode=gmcode, perf16=None, gmstate=gmstate, external_epoch_ms=epoch_ms)
            except TypeError:
                latency_round.mark_start(gmcode=gmcode, perf16=None, gmstate=gmstate)

            dm.startPredict(gmcode, gmstate)
            if hasattr(dm, "dispatchCard"):
                dm.dispatchCard(gmcode, 1, False)
                logger.info("[HTTP_SENT] startPredict + dispatch index=1, gmcode=%s" % gmcode)
            elif hasattr(dm, "dispatchIndex"):
                dm.dispatchIndex(gmcode, 1)
                logger.info("[HTTP_SENT] startPredict + dispatchIndex(1), gmcode=%s" % gmcode)
        except Exception as e:
            self._send_json(
                500,
                {"status":"error","action":"start_predict","gmcode":gmcode,"message":"start failed: %s" % e},
                {"X-Latency-Status":"error"},
            )
            logger.error("start_predict failed for %s: %s" % (gmcode, e))
            return

        # ---- WAIT：最多 30s ----
        t0 = time.time()
        ok = False
        resultlist = None
        logger.info("[HTTP_WAIT] begin gmcode=%s" % gmcode)

        if _wait_for_result is not None:
            ok, resultlist = _wait_for_result(gmcode, PREDICT_TIMEOUT_MS/1000.0)

        waited_ms = int((time.time() - t0) * 1000)
        logger.info("[HTTP_WAIT] end gmcode=%s ok=%s waited_ms=%d" % (gmcode, ok, waited_ms))

        # ---- SUCCESS：回傳結果 + 停局(用 gmstate=0) + 寫 latency ----
        if ok and resultlist is not None:
            logger.info(
                "[HTTP_DONE] gmcode=%s count=%s sample=%s"
                % (
                    gmcode,
                    (len(resultlist) if hasattr(resultlist, "__len__") else "1"),
                    (str(resultlist[0]) if hasattr(resultlist, "__len__") and len(resultlist) > 0 else str(resultlist)),
                )
            )

            # auto stop MUST use gmstate=0 to really stop
            logger.info("[HTTP_STOP] by=success gmcode=%s gmstate=%s->%s" % (gmcode, gmstate, AUTO_STOP_GMSTATE))
            try:
                dm.stopPredict(gmcode, AUTO_STOP_GMSTATE)
            except Exception as _e:
                logger.info("[HTTP_STOP] dm.stopPredict error (ignored): %s" % _e)

            try:
                latency_round.mark_stop_and_write(gmcode)
            except Exception as _e:
                logger.info("[HTTP_STOP] mark_stop_and_write error (ignored): %s" % _e)

            # make results serializable
            results_json = []
            try:
                for r in (resultlist or []):
                    if isinstance(r, dict):
                        idx  = int(r.get("index", r.get("idx", 0)))
                        cls  = int(r.get("dealer_classid", r.get("classid", r.get("cls", 0))))
                        conf = float(r.get("conf", r.get("score", 0.0)))
                    else:
                        idx  = int(getattr(r, "index", getattr(r, "idx", 0)))
                        cls  = int(getattr(r, "dealer_classid", getattr(r, "classid", getattr(r, "cls", 0))))
                        conf = float(getattr(r, "conf", getattr(r, "score", 0.0)))
                    results_json.append({"index": idx, "dealer_classid": cls, "conf": conf})
            except Exception:
                results_json = [str(r) for r in (resultlist or [])]

            payload = {
                "status": "predict_done",
                "action": "start_predict",
                "gmcode": gmcode,
                "gmstate": gmstate,
                "wait_ms": waited_ms,
                "count": len(resultlist) if hasattr(resultlist, "__len__") else 1,
                "results": results_json,
            }
            self._send_json(200, payload, {"X-Latency-Status":"predict_done"})
            logger.info("LatencyHTTP predict_done: gmcode=%s, wait_ms=%d" % (gmcode, waited_ms))
            return

        # ---- TIMEOUT：只停局(也用 gmstate=0) — 不寫 latency ----
        logger.info("[HTTP_STOP] by=timeout gmcode=%s gmstate=%s->%s" % (gmcode, gmstate, AUTO_STOP_GMSTATE))
        try:
            dm.stopPredict(gmcode, AUTO_STOP_GMSTATE)
        except Exception as _e:
            logger.info("[HTTP_STOP] dm.stopPredict error (ignored): %s" % _e)

        self._send_json(
            200,
            {"status":"timeout","action":"start_predict","gmcode":gmcode,"gmstate":gmstate,"wait_ms": waited_ms},
            {"X-Latency-Status":"timeout"},
        )
        logger.info("LatencyHTTP predict timeout: gmcode=%s, wait_ms=%d" % (gmcode, waited_ms))

    # ---- HTTP 接口 3: stop_predict（手動結束量測；不寫 latency） ----
    def _handle_stop_predict(self, method: str) -> None:
        """
        HTTP 接口 3: stop_predict（手動結束）

        Response (only 3 keys):
          - status: "stopped" | "no_current_round" | "request_gmcode_not_match_current"
          - current_round_gmcode: <gmcode or null>
          - last_start_gmcode: <latest gmcode seen from start_predict or null>

        Rules:
          - "current round" is defined by latency_round._rounds (started but not yet stopped).
          - If request provides gmcode and it doesn't match current round, DO NOT stop anything;
            just return status=request_gmcode_not_match_current.
          - mark=1 -> close the round and write latency CSV
            mark=0 -> close the round WITHOUT writing CSV (still clears current round)
        """
        dm = DataMgrInstance()

        requested_gmcode: Optional[str] = None
        gmcode: Optional[str] = None  # incoming gmcode (optional)
        gmcode_provided: bool = False
        gmstate: int = 0  # default to 0 for stopPredict
        mark: Optional[int] = None  # None means "not provided"; we will decide default later
        mark_provided: bool = False
        gmcode_source: str = "provided"

        # -------- parse input --------
        try:
            if method == "GET":
                qs = parse_qs(urlparse(self.path).query)
                gmcode = (qs.get("gmcode") or [None])[0]
                gmcode_provided = bool(gmcode)
                if "mark" in qs:
                    mark_provided = True
                s = (qs.get("gmstate") or [None])[0]
                mk = (qs.get("mark") or [None])[0]
                if s not in (None, ""):
                    try:
                        gmstate = int(s)
                    except Exception:
                        gmstate = 0
                if mk not in (None, ""):
                    try:
                        mark = int(mk)
                    except Exception:
                        mark = 1
            else:
                length = int(self.headers.get("Content-Length", "0") or "0")
                raw = self.rfile.read(length) if length > 0 else b""
                data = json.loads(raw.decode("utf-8", "replace")) if raw else {}
                gmcode = (data or {}).get("gmcode")
                gmcode_provided = bool(gmcode)
                if "mark" in (data or {}):
                    mark_provided = True
                try:
                    gmstate = int((data or {}).get("gmstate", 0))
                except Exception:
                    gmstate = 0
                mk = (data or {}).get("mark", None)
                if mk is not None:
                    try:
                        mark = int(mk)
                    except Exception:
                        mark = 1
        except Exception as e:
            self._send_json(
                400,
                {"status":"error","action":"stop_predict","message":"invalid request body/query"},
                {"X-Latency-Status":"error"},
            )
            logger.info("[LatencyHTTP] stop_predict parse error: %s" % e)
            return

        if gmcode:
            gmcode = str(gmcode).replace("\x00", "").strip()
            requested_gmcode = gmcode or None
        else:
            requested_gmcode = None

        # latest start gmcode for UI display (independent; no logic impact)
        try:
            last_start_gmcode = latency_round.get_last_start_gmcode() if hasattr(latency_round, "get_last_start_gmcode") else None
        except Exception:
            last_start_gmcode = None

        # -------- decide default mark --------
        # - if no gmcode provided (manual stop), default mark=0 (do NOT write latency)
        # - otherwise default mark=1 (keep previous behavior)
        if mark is None:
            if (not gmcode_provided) and (not mark_provided):
                mark = 0
            else:
                mark = 1

        # -------- resolve current active round --------
        current_gmcode, current_src = _resolve_current_gmcode(dm)
        if not current_gmcode:
            payload = {
                "status": "no_current_round",
                "current_round_gmcode": None,
                "last_start_gmcode": last_start_gmcode,
            }
            self._send_json(200, payload, {"X-Latency-Status": "no_current_round"})
            logger.info("[LatencyHTTP] stop_predict: no current round (requested=%s, last_start=%s)" %
                        (requested_gmcode or "", last_start_gmcode or ""))
            return

        # If a gmcode is provided but mismatches the current active round, do NOT stop anything.
        if requested_gmcode is not None and requested_gmcode != current_gmcode:
            payload = {
                "status": "request_gmcode_not_match_current",
                "current_round_gmcode": current_gmcode,
                "last_start_gmcode": last_start_gmcode,
            }
            self._send_json(200, payload, {"X-Latency-Status": "request_gmcode_not_match_current"})
            logger.info("[LatencyHTTP] stop_predict gmcode mismatch: requested=%s current=%s last_start=%s" %
                        (requested_gmcode, current_gmcode, last_start_gmcode or ""))
            return

        # Stop the current active round (source of truth).
        stop_gmcode: str = current_gmcode
        gmcode_source = current_src

        # stop predict (datamanager is global; gmcode param is informational only)
        try:
            dm.stopPredict(stop_gmcode, gmstate)
        except Exception as e1:
            logger.info("[LatencyHTTP] stopPredict call failed for %s: %s" % (stop_gmcode, e1))

        # Close the active latency round
        recorded = False
        cleared = False
        if int(mark or 0) == 1:
            try:
                if _latency_has_active_round(stop_gmcode):
                    latency_round.mark_stop_and_write(stop_gmcode)
                    recorded = True
                    cleared = True
                else:
                    # race: already cleared by another STOP
                    cleared = False
            except Exception as _e:
                logger.info("[LatencyHTTP] stop_predict mark_stop_and_write error (ignored): %s" % _e)
        else:
            # mark=0: close WITHOUT writing
            try:
                if hasattr(latency_round, "clear_active_round"):
                    cleared = bool(latency_round.clear_active_round(stop_gmcode))
                else:
                    # fallback (shouldn't happen): pop directly
                    rounds = _latency_rounds_dict()
                    rounds.pop(stop_gmcode, None)
                    cleared = True
            except Exception as _e:
                logger.info("[LatencyHTTP] stop_predict clear_active_round error (ignored): %s" % _e)

        payload = {
            "status": "stopped",
            "current_round_gmcode": stop_gmcode,
            "last_start_gmcode": last_start_gmcode,
        }
        self._send_json(200, payload, {"X-Latency-Status": "stopped_current" if cleared else "stopped_but_missing_round"})
        logger.info("[LatencyHTTP] stop_predict done: current=%s, gmstate=%s, mark=%s, cleared=%s, recorded=%s, source=%s, last_start=%s" %
                    (stop_gmcode, gmstate, int(mark or 0), cleared, recorded, gmcode_source, last_start_gmcode or ""))

# -------------- HTTP methods ---------------
    def do_GET(self):
        path = self.path.split("?", 1)[0]
        if path in ("/", "/latency", "/latency_json"):
            self._handle_latency_json(); return
        if path == "/start_predict":
            self._handle_start_predict("GET"); return
        if path == "/stop_predict":
            self._handle_stop_predict("GET"); return
        self.send_error(404, "Not Found")

    def do_POST(self):
        path = self.path.split("?", 1)[0]
        if path == "/start_predict":
            self._handle_start_predict("POST"); return
        if path == "/stop_predict":
            self._handle_stop_predict("POST"); return
        self.send_error(404, "Not Found")

# -------------------- bootstrap -----------------------
def _start_http(port: int, use_https: bool = False, certfile: Optional[str] = None, keyfile: Optional[str] = None):
    server = _BaseServer(("0.0.0.0", port), _Handler)
    if use_https:
        import ssl
        if not (certfile and keyfile):
            logger.error("HTTPS requested but cert/key missing; skip HTTPS.")
            return None
        try:
            ctx = ssl.SSLContext(ssl.PROTOCOL_TLS_SERVER)
            ctx.load_cert_chain(certfile, keyfile)
            server.socket = ctx.wrap_socket(server.socket, server_side=True)
        except Exception as e:
            logger.error("HTTPS setup failed: %s" % e)
            return None
    th = threading.Thread(target=server.serve_forever, name=f"LatencyJSON-{port}", daemon=True)
    th.start()
    return server

def start_latency_services(certfile: Optional[str] = None, keyfile: Optional[str] = None):
    http_srv = _start_http(HTTP_PORT, use_https=False)
    https_srv = None
    if certfile and keyfile:
        https_srv = _start_http(HTTPS_PORT, use_https=True, certfile=certfile, keyfile=keyfile)
    else:
        logger.info("Latency HTTPS not started (no cert/key). HTTP on %d." % HTTP_PORT)
    return http_srv, https_srv

if __name__ == "__main__":
    start_latency_services()
    while True:
        time.sleep(1)
