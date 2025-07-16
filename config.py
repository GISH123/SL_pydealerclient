#encoding=utf-8

import xml.dom.minidom as xmldom
import pylogger as logger

TRY_CONNECT_DEALER_SECOND = 10
TRY_CONNECT_DEVMGR_SECOND = 10

'''
# 视频流
videoname = 'rtmp://192.168.23.34/max01/8-11v2'

# 模型路径
fastrcnn_model = './models/frozen_inference_graph.pb'
fastrcnn_config = './models/graph_faster_rcnn.pbtxt'
position_filename = './models/8-11v2.xml'
'''

class CardPositon(object):
    def __init__(self, index, name, xmin, ymin, xmax, ymax):
        self.index = int(index)
        self.name = name
        self.xmin = int(xmin)
        self.ymin = int(ymin)
        self.xmax = int(xmax)
        self.ymax = int(ymax)

    def width(self):
        return self.xmax - self.xmin

    def height(self):
        return self.ymax - self.ymin

class AppConfig(object):
    def __init__(self, config_filename, video_filename, score_thresholdname):
        self.config_filename = config_filename
        self.video_filename = video_filename
        self.score_thresholdname = score_thresholdname
        self.position_filename = ''
        self.DETECT_FRAME = 20 # 检测帧率
        self.devmgr_host = "10.96.8.128"
        self.devmgr_port = 1833

    # 初始化配置
    def load_config(self):

        bRet = self.read_base_config(self.config_filename)
        if not bRet:
            logger.error('load_config %s failed' %(self.config_filename))
            return False

        bRet = self.read_video_list(self.video_filename)
        if not bRet:
            logger.error('load_video_list %s failed' % (self.video_filename))
            return False

        bRet = self.read_position(self.position_filename)
        if not bRet:
            logger.error('read_position %s failed' % (self.position_filename))
            return False

        bRet = self.read_scoreshold(self.score_thresholdname)
        if not bRet:
            logger.error('read_scoreshold %s failed' % (self.read_scoreshold))
            return False

        return True

    # 读取基本配置
    def read_base_config(self, filename):
        xml_file = xmldom.parse(filename)
        root = xml_file.documentElement

        node_common = root.getElementsByTagName('common')[0]
        self.vid = node_common.getAttribute('vid')
        self.freq = int(node_common.getAttribute('freq'))
        self.onelabel = int(node_common.getAttribute('onelabel'))
        self.detecttimes = int(node_common.getAttribute('detecttimes'))
        self.saveimagescore = float(node_common.getAttribute('saveimagescore'))
        node_dealer = root.getElementsByTagName('dealer')[0]
        self.dealer_id = node_dealer.getAttribute('id')
        self.dealer_host = node_dealer.getAttribute('host')
        self.dealer_port = int(node_dealer.getAttribute('port'))
        node_save = root.getElementsByTagName('save')[0]
        self.save_folder = node_save.getAttribute('folder')
        self.save_auto_upload = node_save.getAttribute('autoUpload')
        # self.snapshot_stream = node_snapshot.getAttribute('stream')

        logger.info('read_base_config success, vid=%s, freq=%d, onelabel=%d, detecttimes=%d,saveimagescore=%.4f, id=%s, host=%s, port=%d' %
                    (self.vid, self.freq, self.onelabel, self.detecttimes, self.saveimagescore, self.dealer_id, self.dealer_host, self.dealer_port))
        logger.info("save_folder={},save_auto_upload={}".format(self.save_folder, self.save_auto_upload))
        return True

    # 读取视频列表
    def read_video_list(self, filename):
        xml_file = xmldom.parse(filename)
        root = xml_file.documentElement
        node_dnn = root.getElementsByTagName('dnn')[0]
        self.dnn_model = node_dnn.getAttribute('model')

        logger.info('read_video_list, dnn_model=%s' %(self.dnn_model))

        node_video_list = root.getElementsByTagName('videolist')[0]
        node_videos = node_video_list.getElementsByTagName('video')
        for node_video in node_videos:
            vid = node_video.getAttribute('vid')
            if vid == self.vid:
                self.gametype = node_video.getAttribute('gametype')
                self.stream = node_video.getAttribute('stream')
                #有可能会用采集卡采集视频，则stream的格式是0,1,2,3这种，得解析成int类型
                if len(self.stream) <= 2:
                    self.stream = int(self.stream)
                self.position_filename = node_video.getAttribute('position_file')
                self.videowidth = int(node_video.getAttribute('width'))
                self.videoheight = int(node_video.getAttribute('height'))
                # logger.info('read_video_list, gametype=%s, stream=%s, pos_file=%s, width=%d, height=%d' %
                #             (self.gametype, self.stream, self.position_filename, self.videowidth, self.videoheight))
                logger.info(f'read_video_list, gametype={self.gametype}, stream={self.stream}, \
                    pos_file={self.position_filename}, width={self.videowidth}, height={self.videoheight}')
                return True
        logger.error('read_video_list failed, filename=%s, vid=%s' %(filename, self.vid))
        return False

    # 读取定位的配置文件
    def read_position(self, filename):
        self.pos_list = []
        xml_file = xmldom.parse(filename)
        root = xml_file.documentElement

        # Check for tilt_angle in the annotation file
        size_node = root.getElementsByTagName('size')[0]
        tilt_angle_node = size_node.getElementsByTagName('tilt_angle')
        if tilt_angle_node:
            self.tilt_angle = int(tilt_angle_node[0].childNodes[0].nodeValue)
        else:
            self.tilt_angle = 0  # Set to default value if not present
        logger.info(f'Read tilt_angle: {self.tilt_angle}')

        nodes = root.getElementsByTagName('object')
        for node in nodes:
            card_name = node.getElementsByTagName('name')[0].childNodes[0].nodeValue
            str = card_name.split('_', 1)
            index = str[1]
            bnd_box = node.getElementsByTagName('bndbox')
            xmin = 0
            ymin = 0
            xmax = 0
            ymax = 0
            for box in bnd_box:
                xmin = box.getElementsByTagName('xmin')[0].childNodes[0].nodeValue
                ymin = box.getElementsByTagName('ymin')[0].childNodes[0].nodeValue
                xmax = box.getElementsByTagName('xmax')[0].childNodes[0].nodeValue
                ymax = box.getElementsByTagName('ymax')[0].childNodes[0].nodeValue

            pos = CardPositon(index, card_name, xmin, ymin, xmax, ymax)
            self.pos_list.append(pos)

        logger.info('read_position success, filename=%s, gametype=%s, vid=%s, count=%d' %
                    (filename, self.gametype, self.vid, len(self.pos_list)))
        return True

    # 读分数列表
    def read_scoreshold(self, filename):
        self.scoremap = {}
        xml_file = xmldom.parse(filename)
        root = xml_file.documentElement
        nodes = root.getElementsByTagName('puke')
        for node in nodes:
            index = int(node.getElementsByTagName('index')[0].childNodes[0].nodeValue)
            score = float(node.getElementsByTagName('threshold')[0].childNodes[0].nodeValue)
            self.scoremap[index] = score
        logger.info('read_position success, filename=%s,count=%d' %
                    (filename, len(self.scoremap)))
        return True
cfg = AppConfig('./config.xml', './models/videolist.xml','./models/score-threshold.xml')
cfg.load_config()