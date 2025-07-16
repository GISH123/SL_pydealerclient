# encoding=utf-8

import os
import datetime as d
import pylogger as logger
import cv2
from twisted.internet import reactor
import queue
import threading
import subprocess
from config import cfg

class ImageFileNode(object):
    """
    Represents an image file node with its associated metadata.
    """
    def __init__(self, filename, filepath, image, gmcode):
        self.filename = filename
        self.filepath = filepath
        self.image = image
        self.gmcode = gmcode

class ImageSaver(object):
    """
    Manages the saving of images to disk and handles a snapshot queue for special images.
    Images can be saved directly or through a background thread using a queue.
    """
    def __init__(self, dir):
        # Maximum number of images that can be queued for saving
        self.maxImageSaveQueueSize = 50

        # Audit directory for storing snapshot images with timestamps
        # self.auditDir = "./audit_images"
        self.auditDir = dir

        # Control flag for stopping the running thread
        self.stopRun = False
        
        # Queue to store image nodes to be saved
        self.imageSaveQueue = queue.Queue(self.maxImageSaveQueueSize)
        
        # Queue for managing snapshot images
        self.snapshotQueue = queue.Queue(1)
        self.snapshotFlag = False

        # Create directories if they do not exist
        # if not os.path.exists(dir): # 20240919 不用dir，用auditDir
        #     os.mkdir(dir)
        if not os.path.exists(self.auditDir):
            os.mkdir(self.auditDir)

        # Create a subdirectory based on the current date
        date = self.curDate()
        self.curDir = os.path.join(self.auditDir, date)
        if not os.path.exists(self.curDir):
            os.mkdir(self.curDir)

    def start(self):
        """
        Starts the background thread to save images.
        """
        reactor.callInThread(self.run)

    def stop(self):
        """
        Stops the background thread and terminates the reactor.
        """
        self.stopRun = True
        reactor.callFromThread(reactor.stop)

    def run(self):
        """
        The background thread responsible for saving images from the queue.
        """
        self.stopRun = False
        while True:
            if self.stopRun:
                return

            # Process the image save queue
            if not self.imageSaveQueue.empty():
                node = self.imageSaveQueue.get_nowait()
                if node.image is not None:
                    cv2.imwrite(node.filepath, node.image)

            # # Process snapshot saving when the flag is set
            # if self.snapshotFlag and not self.snapshotQueue.empty():
            #     node = self.snapshotQueue.get_nowait()
            #     if node.image is not None:
            #         cv2.imwrite(node.filepath, node.image)

            #         # Auto-upload logic
            #         if os.path.exists("ImageUploader.exe") and cfg.save_auto_upload == "1":
            #             cmd = f"ImageUploader.exe {node.filename} {node.filepath} {node.gmcode}"
            #             subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
            #             logger.info(cmd)
            #         else:
            #             # Overlay text using FFmpeg if auto-upload is disabled
            #             cmd = f'''ffmpeg.exe -v error -i {node.filepath} -vf "drawtext=fontfile=simhei.ttf:fontsize=40:text='局号 {node.gmcode}':x=w-tw-20:y=20:fontsize=40:fontcolor=yellow:shadowy=2" -y {node.filepath}'''
            #             subprocess.Popen(cmd, stdout=subprocess.PIPE, shell=True)
            #             logger.info(cmd)

            #     # Reset the snapshot flag
            #     self.snapshotFlag = False

            # Exit the thread if 'q' is pressed
            if cv2.waitKey(1) & 0xFF == ord('q'):
                self.stopRun = True
                logger.error('exit.')
                reactor.callFromThread(reactor.stop)
                break            

    def curDate(self):
        """
        Returns the current date as a string in the format YYYY-MM-DD.
        """
        return d.datetime.now().strftime('%Y-%m-%d')

    def write(self, strgmcode, fmt_str, image):
        """
        Writes the image to the file system. Saves either in the general directory or the audit directory.
        """

        # Update the current directory if the date has changed
        newDir = os.path.join(self.auditDir, self.curDate())
        if newDir != self.curDir:
            self.curDir = newDir
            if not os.path.exists(newDir):
                os.mkdir(newDir)

        # 製造gmcode的dir
        gmcode_dir = os.path.join(newDir, strgmcode)
        if not os.path.exists(gmcode_dir):
            os.mkdir(gmcode_dir)

        # Generate filename based timestamped
        filename = d.datetime.now().strftime('%Y%m%d%H%M_') + fmt_str + '.jpg' 
        # 20240919 .strftime('%Y%m%d%H%M%S%f_') 改為 .strftime('%Y%m%d%H%M_')，以分鐘為單位保存圖片，不然同張卡牌惠存一堆圖片
        filepath = os.path.join(gmcode_dir, filename)

        logger.info('write, image file path =%s' % (filepath))

        # Add the image node to the save queue
        node = ImageFileNode(filename, filepath, image, fmt_str)
        if self.imageSaveQueue.qsize() < self.maxImageSaveQueueSize:
            self.imageSaveQueue.put_nowait(node)

        return filename, filepath

    def _toString(self, data):
        """
        Converts byte data to a string, removing null characters.
        """
        return ''.join([c for c in data if c != '\000'])

    def save(self, gmcode, index, desc, score, image):
        """
        Saves an image with metadata and returns the filename and filepath.
        """
        strgmcode = self._toString(str(gmcode, encoding='utf-8'))

        fmt_str = '%s_%d_%s(%.4f)' % (strgmcode, index, desc, score)

        filename, filepath = self.write(strgmcode, fmt_str, image)
        return filename, filepath

    # def saveDirectly(self, gmcode, index, desc, score, image, save_all):
    #     """
    #     Directly saves an image without using the queue and returns the filename and filepath.
    #     """
    #     strgmcode = self._toString(str(gmcode, encoding='utf-8'))

    #     if save_all:
    #         fmt_str = '%s' % strgmcode
    #     else:
    #         fmt_str = '%s_%d_%s(%.4f)' % (strgmcode, index, desc, score)

    #     newDir = os.path.join(self.auditDir, self.curDate())
    #     if newDir != self.curDir:
    #         self.curDir = newDir
    #         if not os.path.exists(newDir):
    #             os.mkdir(newDir)

    #     if save_all:
    #         filename = fmt_str + '.jpg'
    #     else:
    #         filename = d.datetime.now().strftime('%Y%m%d%H%M%S%f_') + fmt_str + '.jpg'
        
    #     filepath = os.path.join(newDir, filename)
    #     logger.info('saveDirectly, image file path =%s' % (filepath))

    #     cv2.imwrite(filepath, image)
    #     return filename, filepath

    def putSnapshotQueue(self, gmcode, index, desc, score, image):
        """
        Puts an image in the snapshot queue with metadata and returns the filename and filepath.
        """
        strgmcode = self._toString(str(gmcode, encoding='utf-8'))

        fmt_str = '%s' % strgmcode

        newDir = os.path.join(self.auditDir, self.curDate())
        if newDir != self.curDir:
            self.curDir = newDir
            if not os.path.exists(newDir):
                os.mkdir(newDir)

        # 製造gmcode的dir
        gmcode_dir = os.path.join(newDir, strgmcode)
        if not os.path.exists(gmcode_dir):
            os.mkdir(gmcode_dir)

        filename = d.datetime.now().strftime('%Y%m%d%H%M%S%f_') + fmt_str + '.jpg'
        filepath = os.path.join(gmcode_dir, filename)

        if not self.snapshotQueue.empty():
            self.snapshotQueue.get_nowait()

        node = ImageFileNode(filename, filepath, image, fmt_str)
        self.snapshotQueue.put_nowait(node)
        return filename, filepath

    def setSnapshotFlag(self):
        """
        Enables the flag to process snapshot saving in the background.
        """
        self.snapshotFlag = True