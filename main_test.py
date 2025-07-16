# encoding=utf-8
import sys
import os
from twisted.internet import reactor

if __name__ == '__main__':
    reactor.suggestThreadPoolSize(8)

    # 20241024 capture same stream for reference video speed
    def ref_video_stream():
        import cv2
        import numpy as np
        cap = cv2.VideoCapture("rtmp://pull.video-g18.com:1935/mt01/h-4")
        winname = 'ref_video_stream'
        cv2.namedWindow(winname)
        while True:
            ret, frame = cap.read()
            if not ret or frame is None:
                logger.info('Failed to read frame from video')
                continue

            # Exit condition
            key = cv2.waitKey(1)
            if key & 0xFF == ord('q') or cv2.getWindowProperty(winname, cv2.WND_PROP_AUTOSIZE) < 1: 
                cv2.destroyAllWindows()
                break

            # cv2.waitKey(1)
            cv2.imshow(winname, frame)
    reactor.callInThread(ref_video_stream)

    reactor.run()
    sys.exit()
