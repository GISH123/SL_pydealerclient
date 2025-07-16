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

class VideoManager(object):
    def __init__(self, gametype, stream, videowidth, videoheight, poslist, dealer, detector, \
        imageSaver, onelabel, freq, tilt_angle, save_predictions, save_full_image, savedir,\
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
        while not self.stopRun:
            # Play video stream and process frames
            ifopenVideo = self.playVideo(self.stream, self.config_poslist, self.detector)
            if self.isExit or not ifopenVideo:
                self.cleanup(playVideoCount)
                break

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

    def playVideo(self, videoname, poslist, detector):
        '''
        Opens the video stream, reads frames, and processes them. Incorporates pausing/resuming functionality.
        '''
        logger.info(f'Starting video stream: {videoname}')
        cap = cv2.VideoCapture(videoname)

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

        while True:
            if not self.paused:
                ret, frame = cap.read()
                frame_id += 1
                is_card_detected = False

                if not ret or frame is None:
                    logger.info('Failed to read frame from video')
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
            key = cv2.waitKey(1)
            if key & 0xFF == ord('q') or cv2.getWindowProperty(winname, cv2.WND_PROP_AUTOSIZE) < 1: 
                self.stopRun = True
                logger.error('Exiting...')
                cv2.destroyAllWindows()
                reactor.callFromThread(reactor.stop)
                self.isExit = True
                break

        if cap.isOpened():
            cap.release()

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

    def process_frame(self, frame, poslist, gmcode, detector, isDetect, gmcode_show, frame_id):
        '''
        Process each frame to detect card values and save predictions.
        '''
        # 1) Compare current gmcode to self.last_gmcode
        if gmcode != self.last_gmcode:
            # This means a new game code just arrived
            logger.info(f"New game code detected: {gmcode}. Clearing old data.")
            self.detection_order.clear()
            self.rois_by_index.clear()
            self.last_zoomed_display = None

            self.last_gmcode = gmcode  # update so we won't clear again until next game code changes

        # 2) Proceed with your normal detection logic
        is_card_detected = False # 當卡牌有預測出來時(不論只預測出卡牌點數，還是卡牌花色，還是兩個都有)，save_all變為True
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
                predict_image = cv2.cvtColor(predict_image, cv2.COLOR_BGR2RGB)
                predict_suits, predict_cardval, desc, score, classid = self.predict_card(detector, predict_image, gmcode, pos, frame_id)

                if desc:
                    # 儲存預測結果準備回傳、儲存圖片至本機供debug
                    logger.info(f'send {gmcode_show} prediction with send_prediction, desc = {desc}, predict_classid = {classid}')
                    self.send_prediction(gmcode_show, pos, predict_image, desc, score, predict_suits, predict_cardval, classid)
                    # logger.info(f'saving prediction with save_prediction done, desc = {desc}')
                    is_card_detected = True
                else:
                    # logger.info(f'do not save_prediction, desc : {desc}') # 20240924 comment out to clean terminal
                    pass # 20240924 pass for previous comment out to clean terminal
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
            return detector.do_predict_one_label(image, gmcode, pos.index, False, frame_id)
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
            # self.imageSaver.save(gmcode, pos.index, desc, save_score, predict_image)
            # 拔imageSaver.save的code到這
            # strgmcode = self._toString(str(gmcode, encoding='utf-8'))
            strgmcode = gmcode_show
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

            logger.info('write prediction image, image file path =%s' % (filepath))

            #20241211 因前面有bgr2rgb 現在cv2要轉回來 才能存下正確顏色的圖片
            predict_image_bgr = cv2.cvtColor(predict_image, cv2.COLOR_RGB2BGR)
            cv2.imwrite(filepath, predict_image_bgr)
            
            # ScanRMgrInstance().saveDataToCsv(gmcode, pos.index, cardVal, desc, score) # 原本imageSaver.save裡面的.write有這段，現在我先取消
            # dealerclient onSaveFinalResult會存 不知道這裡要存要幹嘛

        # 20250407 add zoomed in cards
        # Let's create a zoomed ROI
        zoomed_roi = cv2.resize(predict_image_bgr, (200, 300))
        
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
        logger.info('write full image, image file path =%s' % (filepath))

        # 20241127 存大圖也將牌局名稱印在左上角，對齊detector秀的frame
        # Display gmcode on the top-left corner of the window
        font = cv2.FONT_HERSHEY_SIMPLEX
        font_scale = 1
        font_color = (255, 255, 255)  # 白
        thickness = 2
        position = (10, 30)  # Coordinates for the top-left corner
        cv2.putText(frame, f'{gmcode_show}', position, font, font_scale, font_color, thickness, cv2.LINE_AA)
        cv2.imwrite(filepath, frame)

        return filename, filepath

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

        # Show main window
        cv2.imshow(winname, frame_resized)

        # 20250407 show zoomed in cards
        # Build zoomed image in the order detected
        zoomed_images = []
        for idx in self.detection_order:
            roi = self.rois_by_index.get(idx)
            if roi is not None:
                zoomed_images.append(roi)

        if zoomed_images:
            composite = np.hstack(zoomed_images)
            cv2.imshow("ZoomedCards", composite)
            self.last_zoomed_display = composite
        else:
            # If no new detection, show the old image or blank
            if self.last_zoomed_display is not None:
                cv2.imshow("ZoomedCards", self.last_zoomed_display)
            else:
                blank = np.zeros((300, 300, 3), dtype=np.uint8)
                cv2.imshow("ZoomedCards", blank)

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