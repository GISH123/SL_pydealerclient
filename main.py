# encoding=utf-8
import sys
import os
os.environ["SETUPTOOLS_USE_DISTUTILS"] = "stdlib"  # 強制 TF 用內建 distutils # fixing exe problem when building on 11.75 computer  
from twisted.internet import reactor
import pylogger as logger
# from singleInstance import singleInstanceStart
from config import cfg
from dealerclient import DealerClient
# from dev_mgr_client import DevMgrClient
from detector import Detector
from imagesaver import ImageSaver
from videomanager import VideoManager
# from version import VERSION
VERSION = '2.0.0'

if __name__ == '__main__':
    logger.info('detect v%s starting...' % VERSION)
    dector = Detector()
    reactor.suggestThreadPoolSize(8)

    dealer = DealerClient(cfg.dealer_host, cfg.dealer_port, cfg.dealer_id)
    # devmgr = DevMgrClient(cfg.devmgr_host, cfg.devmgr_port, cfg.vid)

    # 開這個imagesaver會讓整個detection process過慢無法跟上傳流sync，當freq低的時候甚至會無法辨識(太卡，太積累frames)，改為直接在VideoManager直接存圖
    # imageSaver = ImageSaver(cfg.save_folder)
    # imageSaver.start()
    imageSaver = None

    # 启动视频
    # 20241025 add parameter "save_predictions" to toggle if save to local disk or not(it will slow down the system)
    save_predictions = True # 存小圖
    # save_full_image = True # 存大圖
    # 20241127 save_full_image應為config裡的save_auto_upload
    save_full_image = int(cfg.save_auto_upload)
    videoMgr = VideoManager(cfg.gametype, cfg.stream, cfg.videowidth, cfg.videoheight, cfg.pos_list, dealer, dector, imageSaver, \
        cfg.onelabel, cfg.freq, cfg.tilt_angle, save_predictions, save_full_image, cfg.save_folder)
    videoMgr.start()

    reactor.run()
    sys.exit()
