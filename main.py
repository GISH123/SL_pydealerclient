# encoding=utf-8
import sys
import os
os.environ["SETUPTOOLS_USE_DISTUTILS"] = "stdlib"  # 強制 TF 用內建 distutils # fixing exe problem when building on 11.75 computer  
from twisted.internet import reactor
import pylogger as logger
# from singleInstance import singleInstanceStart
from config import cfg
# --- robust import for PyInstaller ---
import importlib
# _dealerclient = importlib.import_module("dealerclient")
import dealerclient as _dealerclient
logger.info(f"dealerclient loaded from: {_dealerclient.__file__}")
DealerClient = _dealerclient.DealerClient
# from dev_mgr_client import DevMgrClient
from detector import Detector
from imagesaver import ImageSaver
from videomanager import VideoManager
from pathlib import Path
# ------------------------------------------------------------
# version.txt (auto-generated at build time by ImageDetector_Latency.spec)
# Format: Imagedetector_latency_v<MAJOR>_<MINOR>_<PATCH>
# ------------------------------------------------------------
DISPLAY_VERSION_PREFIX = 'Imagedetector_latency_v'


def _get_app_dir() -> Path:
    """Return the directory where runtime resources (like version.txt) live.

    - PyInstaller onedir: next to the .exe
    - source run: next to this main.py
    """
    if getattr(sys, 'frozen', False):
        return Path(sys.executable).resolve().parent
    return Path(__file__).resolve().parent


def _load_version_txt() -> str:
    # Prefer exe dir; fallback to script dir
    candidates = [
        _get_app_dir() / 'version.txt',
        Path(__file__).resolve().parent / 'version.txt',
    ]
    for p in candidates:
        try:
            s = p.read_text(encoding='utf-8').strip()
            if s:
                return s
        except Exception:
            pass
    return f"{DISPLAY_VERSION_PREFIX}0_0_0"


VERSION = _load_version_txt()
from async_image_saver import AsyncImageSaver, NullImageSaver
import threading, time
from latency_http_service import start_latency_services

# 20251015 add imagesaver for I/O tasks to non block detection
def create_image_saver(save_small: int, save_big: int):
    """
    Decide whether to use a real async saver or a no-op based on toggles.
    Always returns an object exposing .start(), .stop(), .enqueue(...).
    """
    try:
        enabled = (int(save_small) > 0) or (int(save_big) > 0)
    except Exception:
        enabled = True
    if enabled:
        saver = AsyncImageSaver(queue_maxsize=512, workers=1, log_interval_sec=60).start()
        logger.info('Image saver: async mode enabled.')
        return saver
    else:
        logger.info('Image saver: disabled (no image saving).')
        return NullImageSaver().start()

# Detect the directory for certificates
# Detect if running as a frozen executable or as a script
if getattr(sys, 'frozen', False):  # If running as a bundled .exe
    base_dir = Path(sys._MEIPASS)  # _MEIPASS is where PyInstaller unpacks resources
else:
    base_dir = Path(__file__).resolve().parent
cert_dir = base_dir / "certs"
certfile = cert_dir / "latency_server.crt"
keyfile = cert_dir / "latency_server.key"

if __name__ == '__main__':

    # ---- Version ----
    print(f"[INFO] {VERSION}")
    logger.info(f"version.txt: {VERSION}")
    try:
        vp = _get_app_dir() / 'version.txt'
        if not vp.exists():
            vp.write_text(VERSION + '\n', encoding='utf-8')
    except Exception:
        pass


    # ---- Start latency JSON HTTP service (and optional HTTPS) ----
    # HTTP:  port 8880  -> returns latest latency row as JSON at "/" or "/latency"
    # HTTPS: port 8881  -> only started if you later pass cert/key to start_latency_services(...)
    try:
        if certfile.exists() and keyfile.exists():
            print("[INFO] Found certs in certs/ directory. Starting HTTP and HTTPS services.")
            # Fire up both HTTP and HTTPS
            start_latency_services(certfile=str(certfile), keyfile=str(keyfile))
        else:
            print("[INFO] No certs found in certs/ directory. Starting only HTTP service.")
            # Only fire up HTTP
            start_latency_services()

        # Give the server a little time to start before any further action
        time.sleep(0.3)
    except Exception as e:
        logger.error("Latency JSON service failed to start: %s", e)

    logger.info('detect v%s starting...' % VERSION)
    dector = Detector()

    # ---- NEW: kick off detector warm-up in background (non-blocking) ----
    try:
        threading.Thread(
            target=dector.warmup,
            kwargs={"iters": 2, "size": (cfg.videoheight, cfg.videowidth)},  # (H, W)
            daemon=True
        ).start()
    except Exception as e:
        logger.info("warmup spawn failed: " + str(e))
    # --------------------------------------------------------------------

    reactor.suggestThreadPoolSize(8)

    dealer = DealerClient(cfg.dealer_host, cfg.dealer_port, cfg.dealer_id)

    # 启动视频
    # Toggles from config
    save_predictions = int(cfg.save_small_image)   # 存小圖（cropped）
    save_full_image  = int(cfg.save_big_image)     # 存大圖（full frame）

    # Async, non-blocking saver 
    imageSaver = create_image_saver(save_predictions, save_full_image)
    try:
        videoMgr = VideoManager(cfg.gametype, cfg.stream, cfg.videowidth, cfg.videoheight, cfg.pos_list, dealer, dector, imageSaver, \
            cfg.onelabel, cfg.freq, cfg.tilt_angle, save_predictions, save_full_image, cfg.save_folder, cfg.video_loop)
        videoMgr.start()
        reactor.addSystemEventTrigger('before', 'shutdown', imageSaver.stop)
        reactor.run()
    except Exception as e:
        logger.error("Main process videomanager (reactor) failed: " + str(e))

    sys.exit()
