# encoding=utf-8

import cv2
import numpy as np
from cardinfo import CardInfo, GetCardVal
from datamanager import DataMgrInstance
from scanresultsave import ScanRMgrInstance
import pylogger as logger
from twisted.internet import reactor
import time
from skimage.metrics import structural_similarity as compare_ssim # tf2.1
from config import cfg
import subprocess

# 20241025 add a button for manual predict process
import tkinter as tk
from tkinter import Button
# Add this line to start the Tkinter UI inside Twisted's event loop
from twisted.internet import tksupport
# 20241029 put imageSaver code in here
import datetime as d
import os
import sys

# 20251203 --- resilience & latency ---
from stream_resilience import SafeCapture, add_ffmpeg_reconnect_params, disable_windows_quickedit
import latency_round

class VideoManager(object):
    def __init__(self, gametype, stream, videowidth, videoheight, poslist, dealer, detector, \
        imageSaver, onelabel, freq, tilt_angle, save_predictions, save_full_image, savedir, video_loop, \
        window_resize_width=640, window_resize_height=480):
        # Initialize class variables
        self.gametype = gametype
        self.stream = stream
        self.config_videowidth = videowidth
        self.config_videoheight = videoheight
        self.config_poslist = poslist
        self.dealer = dealer
        self.detector = detector
        self.imageSaver = imageSaver
        self.onelabel = onelabel
        self.config_freq = freq
        self.skip_freq = 10
        self.resultlist = []
        self.first_predict = True  # Flag to handle the first prediction
        self.stopRun = False
        self.isExit = False
        self.resize_width = window_resize_width
        self.resize_height = window_resize_height
        DataMgrInstance().setgametype(gametype)
        DataMgrInstance().register_ImageSaver(imageSaver)
        # 20240926 tilt_angle
        self.tilt_angle = tilt_angle
        # pause mechanic
        self.paused = False  # Track pause/play state
        self.last_click_time = 0  # Track time of last click to detect double-click
        # 20241025 新增按鈕，手動決定什麼時候開始預測
        self.use_manual_flag = False  # Track if manual predictFlag is being used
        self.predictFlag_manual = False  # Custom flag to control prediction
        self.paused = False  # Track pause/play state
        self.root = None # 20241112 cancael setup_ui() # self.setup_ui()  # 20241025 Set up Tkinter UI
        # 20241025 toggle save predictions(I/O save to local disk)
        self.save_predictions = save_predictions
        self.save_full_image = save_full_image
        # 20241029 把imagesaver功能放到這
        # Audit directory for storing snapshot images with timestamps
        self.auditDir = savedir

        # 20250407 新增一個為了檢驗小圖片的功能
        self.last_gmcode = None
        self.detection_order = []      # or whatever structures you use
        self.rois_by_index = {}
        self.last_zoomed_display = None

        # ---- Latency dispatch-cycle (gmtype == 'lattest') ----
        # Each accepted dispatch starts a new "dispatch-cycle" for an index.
        # We must SEND/SAVE exactly once per dispatch-cycle (avoid duplicates).
        # Keys use: (gmcode_show, index, cycle_id)
        self._cardback_sent_keys = set()
        self._cardback_saved_keys = set()
        self._lattest_saved_prediction_keys = set()

        # 20251005 video loop option
        self.video_loop = video_loop

        # 20251203 --- resilience & latency ---
        self.paused = False
        self.last_zoomed_display = None
        self.stream_videowidth = 0
        self.stream_videoheight = 0
        self.rois_by_index = {}
        self.detection_order = []
        self.mouse_down = False
        self.mouse_start = None
        self.mouse_end = None
        self.last_frame_ts = 0.0
        self.keep_running = True

        # ---- UI resilience (OpenCV window may be temporarily unavailable on Windows) ----
        self._ui_enabled = True
        self._ui_next_retry_ts = 0.0
        self._ui_fail_count = 0
        self._ui_last_fail_log_ts = 0.0
        self._ui_retry_interval_sec = 1.0

    # 20241025
    def setup_ui(self):
        '''
        Set up Tkinter UI with a button to toggle the prediction process.
        '''
        self.root = tk.Tk()
        self.root.title("Prediction Control")
        # Initial button to ask if user wants to use manual predictFlag
        self.initial_manual_button = Button(self.root, text="Use manual predictFlag?", command=self.set_manual_flag)
        self.initial_manual_button.pack()

    def set_manual_flag(self):
        '''
        Set the manual prediction flag, remove the initial button, and create a toggle button for manual prediction.
        '''
        self.use_manual_flag = True
        logger.info('User chose to use manual predictFlag.')
        # Remove initial button and create a toggle button
        self.initial_manual_button.destroy()  # Remove the initial button
        self.toggle_button = Button(self.root, text="Start Prediction", command=self.toggle_prediction)
        self.toggle_button.pack()
    
    # 20241025
    def toggle_prediction(self):
        '''
        Toggle the prediction flag when the button is clicked.
        '''
        self.predictFlag_manual = not self.predictFlag_manual
        if self.predictFlag_manual:
            self.toggle_button.config(text="Stop Prediction")
            logger.info('Prediction started manually.')
        else:
            self.toggle_button.config(text="Start Prediction")
            logger.info('Prediction stopped manually.')

    def mouse_callback(self, event, x, y, flags, param):
        '''
        Handles mouse events, specifically detecting double-clicks to pause/resume the video.
        '''
        if event == cv2.EVENT_LBUTTONDBLCLK:
            self.toggle_pause_resume()

    def toggle_pause_resume(self):
        '''
        Toggle between pausing and resuming the video and processes.
        '''
        if self.paused:
            self.paused = False
            logger.info('Resuming video and processes...')
        else:
            self.paused = True
            logger.info('Pausing video and processes...')

    def start(self):
        # # 20241025
        # # Integrate Tkinter with Twisted reactor
        if self.root:
            tksupport.install(self.root)  # This ensures Tkinter's main loop runs in sync with Twisted's event loop
        # Start the video processing in a separate thread
        reactor.callInThread(self.run)

    def run(self):
        '''
        This loop ensures continuous video processing until stopRun is True.
        '''
        playVideoCount = 0
        try:
            while not self.stopRun:
                # Play video stream and process frames
                ifopenVideo = self.playVideo(self.stream, self.config_poslist, self.detector)
                if self.isExit or not ifopenVideo:
                    self.cleanup(playVideoCount)
                    break
        except Exception as e:
            logger.error(f"VideoManager crashed: {e}")  # 會印完整 traceback

    def cleanup(self, playVideoCount):
        '''
        Cleanup resources and stop the reactor when the video processing is done or fails.
        '''
        if playVideoCount > 20:
            logger.info(f'openVideo failed, exit after {playVideoCount} attempts')
        self.stopRun = True
        cv2.destroyAllWindows()
        self.imageSaver.stop()
        reactor.callFromThread(reactor.stop)
        if self.root:
            self.root.quit()  # Close the Tkinter window

    def camera_check(self, cap):
        '''
        Check if the camera is operational by comparing a test frame with an error template.
        '''
        if cap.isOpened():
            success, frame = cap.read()
            if success and frame is not None:
                error_template = cv2.imread('./models/error_frame.jpg')
                if error_template is not None:
                    # Compare frames using SSIM to check for errors
                    score = compare_ssim(cv2.GaussianBlur(frame, (11, 11), 0), error_template, multichannel=True)
                    return score < 0.99
            logger.info("Camera read failed or error frame comparison failed")
        return False

    # helper: rewind or reopen a file source
    def _restart_video(self, cap, source_path):
        # try seeking to the beginning
        try:
            cap.set(cv2.CAP_PROP_POS_FRAMES, 0)
            ok, _ = cap.read()
            if ok:
                cap.set(cv2.CAP_PROP_POS_FRAMES, 0)  # go back again after the probe
                return cap
        except Exception:
            pass
        # fallback: reopen
        try:
            cap.release()
        except Exception:
            pass
        return cv2.VideoCapture(source_path)

    def _write_image(self, filepath, bgr_image):
        """
        Write an image to disk without blocking the main predict loop.
        If an AsyncImageSaver is attached, enqueue; otherwise fallback to cv2.imwrite.
        """
        try:
            saver = getattr(self, "imageSaver", None)
            if saver and hasattr(saver, "enqueue"):
                ok = saver.enqueue(filepath, bgr_image)
                if not ok:
                    logger.warning(f'Async saver dropped image (queue full): {filepath}')
                return ok
            # Fallback (blocking)
            import cv2, os
            os.makedirs(os.path.dirname(filepath), exist_ok=True)
            cv2.imwrite(filepath, bgr_image)
            return True
        except Exception as e:
            logger.error(f'_write_image failed for {filepath}: {e}')
            return False

    def _prepare_predict_bgr_and_zoom(self, predict_image, predict_image_bgr=None, zoom_size=(200, 300)):
        """
        Return (predict_image_bgr, zoomed_roi) safely.
        - Always tries to make a 3-channel BGR from `predict_image` if `predict_image_bgr` is None.
        - If nothing valid, returns (None, None).
        - Never raises on bad/empty inputs.
        """
        import cv2
        import numpy as np

        bgr = predict_image_bgr
        try:
            # If caller didn't prepare a BGR image, normalize from `predict_image`
            if bgr is None and predict_image is not None:
                if isinstance(predict_image, np.ndarray) and predict_image.size > 0:
                    if predict_image.ndim == 2:  # grayscale
                        bgr = cv2.cvtColor(predict_image, cv2.COLOR_GRAY2BGR)
                    elif predict_image.ndim == 3:
                        c = predict_image.shape[2]
                        if c == 3:
                            bgr = predict_image
                        elif c == 4:
                            bgr = cv2.cvtColor(predict_image, cv2.COLOR_BGRA2BGR)
                        else:
                            bgr = None
                else:
                    bgr = None
        except Exception as e:
            try:
                logger.warning(f'_prepare_predict_bgr_and_zoom: normalize failed: {e}')
            except Exception:
                pass
            bgr = None

        # Make zoomed ROI if we have a valid BGR
        zoomed = None
        try:
            if bgr is not None and getattr(bgr, 'size', 0) > 0:
                zoomed = cv2.resize(bgr, zoom_size)
        except Exception as e:
            try:
                logger.warning(f'_prepare_predict_bgr_and_zoom: resize failed: {e}')
            except Exception:
                pass
            zoomed = None

        return bgr, zoomed

    def _is_network_stream(self, src: str) -> bool:
        """
        Heuristic: if it has '://', treat as network stream (rtmp/rtsp/http/https/udp/tcp/rtml...).
        Otherwise assume local file path.
        """
        if not isinstance(src, str):
            return False
        s = src.strip().lower()
        if "://" in s:
            # allow-list of common schemes, but anything with :// is good enough
            return True
        return False

    def playVideo(self, videoname, poslist, detector):
        '''
        Opens the video stream, reads frames, and processes them. Incorporates pausing/resuming functionality.
        '''
        logger.info(f'Starting video stream: {videoname}')

        # Decide source type
        is_stream = self._is_network_stream(videoname)

        # Avoid Windows console “QuickEdit” freezes (“press Enter to resume”)
        disable_windows_quickedit()
        # Open capture with low-latency hints for network streams
        cap = None
        grabber = None

        if is_stream:
            latency_round.set_video_url(videoname)
            # Add FFmpeg reconnect params & expose url to latency
            params_videoname = add_ffmpeg_reconnect_params(videoname)

            # Optional: CAP_PROP_BUFFERSIZE hint (smaller buffer = lower latency)
            _cap_buf = getattr(cfg, 'cap_buffersize', None)
            try:
                cap_opts = {cv2.CAP_PROP_BUFFERSIZE: float(_cap_buf)} if _cap_buf not in (None, "", 0, 0.0) else None
            except Exception:
                cap_opts = None

            # Open resilient capture (auto-reopen on read failure)
            # NOTE: if user explicitly sets cap_buffersize, don't overwrite it with set_small_buffer default.
            cap = SafeCapture(
                params_videoname,
                max_open_retries=12,
                reopen_backoff_sec=1.0,
                set_small_buffer=False if cap_opts else True,
                options=cap_opts,
            )
            # Pick publish FPS for network streams:
            # - stream_publish_fps (preferred)
            # - else max_grab_fps (back-compat)
            # - else 60
            max_fps = float(getattr(cfg, 'max_grab_fps', 0.0) or 0.0)
            try:
                publish_fps = float(getattr(cfg, 'stream_publish_fps', 0.0) or 0.0)
            except Exception:
                publish_fps = 0.0
            if publish_fps <= 0.0:
                publish_fps = max_fps if max_fps > 0.0 else 60.0

            # Keep `target_fps` for UI pacing / logs
            target_fps = publish_fps

            # Let the grabber own the draining loop and only publish the newest frame at target_fps
            drain_max = int(getattr(cfg, 'stream_drain_grab_max', 200) or 200)
            grabber = LatestFrameGrabber(cap=cap, publish_fps=target_fps, drain_grab_max=drain_max)
            # We will not call cap.read() directly after this point
        else:
            cap = cv2.VideoCapture(videoname)
            # Optional: CAP_PROP_BUFFERSIZE hint (where supported)
            _cap_buf = getattr(cfg, 'cap_buffersize', None)
            if _cap_buf not in (None, "", 0, 0.0):
                try:
                    cap.set(cv2.CAP_PROP_BUFFERSIZE, float(_cap_buf))
                except Exception:
                    pass

            # Compute target FPS (for file/capture loop pacing)
            max_fps = float(getattr(cfg, 'max_grab_fps', 0.0) or 0.0)
            src_fps = float(cap.get(cv2.CAP_PROP_FPS) or 0.0)
            target_fps = src_fps if src_fps > 1e-3 else (max_fps if max_fps > 0 else 0.0)
            if max_fps > 0 and target_fps > 0:
                target_fps = min(target_fps, max_fps)

        # UI pacing: use target_fps if available
        try:
            self._ui_wait_ms = max(1, int(round(1000.0 / target_fps))) if target_fps and target_fps > 0 else 1
        except Exception:
            self._ui_wait_ms = 1
            
        self.stream_videowidth = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
        self.stream_videoheight = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
        
        # 20241024 refactor後程式碼只使用stream真實的解析度，這邊寫log紀錄config(crop tool時的解析度)跟stream不一樣解析度的情況
        if self.config_videowidth != self.stream_videowidth:  # float `width`
            # 20241122 解析度不對就直接離開程式
            logger.info(f"WARNING : config videowidth is {self.config_videowidth}, but the stream videowidth is {self.stream_videowidth}, exit program")
            reactor.callFromThread(reactor.stop)
            self.isExit = True
            raise ValueError('config videowidth and stream videowidth mismatch')
            
            # 20241024 config裡的解析度是當初crop_tool抓取的影片的解析度，因此pos_list解析度也應做同樣的調整
            logger.info(f"WARNING : config videowidth is {self.config_videowidth}, but the stream videowidth is {self.stream_videowidth}, use stream videowidth instead")
            # Calculate the rectangle coordinates based on the real frame
            for pos in poslist:
                pos.xmin = int(pos.xmin * self.stream_videowidth / self.config_videowidth)
                pos.xmax = int(pos.xmax * self.stream_videowidth / self.config_videowidth)

        if self.config_videoheight != self.stream_videoheight:
            # 20241122 解析度不對就直接離開程式
            logger.info(f"WARNING : config videoheight is {self.config_videoheight}, but the stream videoheight is {self.stream_videoheight}, exit program")
            reactor.callFromThread(reactor.stop)
            self.isExit = True
            raise ValueError('config videoheight and stream videoheight mismatch')

            # 20241024 config裡的解析度是當初crop_tool抓取的影片的解析度，因此pos_list解析度也應做同樣的調整
            logger.info(f"WARNING : config videoheight is {self.config_videoheight}, but the stream videoheight is {self.stream_videoheight}, use stream videoheight instead")
            # Calculate the rectangle coordinates based on the real frame
            for pos in poslist:
                pos.ymin = int(pos.ymin * self.stream_videoheight / self.config_videoheight)
                pos.ymax = int(pos.ymax * self.stream_videoheight / self.config_videoheight)

        if isinstance(videoname, int): # 如果是int类型就代表用的采集卡，就得调整下视频流的大小
            self.adjust_capture_settings(cap)

        if not cap.isOpened():
            logger.info('cap.isOpened() failed')
            return False
        
        nframe = 0
        frame_id = 0 # 數第幾個frame時使用
        skip_freq = self.skip_freq
        winname = 'detector tf2'
        # Set the mouse callback for the window
        cv2.namedWindow(winname)
        cv2.setMouseCallback(winname, self.mouse_callback)

        is_file_source = isinstance(videoname, (str, bytes, os.PathLike)) and os.path.exists(videoname)
        total_frames = int(cap.get(cv2.CAP_PROP_FRAME_COUNT) or 0)

        while True:
            if not self.paused:
                # Read a frame
                if is_stream:
                    frame = grabber.get()
                    if frame is None:
                        time.sleep(0.005)
                        continue
                    ret = True
                else:
                    ret, frame = cap.read()
                    
                frame_id += 1
                is_card_detected = False

                if not ret or frame is None:
                    # EOF for files: loop back to start
                    if is_file_source and total_frames > 0:
                        if self.video_loop:
                            logger.info('Reached end of video. Restarting from beginning...')
                            cap = self._restart_video(cap, videoname)
                            frame_id = 0
                            time.sleep(0.05)  # avoid busy loop
                            continue
                        else:
                            logger.info(f'Reached end of video. Stops program since video_loop is set to {self.video_loop}')
                    logger.info('Failed to read frame from video (retrying)...')
                    time.sleep(0.05)
                    continue

                # Rotate the frame based on self.tilt_angle
                if self.tilt_angle != 0:
                    frame = self.rotate_frame(frame, self.tilt_angle)

                # Process and display frame
                predictFlag = DataMgrInstance().getPredictFlag()
                gmcode = DataMgrInstance().getGamecode()
                gmcode_show = gmcode
                # Check if gmcode is in bytes, if so decode it to a string
                if isinstance(gmcode, bytes):
                    gmcode_show = gmcode.decode('utf-8').rstrip('\x00')

                nframe += 1
                # 20241114 解決開始預測時(當荷官端發射開始預測信號)程式跑比較慢(影片開始與實際影片流呈現延遲，因積累還來不及處理的frames)
                # 這邊implement 如果持續預測空牌，則設定一個比較慢的頻率去偵測
                # isDetect 代表隔幾個frame去做一次 模型預測
                isDetect = nframe >= skip_freq
                if isDetect:
                    nframe = 0

                # 20241025
                # Use manual predictFlag if the user has chosen to use it
                if self.use_manual_flag:
                    predictFlag = self.predictFlag_manual
                else:
                    predictFlag = DataMgrInstance().getPredictFlag()

                if predictFlag and gmcode:
                    self.resultlist = []  # Clear results
                    is_card_detected = self.process_frame(frame, poslist, gmcode, detector, isDetect, gmcode_show, frame_id)
                    if len(self.resultlist) > 0:
                        DataMgrInstance().addResultlist(gmcode, self.resultlist)
                        # 20241205 打算在這邊埋log，印出現有result list裡的card info的attribute(花色、數值等)
                        # logger.info(f"self.resultlist after process_frame :  {self.resultlist}")
                        # logger.info(f"")

                # Display frame
                self.display_frame(frame, winname, gmcode, gmcode_show, frame_id)

                if is_card_detected:
                    skip_freq = self.config_freq
                    if self.save_full_image:
                        # save_last_frame 存大圖
                        last_frame = frame.copy()
                        self.save_full_img(gmcode, last_frame, gmcode_show)
                else:
                    skip_freq = self.skip_freq

                frame_id += 1

            # Exit condition
            # IMPORTANT: do not let OpenCV window state crash/stop the service.
            # User can press 'q' to exit; window minimize/move/close will only disable UI temporarily.
            key = cv2.waitKey(getattr(self, '_ui_wait_ms', 1))
            if key & 0xFF == ord('q'):
                self.stopRun = True
                logger.error('Exiting...')
                try:
                    cv2.destroyAllWindows()
                except Exception:
                    pass
                reactor.callFromThread(reactor.stop)
                self.isExit = True
                break

            # If the window is closed/unavailable, keep running headless and periodically retry.
            if self._ui_can_try() and self._ui_enabled:
                try:
                    prop = cv2.getWindowProperty(winname, cv2.WND_PROP_AUTOSIZE)
                    if prop < 1:
                        self._ui_mark_failed("getWindowProperty<1", RuntimeError("window closed"))
                except cv2.error as e:
                    self._ui_mark_failed("getWindowProperty", e)

        # Clean shutdown (stream grabber thread must stop BEFORE releasing capture)
        try:
            if grabber is not None:
                grabber.release()
        except Exception:
            pass

        try:
            if cap is not None and hasattr(cap, 'isOpened') and cap.isOpened():
                cap.release()
        except Exception:
            pass

    def adjust_capture_settings(self, cap):
        '''
        Adjust settings for camera capture if the input is a live video feed (e.g., from a camera).
        '''
        counter = 0
        while counter <= 10:
            if cap.isOpened():
                cap.release()
            cap = cv2.VideoCapture(self.stream)
            cap.set(cv2.CAP_PROP_FOURCC, cv2.VideoWriter.fourcc('M', 'J', 'P', 'G'))
            cap.set(cv2.CAP_PROP_FPS, 30)
            stream_width = cap.get(cv2.CAP_PROP_FRAME_WIDTH)
            stream_height = cap.get(cv2.CAP_PROP_FRAME_HEIGHT)
            cap.set(cv2.CAP_PROP_FRAME_WIDTH, stream_width)
            cap.set(cv2.CAP_PROP_FRAME_HEIGHT, stream_height)
            logger.info(f"cv2.CAP_PROP_FRAME_WIDTH set to : {stream_width}, cv2.CAP_PROP_FRAME_HEIGHT set to : {stream_height}")

            if self.camera_check(cap):
                break
            
            counter += 1

    # =========================
    # Card-back (class 0) support
    # =========================
    def _get_score_threshold(self, classid: int, default: float = 0.5) -> float:
        # Best-effort score threshold lookup from cfg.scoremap, with safe fallback.
        sm = getattr(cfg, 'scoremap', None)
        if sm is None:
            return float(default)
        try:
            return float(sm[classid])
        except Exception:
            try:
                return float(sm.get(classid, default))
            except Exception:
                return float(default)

    def _send_cardback_viewonly_once(self, gmcode, gmcode_show, pos, predict_image, score, predict_classid=0):
        """Send + save card-back (classid=0) exactly once per dispatch-cycle.

        Latency mode change:
        - Cardback is now treated as a NORMAL prediction result.
        - Once cardback is reported, this dispatch-cycle is DONE and the index must stop scanning
          until the next DispatchIndex arrives.
        """

        # IMPORTANT:
        # Cardback-as-result is ONLY valid for latency mode (gmtype == 'lattest').
        # In DT/BAC normal modes, cardback must be ignored entirely (do not send / do not mark done).
        if getattr(DataMgrInstance(), 'gmtype', None) != 'lattest':
            return

        # dispatch-cycle id (lattest only). For other modes, cycle_id=0.
        try:
            cycle_id = DataMgrInstance().get_lattest_dispatch_cycle_id(int(pos.index))
        except Exception:
            cycle_id = 0
        key = (str(gmcode_show), int(pos.index), int(cycle_id))

        # Threshold guard: only send card-back when its score is confident enough.
        th = self._get_score_threshold(0, default=0.0)
        try:
            score_f = float(score)
        except Exception:
            score_f = 0.0

        if score_f < float(th):
            return

        # 1) send once per dispatch-cycle
        if key not in self._cardback_sent_keys:
            self._cardback_sent_keys.add(key)

            # Build a minimal CardInfo so dealer can see "cardback" event
            dealer_classid = 0
            card_point = 0
            result = CardInfo(pos.index, dealer_classid, int(predict_classid), card_point, score_f)

            # Anchor is for overlay/debug; just fill the ROI
            try:
                h, w = predict_image.shape[:2]
                result.setAnchor(pos, 0, 0, w, h, f'BACK({score_f:.4f})')
            except Exception:
                pass

            try:
                if hasattr(DataMgrInstance(), 'senddata') and DataMgrInstance().senddata:
                    DataMgrInstance().senddata([result])
            except Exception as e:
                try:
                    logger.info(f'cardback senddata failed: {e}')
                except Exception:
                    pass

        # 2) complete this dispatch-cycle -> stop scanning until next dispatch
        try:
            DataMgrInstance().lattest_mark_cycle_done(gmcode, int(pos.index))
        except Exception:
            pass

        # 3) save image once per dispatch-cycle
        if not self.save_predictions:
            return
        if key in self._cardback_saved_keys:
            return
        self._cardback_saved_keys.add(key)

        try:
            if not os.path.exists("./predict_images"):
                os.mkdir("./predict_images")
            newDir = os.path.join("./predict_images", d.datetime.now().strftime('%Y-%m-%d'))
            if not os.path.exists(newDir):
                os.mkdir(newDir)

            # Match Jieqi-ish format, but mark as BACK and #0
            fmt_str = f'{gmcode_show}_{pos.index}_#0_BACK@{int(predict_classid)}({score_f:0.4f})'
            filename = d.datetime.now().strftime('%Y%m%d%H%M_') + fmt_str + '.jpg'
            filepath = os.path.join(newDir, filename)

            # predict_image is RGB here; convert back to BGR for cv2.imwrite
            predict_image_bgr = cv2.cvtColor(predict_image, cv2.COLOR_RGB2BGR)
            self._write_image(filepath, predict_image_bgr)
        except Exception as e:
            try:
                logger.info(f'cardback save failed: {e}')
            except Exception:
                pass

        # done

    def process_frame(self, frame, poslist, gmcode, detector, isDetect, gmcode_show, frame_id):
        '''
        Process each frame to detect card values and save predictions.
        '''
        # 1) Compare current gmcode to self.last_gmcode
        if gmcode != self.last_gmcode:
            # This means a new game code just arrived
            # logger.info(f"New game code detected: {gmcode}. Clearing old data.")
            self.detection_order.clear()
            self.rois_by_index.clear()
            self.last_zoomed_display = None

            # New round: clear per-round/per-cycle de-dup caches.
            # Keys: (gmcode_show, index, cycle_id)
            try:
                self._cardback_sent_keys.clear()
                self._cardback_saved_keys.clear()
                self._lattest_saved_prediction_keys.clear()
            except Exception:
                pass

            self.last_gmcode = gmcode  # update so we won't clear again until next game code changes

        # 2) Proceed with your normal detection logic
        is_card_detected = False # 當卡牌有預測出來時(不論只預測出卡牌點數，還是卡牌花色，還是兩個都有)，save_all變為True

        # NOTE: There are TWO different classid semantics in this system:
        # - gmtype == 'lattest' (Latency): classid=0 cardback, classid=1 real-card, else => empty/unknown.
        # - normal DT/BAC modes: classid in [1..52] are real cards; classid=0 is cardback;
        #   other values (e.g. 53, 99) mean empty/unknown and MUST NOT complete an index.
        is_lattest = (getattr(DataMgrInstance(), 'gmtype', None) == 'lattest')
        for pos in poslist:
            # logger.info(f'Current in position {pos.index} ...')
            if DataMgrInstance().getIsDispatch(gmcode, pos.index):
                # logger.info(f'postion {pos.index} dispatched, no need to detect')
                continue

            if DataMgrInstance().isincurCardList(gmcode, pos.index) == False:
                # 判断当前索引是否在下一个要扫描的列表里，如果不在就continue
                # logger.info(f'postion {pos.index} not in curCardList, no need to detect')
                continue

            if (isDetect or self.first_predict):
                self.first_predict = False
                predict_image = frame[pos.ymin:pos.ymax, pos.xmin:pos.xmax]

                # 20241209 cv2 read frame is BGR in default.... compared to tf.io.read_file is RGB default
                begin_time = lambda: int(round(time.time() * 1000))
                preprocess_and_save_result_begin_time = begin_time()
                predict_image = cv2.cvtColor(predict_image, cv2.COLOR_BGR2RGB)
                predict_suits, predict_cardval, desc, score, classid = self.predict_card(detector, predict_image, gmcode, pos, frame_id)

                cid = int(classid)

                if is_lattest:
                    # ---- Latency semantics ----
                    # classid=0 cardback: send as view-only once per dispatch-cycle (latency only)
                    if cid == 0:
                        self._send_cardback_viewonly_once(
                            gmcode=gmcode,
                            gmcode_show=gmcode_show,
                            pos=pos,
                            predict_image=predict_image,
                            score=score,
                            predict_classid=classid,
                        )
                        is_card_detected = True
                    # classid=1: real-card path (desc should be non-empty when suit/value are valid)
                    elif cid == 1 and desc:
                        self.send_prediction(gmcode_show, pos, predict_image, desc, score, predict_suits, predict_cardval, classid)
                        is_card_detected = True
                    else:
                        # Empty / unknown in latency mode: do nothing here.
                        # (Dealer-side latency loop already handles re-dispatching until real card.)
                        pass
                else:
                    # ---- DT/BAC normal semantics ----
                    # Only accept real cards (1..52). Anything else (0 cardback, 53/99 empty/unknown) must be ignored.
                    if (1 <= cid <= 52) and desc:
                        self.send_prediction(gmcode_show, pos, predict_image, desc, score, predict_suits, predict_cardval, classid)
                        is_card_detected = True
                    else:
                        # ignore non-terminal
                        pass
                end_time = lambda: int(round(time.time() * 1000))
                preprocess_and_save_result_end_time = end_time()
                logger.info(f'preprocess_and_save_result_time(C++ timespan reference) time = {preprocess_and_save_result_end_time - preprocess_and_save_result_begin_time}')

        return is_card_detected

    def predict_card(self, detector, image, gmcode, pos, frame_id):
        '''
        Predict card value based on the input image.
        '''
        # 20241205 以下前處理(灰化)tf2不需要，會影響模型
        # image_gray = cv2.cvtColor(cv2.cvtColor(image, cv2.COLOR_BGR2GRAY), cv2.COLOR_GRAY2BGR)
        # if self.gametype == 'BAC' and pos.index > 4:
        #     image_gray = cv2.flip(cv2.transpose(image_gray), 1)

        if self.onelabel:
            # return detector.do_predict_one_label(image, gmcode, pos.index, False, frame_id)
            return detector.do_predict_one_label_jk_preprocess(image, gmcode, pos.index, False, frame_id)
        return detector.do_predict_multi_label(image, gmcode, pos.index) # 20240920 do_predict_multi_label已被comment out，要使用的話必須修改

    def send_prediction(self, gmcode_show, pos, predict_image, desc, score, predict_suits, predict_cardval, predict_classid):
        # 設定要儲存到data manager resultlist的卡牌
        score = predict_cardval.score + predict_suits.score
        logger.info(f'predict_cardval.score : {predict_cardval.score}, predict_suits.score : {predict_suits.score}')
        card_point = predict_cardval.classid # predict instance(cardval)的classid為點數, predict instance(suites)為14 15 16 17 對應梅 方 紅 黑
        dealer_classid = GetCardVal(predict_suits.classid, predict_cardval.classid)
        result = CardInfo(pos.index, dealer_classid, predict_classid, card_point, float(score / 2.0))
        save_score = result.score
        box = predict_suits.box
        height = predict_image.shape[0]
        width = predict_image.shape[1]
        ymin = int(box[0] * height)
        xmin = int(box[1] * width)
        ymax = int(box[2] * height)
        xmax = int(box[3] * width)
        result.setAnchor(pos, xmin, ymin, xmax-xmin, ymax-ymin, '%s(%.4f)' % (desc, save_score))
        self.resultlist.append(result)

        # 20241029 原ImagerSaver.save()
        # 儲存圖片到本機
        if self.save_predictions:
            strgmcode = gmcode_show

            # Latency mode: save exactly ONCE per dispatch-cycle
            do_save = True
            if DataMgrInstance().gmtype == 'lattest':
                try:
                    cycle_id = DataMgrInstance().get_lattest_dispatch_cycle_id(int(pos.index))
                except Exception:
                    cycle_id = 0
                save_key = (str(strgmcode), int(pos.index), int(cycle_id))
                if save_key in self._lattest_saved_prediction_keys:
                    do_save = False
                else:
                    self._lattest_saved_prediction_keys.add(save_key)

            if do_save:
                # fmt_str = '%s_%d_%s(%.4f)' % (strgmcode, pos.index, desc, save_score)
                # 20241113 match jieqi's format
                fmt_str = f'{strgmcode}_{pos.index}_#{dealer_classid}_{desc}@{predict_classid}({save_score:0.4f})'
                if not os.path.exists("./predict_images"):
                    os.mkdir("./predict_images")

                newDir = os.path.join("./predict_images", d.datetime.now().strftime('%Y-%m-%d'))
                if not os.path.exists(newDir):
                    os.mkdir(newDir)

                # Generate filename based timestamped
                filename = d.datetime.now().strftime('%Y%m%d%H%M_') + fmt_str + '.jpg'
                # 20240919 .strftime('%Y%m%d%H%M%S%f_') 改為 .strftime('%Y%m%d%H%M_')，以分鐘為單位保存圖片，不然同張卡牌惠存一堆圖片
                filepath = os.path.join(newDir, filename)

                # 20241211 因前面有bgr2rgb 現在cv2要轉回來 才能存下正確顏色的圖片
                predict_image_bgr = cv2.cvtColor(predict_image, cv2.COLOR_RGB2BGR)
                self._write_image(filepath, predict_image_bgr)
            else:
                predict_image_bgr = None
            
            # ScanRMgrInstance().saveDataToCsv(gmcode, pos.index, cardVal, desc, score) # 原本imageSaver.save裡面的.write有這段，現在我先取消
            # dealerclient onSaveFinalResult會存 不知道這裡要存要幹嘛

        # 20250407 add zoomed in cards
        # Let's create a zoomed ROI
        predict_image_bgr, zoomed_roi = self._prepare_predict_bgr_and_zoom(
            predict_image=predict_image,
            predict_image_bgr=locals().get('predict_image_bgr', None),
            zoom_size=(200, 300)
        )
        
        # If it's first time seeing this card index this game, track it in the order
        if pos.index not in self.detection_order:
            self.detection_order.append(pos.index)

        # Store or overwrite the ROI for this index
        self.rois_by_index[pos.index] = zoomed_roi

    def save_full_img(self, gmcode, frame, gmcode_show):
        '''
        Draw the best result on the frame and save to local img 存大圖.
        '''
        filename = ''
        filepath = ''

        # 20241029
        # bestResultlist = DataMgrInstance().getBestResultlist(gmcode, 1)
        # mean_score = sum(result.score for result in bestResultlist) / len(bestResultlist) 
        # filename, filepath = self.imageSaver.putSnapshotQueue(gmcode, 0, 'full', mean_score, frame)
        # 把putSnapshotQueue 拆過來放這
        strgmcode = gmcode_show
        fmt_str = '%s' % strgmcode
        # newDir = os.path.join(self.auditDir, d.datetime.now().strftime('%Y-%m-%d'))

        if not os.path.exists(self.auditDir):
            os.mkdir(self.auditDir)

        # Generate filename based timestamped
        # filename = d.datetime.now().strftime('%Y%m%d%H%M%S%f_') + fmt_str + '.jpg'
        filename = fmt_str + '.jpg' # 只保留一分鐘一張
        filepath = os.path.join(self.auditDir, filename)
        # logger.info('write full image, image file path =%s' % (filepath))

        # 20241127 存大圖也將牌局名稱印在左上角，對齊detector秀的frame
        # Display gmcode on the top-left corner of the window
        # Define font, position, and other text parameters
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1
        font_color = (255, 255, 255)  # 白
        thickness = 2
        position = (10, 30)  # Coordinates for the top-left corner
        cv2.putText(frame, f'{gmcode_show}', position, font, font_scale, font_color, thickness, cv2.LINE_AA)
        self._write_image(filepath, frame)

        return filename, filepath


    # =========================
    # UI resilience helpers
    # =========================
    def _ui_can_try(self) -> bool:
        """Whether we should attempt to touch OpenCV UI APIs this loop."""
        now = time.time()
        return self._ui_enabled or (now >= self._ui_next_retry_ts)

    def _ui_mark_failed(self, context: str, err: Exception) -> None:
        """Disable UI temporarily and schedule a retry."""
        now = time.time()
        self._ui_enabled = False
        self._ui_fail_count += 1
        self._ui_next_retry_ts = now + float(getattr(self, "_ui_retry_interval_sec", 1.0))

        # Rate-limit logs (avoid spamming if the window is minimized/moved frequently)
        if now - self._ui_last_fail_log_ts >= 2.0:
            self._ui_last_fail_log_ts = now
            try:
                logger.warning(f"[UI] OpenCV window unavailable ({context}). Continue headless; will retry. err={err}")
            except Exception:
                pass

    def _ui_try_recover(self, winname: str) -> None:
        """Best-effort re-create the window after temporary failures."""
        # Only called when _ui_can_try() is True.
        try:
            # Create window if missing; if it already exists, OpenCV ignores.
            cv2.namedWindow(winname, cv2.WINDOW_NORMAL)
            try:
                cv2.setMouseCallback(winname, self.mouse_callback)
            except Exception:
                pass
            self._ui_enabled = True
        except cv2.error as e:
            self._ui_mark_failed("namedWindow", e)

    def display_frame(self, frame, winname, gmcode, gmcode_show, frame_id):
        '''
        Resize and display the frame in a window, along with card position rectangles.
        Create/update a second window "ZoomedCards" that persists until next detection.
        '''
        frame_resized = cv2.resize(frame, (self.resize_width, self.resize_height))
        current_time = time.time()  # For flickering effect

        # Display gmcode on the top-left corner of the window
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1
        font_color = (255, 255, 255)  # White
        thickness = 2
        position = (10, 30)
        cv2.putText(
            frame_resized,
            f'{gmcode_show}_{frame_id}',
            position,
            font,
            font_scale,
            font_color,
            thickness,
            cv2.LINE_AA
        )

        zoomed_images = []  # We'll collect card ROIs we want to "zoom in" on

        for pos in self.config_poslist:
            # Calculate the rectangle coords based on the resized frame
            xmin = int(pos.xmin * self.resize_width / self.stream_videowidth)
            ymin = int(pos.ymin * self.resize_height / self.stream_videoheight)
            xmax = int(pos.xmax * self.resize_width / self.stream_videowidth)
            ymax = int(pos.ymax * self.resize_height / self.stream_videoheight)

            # Decide rectangle color
            if DataMgrInstance().getIsDispatch(gmcode, pos.index):
                # Green rectangle for dispatched cards
                color = (0, 255, 0)

                # Example: only show zoom for green “dispatched” cards
                card_roi = frame[pos.ymin:pos.ymax, pos.xmin:pos.xmax]
                zoomed_roi = cv2.resize(card_roi, (200, 300))
                zoomed_images.append((zoomed_roi, pos.index))

            elif DataMgrInstance().isincurCardList(gmcode, pos.index):
                # Flickering yellow for "currently detecting" cards
                flicker = int((current_time * 10) % 2)
                color = (0, 255, 255) if flicker else (255, 255, 255)

                # If you want to also zoom these, uncomment:
                # card_roi = frame[pos.ymin:pos.ymax, pos.xmin:pos.xmax]
                # zoomed_roi = cv2.resize(card_roi, (200, 300))
                # zoomed_images.append(zoomed_roi)
            else:
                # White rectangle for non-active cards
                color = (255, 255, 255)

            # Draw rectangle on the resized display
            cv2.rectangle(frame_resized, (xmin, ymin), (xmax, ymax), color, 2)

        # Show main window (UI may be temporarily unavailable on Windows; do not crash the loop)
        if self._ui_can_try():
            if not self._ui_enabled:
                self._ui_try_recover(winname)
            if self._ui_enabled:
                try:
                    cv2.imshow(winname, frame_resized)
                except cv2.error as e:
                    self._ui_mark_failed("imshow", e)

        # 20250407 show zoomed in cards
        # Build zoomed image in the order detected
        zoomed_images = []
        for idx in self.detection_order:
            roi = self.rois_by_index.get(idx)
            if roi is not None:
                zoomed_images.append(roi)

        # this is for display zoomed images(cards) 20250916 關掉, 順序是依據偵測到牌的順序而不是index順序，還未修復
        # if zoomed_images:
        #     composite = np.hstack(zoomed_images)
        #     cv2.imshow("ZoomedCards", composite)
        #     self.last_zoomed_display = composite
        # else:
        #     # If no new detection, show the old image or blank
        #     if self.last_zoomed_display is not None:
        #         cv2.imshow("ZoomedCards", self.last_zoomed_display)
        #     else:
        #         blank = np.zeros((300, 300, 3), dtype=np.uint8)
        #         cv2.imshow("ZoomedCards", blank)

    def rotate_frame(self, frame, angle):
        '''
        Rotate the given frame by the specified angle.
        '''
        # Get the dimensions of the frame
        (h, w) = frame.shape[:2]
        
        # Get the center of the frame (about which to rotate)
        center = (w // 2, h // 2)
        
        # Get the rotation matrix for the given angle
        rotation_matrix = cv2.getRotationMatrix2D(center, angle, 1.0)
        
        # 20240926 因crop tool傾斜角度的版本是不調整影片至視窗大小，這邊就不調了
        # # Compute the cosine and sine of the rotation matrix
        # abs_cos = abs(rotation_matrix[0, 0])
        # abs_sin = abs(rotation_matrix[0, 1])
        
        # # Compute the new bounding dimensions of the image
        # new_w = int((h * abs_sin) + (w * abs_cos))
        # new_h = int((h * abs_cos) + (w * abs_sin))
        
        # # Adjust the rotation matrix to take into account the translation
        # rotation_matrix[0, 2] += (new_w / 2) - center[0]
        # rotation_matrix[1, 2] += (new_h / 2) - center[1]
        
        # Perform the actual rotation and return the image
        # return cv2.warpAffine(frame, rotation_matrix, (new_w, new_h))
        return cv2.warpAffine(frame, rotation_matrix, (w, h))
    
    def warmup_capture(self, grabs: int = 8) -> None:
        """
        Best-effort: after the stream is opened (i.e., after start()),
        grab a few frames so the first post-START frame appears instantly.
        """
        try:
            cap = getattr(self, "cap", None)
            if cap is None or not hasattr(cap, "grab"):
                return
            for _ in range(max(1, grabs)):
                cap.grab()
            try:
                logger.info("WARMUP capture primed (%d grabs)" % grabs)
            except Exception:
                pass
        except Exception as e:
            try:
                logger.info("WARMUP capture skipped: %s" % str(e))
            except Exception:
                pass


# 20251017 helper Kill input buffering (most impact)

import threading


# --- Low-latency grabber for live streams (keeps only the newest frame) ---
class LatestFrameGrabber:
    """
    Keep preview/processing near-live by DROPPING old frames instead of slowing reads.

    Background thread publishes frames at ~publish_fps.
    In each publish cycle it:
      1) calls cap.grab() repeatedly (up to drain_grab_max, within a time budget)
         to drain buffered/queued frames quickly,
      2) calls cap.retrieve() once to materialize ONLY the newest grabbed frame,
      3) stores it as `latest` for the main loop.

    This prevents the FIFO-buffer drift you see when the main loop reads slower than the stream.
    """

    def __init__(self, src=None, cap=None, publish_fps: float = 60.0, drain_grab_max: int = 200, max_fps=None):
        import cv2, threading
        # Back-compat: older call sites passed max_fps; treat it as publish_fps.
        if (publish_fps is None or float(publish_fps or 0.0) <= 0.0) and max_fps is not None:
            publish_fps = max_fps

        # Accept an already-opened cap (recommended) or open from src
        if cap is None:
            self.cap = cv2.VideoCapture(src, cv2.CAP_FFMPEG)
        else:
            self.cap = cap

        self.lock = threading.Lock()
        self.latest = None
        self.latest_ts = 0.0
        self.latest_seq = 0

        self.alive = True

        try:
            self.publish_fps = float(publish_fps or 0.0)
        except Exception:
            self.publish_fps = 0.0

        try:
            self.drain_grab_max = int(drain_grab_max or 0)
        except Exception:
            self.drain_grab_max = 0

        # How much of each publish interval we spend draining buffered frames.
        # (The rest is for sleeping so publish cadence stays stable.)
        self.drain_budget_ratio = 0.90

        self.t = threading.Thread(target=self._loop, name="LatestFrameGrabber", daemon=True)
        self.t.start()

    def _grab(self) -> bool:
        """Best-effort cap.grab() across SafeCapture / raw VideoCapture."""
        try:
            if hasattr(self.cap, "grab"):
                return bool(self.cap.grab())
        except Exception:
            return False

        # fallback: read-and-discard
        try:
            ok, _ = self.cap.read()
            return bool(ok)
        except Exception:
            return False

    def _retrieve(self):
        """Best-effort cap.retrieve() across SafeCapture / raw VideoCapture."""
        try:
            if hasattr(self.cap, "retrieve"):
                return self.cap.retrieve()
        except Exception:
            return False, None

        # fallback: read
        try:
            return self.cap.read()
        except Exception:
            return False, None

    def _loop(self):
        import time
        # 0 or missing publish_fps means "as fast as possible" publishing.
        interval = (1.0 / self.publish_fps) if (self.publish_fps and self.publish_fps > 0.0) else 0.0

        # Start immediately
        while self.alive:
            t0 = time.perf_counter()

            # Drain buffered frames quickly, but don't exceed our time budget.
            drained = 0
            grabbed_any = False
            # Time budget: spend most of the interval draining. If interval==0, budget a small slice.
            budget = (interval * self.drain_budget_ratio) if interval > 0.0 else 0.01
            deadline = t0 + max(0.001, budget)

            # Drain loop: when we are behind (buffer has backlog), grab() returns quickly and
            # we will drop a LOT in this window, catching up to live.
            # When we are near-live, grab() blocks closer to frame interval, so we naturally stop.
            while self.alive and (time.perf_counter() < deadline):
                if self.drain_grab_max > 0 and drained >= self.drain_grab_max:
                    break
                ok = self._grab()
                if not ok:
                    break
                grabbed_any = True
                drained += 1

            if grabbed_any:
                ok, frame = self._retrieve()
                if ok and frame is not None:
                    with self.lock:
                        self.latest = frame
                        self.latest_ts = time.time()
                        self.latest_seq += 1

            # Keep publish cadence
            if interval > 0.0:
                elapsed = time.perf_counter() - t0
                sleep_s = interval - elapsed
                if sleep_s > 0:
                    time.sleep(min(sleep_s, interval))
            else:
                # avoid 100% CPU spin if someone set publish_fps=0
                time.sleep(0.001)

    def get(self):
        import numpy as np
        with self.lock:
            if self.latest is None:
                return None
            f = self.latest
        # return a copy to avoid accidental mutation across threads
        return f.copy() if hasattr(f, "copy") else np.array(f)

    def release(self):
        self.alive = False
        try:
            self.t.join(timeout=1.0)
        except Exception:
            pass
