# encoding=utf-8
import os
import cv2
import time
import threading
import queue
import traceback
import pylogger as logger

class AsyncImageSaver:
    """
    Lightweight, non-blocking disk writer for images.
    Use enqueue(path, bgr_image) from the hot path. A background worker encodes/writes.

    - Bounded queue with drop-on-backpressure (never blocks the caller).
    - Atomic write via .tmp + os.replace.
    - Periodic stats logs.
    - Back-compat no-ops: setSnapshotFlag / clearSnapshotFlag / getSnapshotFlag
      (some older code calls these methods on the image saver).
    """
    def __init__(self, queue_maxsize=256, workers=1, log_interval_sec=60):
        self._q = queue.Queue(maxsize=queue_maxsize)
        self._stop_evt = threading.Event()
        self._threads = []
        self._written = 0
        self._dropped = 0
        self._failed = 0
        self._last_log_ts = time.time()
        self._log_interval = log_interval_sec
        self._workers = workers if workers >= 1 else 1

        # --- Back-compat snapshot flag (no-op semantics unless your code reads it) ---
        self._snapshot_flag = False
        self._flag_lock = threading.Lock()

    # ---------------- Public lifecycle ----------------
    def start(self):
        if self._threads:
            return self
        for i in range(self._workers):
            t = threading.Thread(target=self._worker, name=f'AsyncImageSaver-{i}', daemon=True)
            t.start()
            self._threads.append(t)
        logger.info(f'AsyncImageSaver started with {self._workers} worker(s), queue maxsize={self._q.maxsize}')
        return self

    def stop(self, drain_timeout_sec=3.0):
        # Signal and drain queue briefly
        self._stop_evt.set()
        deadline = time.time() + max(0.0, drain_timeout_sec)
        for t in self._threads:
            remaining = deadline - time.time()
            t.join(timeout=remaining if remaining > 0 else 0)
        logger.info(f'AsyncImageSaver stopped. written={self._written}, dropped={self._dropped}, failed={self._failed}')
        self._threads.clear()

    # ---------------- Main API ----------------
    def enqueue(self, filepath, image_bgr, encode_ext=None, quality=90):
        """
        Non-blocking: if queue is full, the image is dropped and we log later.
        Returns True if queued, False if dropped.
        """
        if filepath is None or image_bgr is None:
            return False

        # Ensure directory exists
        try:
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
        except Exception as e:
            logger.error(f'AsyncImageSaver: failed to make dirs for {filepath}: {e}')
            return False

        # Determine extension
        if encode_ext is None:
            _, ext = os.path.splitext(filepath)
            encode_ext = ext.lower() if ext else '.jpg'
        if encode_ext not in ('.jpg', '.jpeg', '.png', '.bmp'):
            encode_ext = '.jpg'

        # Choose params
        if encode_ext in ('.jpg', '.jpeg'):
            params = [int(cv2.IMWRITE_JPEG_QUALITY), int(quality)]
        elif encode_ext == '.png':
            params = [int(cv2.IMWRITE_PNG_COMPRESSION), 3]  # 0-9
        else:
            params = []

        item = (filepath, image_bgr, encode_ext, params)
        try:
            self._q.put_nowait(item)
            return True
        except queue.Full:
            self._dropped += 1
            self._maybe_log_stats()
            return False

    # ---------------- Worker ----------------
    def _worker(self):
        while not self._stop_evt.is_set() or not self._q.empty():
            try:
                item = self._q.get(timeout=0.1)
            except queue.Empty:
                self._maybe_log_stats()
                continue
            try:
                self._process_item(item)
                self._written += 1
            except Exception as e:
                self._failed += 1
                logger.error(f'AsyncImageSaver worker exception: {e}\n{traceback.format_exc()}')
            finally:
                self._q.task_done()
                self._maybe_log_stats()

    def _process_item(self, item):
        filepath, image_bgr, encode_ext, params = item
        # Encode in memory, then atomic write to disk
        ok, buf = cv2.imencode(encode_ext, image_bgr, params)
        if not ok:
            raise RuntimeError(f'imencode failed for ext={encode_ext} path={filepath}')

        tmp_path = filepath + '.tmp'
        with open(tmp_path, 'wb') as f:
            f.write(buf.tobytes())
        os.replace(tmp_path, filepath)

    def _maybe_log_stats(self):
        now = time.time()
        if now - self._last_log_ts >= self._log_interval:
            qsize = self._q.qsize()
            logger.info(f'AsyncImageSaver stats: queue={qsize}, written={self._written}, dropped={self._dropped}, failed={self._failed}')
            self._last_log_ts = now

    # ---------------- Back-compat no-ops ----------------
    def setSnapshotFlag(self):
        """Some legacy code calls this after stop_prediction/saveFinalResult."""
        with self._flag_lock:
            self._snapshot_flag = True
        logger.info('AsyncImageSaver: snapshot flag set (compat).')

    def clearSnapshotFlag(self):
        with self._flag_lock:
            self._snapshot_flag = False
        logger.info('AsyncImageSaver: snapshot flag cleared (compat).')

    def getSnapshotFlag(self):
        with self._flag_lock:
            return self._snapshot_flag


class NullImageSaver:
    """No-op drop-in with the same API to avoid None checks or attribute errors."""
    def start(self): 
        return self
    def stop(self, drain_timeout_sec=0): 
        return None
    def enqueue(self, filepath, image_bgr, encode_ext=None, quality=90):
        return False
    # Back-compat no-ops:
    def setSnapshotFlag(self): 
        return None
    def clearSnapshotFlag(self): 
        return None
    def getSnapshotFlag(self): 
        return False
