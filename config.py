#encoding=utf-8

import xml.dom.minidom as xmldom
import pylogger as logger
from model_class_mapping import (
    default_mapping_mode_for_gametype,
    normalize_mapping_mode,
)

TRY_CONNECT_DEALER_SECOND = 10
TRY_CONNECT_DEVMGR_SECOND = 10

'''
# 瑙嗛娴?
videoname = 'rtmp://STREAM_HOST/app/stream'

# 妯″瀷璺緞
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
        self.DETECT_FRAME = 20 # 妫€娴嬪抚鐜?
        self.devmgr_host = "127.0.0.1"
        self.devmgr_port = 1833

    # 鍒濆鍖栭厤缃?
    def load_config(self):

        bRet = self.read_base_config(self.config_filename)
        if not bRet:
            logger.error('load_config %s failed' %(self.config_filename))
            return False

        bRet = self.read_video_list(self.video_filename)
        if not bRet:
            logger.error('load_video_list %s failed' % (self.video_filename))
            return False

        # Resolve mapping only after gametype is known.
        # BAC/DT default: current 0..52,99 folders trained with legacy string sort.
        # lattest default: preserve existing 3-class identity mapping.
        default_mapping_mode = default_mapping_mode_for_gametype(self.gametype)
        self.model_class_mapping_mode = normalize_mapping_mode(
            getattr(self, '_model_class_mapping_mode_config', None),
            default_mapping_mode,
        )
        logger.info('model_class_mapping_mode=%s' % self.model_class_mapping_mode)

        bRet = self.read_position(self.position_filename)
        if not bRet:
            logger.error('read_position %s failed' % (self.position_filename))
            return False

        bRet = self.read_scoreshold(self.score_thresholdname)
        if not bRet:
            logger.error('read_scoreshold %s failed' % (self.read_scoreshold))
            return False

        return True

    # 璇诲彇鍩烘湰閰嶇疆
    def read_base_config(self, filename):
        def _as_bool(s, default=True):
            if s is None:
                return default
            s = str(s).strip().lower()
            return s in ("1", "true", "yes", "on")

        def _get_text(root_node, tag: str):
            nodes = root_node.getElementsByTagName(tag)
            if not nodes:
                return None
            if not nodes[0].childNodes:
                return None
            return ''.join(
                n.nodeValue for n in nodes[0].childNodes
                if n.nodeType == n.TEXT_NODE
            )

        xml_file = xmldom.parse(filename)
        root = xml_file.documentElement

        # <common ... />
        node_common = root.getElementsByTagName('common')[0]
        self.vid = node_common.getAttribute('vid')
        self.freq = int(node_common.getAttribute('freq'))
        self.onelabel = int(node_common.getAttribute('onelabel'))
        self.detecttimes = int(node_common.getAttribute('detecttimes'))
        self.saveimagescore = float(node_common.getAttribute('saveimagescore'))

        # Optional model output-index mapping mode. Resolve after video list
        # is loaded because the safe default depends on gametype.
        self._model_class_mapping_mode_config = _get_text(
            root, 'model_class_mapping_mode'
        )

        # <dealer ... />
        node_dealer = root.getElementsByTagName('dealer')[0]
        self.dealer_id = node_dealer.getAttribute('id')
        self.dealer_host = node_dealer.getAttribute('host')
        self.dealer_port = int(node_dealer.getAttribute('port'))

        # Optional: <ftp ... />
        ftp_nodes = root.getElementsByTagName('ftp')
        if ftp_nodes:
            node_ftp = ftp_nodes[0]
            self.ftp_host = node_ftp.getAttribute('host')
            self.ftp_port = int(node_ftp.getAttribute('port') or 21)
            self.ftp_user = node_ftp.getAttribute('user')
            self.ftp_password = node_ftp.getAttribute('password')

        # <save folder="..." savebigImage="1" />
        node_save = root.getElementsByTagName('save')[0]
        self.save_folder = node_save.getAttribute('folder') or "./big_images"

        # Rename: save_auto_upload -> save_big_image  (with backward compatibility)
        big_attr = node_save.getAttribute('savebigImage')
        if (big_attr is None or big_attr == "") and node_save.hasAttribute('autoUpload'):
            # fallback to old name if someone still uses it
            big_attr = node_save.getAttribute('autoUpload')
        # store as "1"/"0" string (main.py casts to int)
        self.save_big_image = big_attr if big_attr not in (None, "") else "1"
        # Back-compat alias so any leftover code won't break
        self.save_auto_upload = self.save_big_image

        # <save_small_image>1</save_small_image>   (new)
        small_nodes = root.getElementsByTagName('save_small_image')
        if small_nodes and small_nodes[0].childNodes:
            txt = ''.join(n.nodeValue for n in small_nodes[0].childNodes
                          if n.nodeType == n.TEXT_NODE)
            self.save_small_image = "1" if _as_bool(txt, True) else "0"
        else:
            # default ON to preserve current behavior
            self.save_small_image = "1"

        # <video_loop>1</video_loop> (existing)
        loop_nodes = root.getElementsByTagName('video_loop')
        if loop_nodes and loop_nodes[0].childNodes:
            txt = ''.join(n.nodeValue for n in loop_nodes[0].childNodes
                          if n.nodeType == n.TEXT_NODE)
            self.video_loop = _as_bool(txt, True)
        else:
            self.video_loop = True  # default

        # <max_grab_fps>60</max_grab_fps> (new, optional)
        # 0 or missing = unlimited (preserve legacy behavior)
        try:
            txt = _get_text(root, 'max_grab_fps')
            if txt is None:
                self.max_grab_fps = 0.0
            else:
                self.max_grab_fps = float(str(txt).strip() or 0.0)
        except Exception:
            self.max_grab_fps = 0.0

        # <cap_buffersize>2</cap_buffersize> (new, optional)
        # Applied as CAP_PROP_BUFFERSIZE hint where supported.
        try:
            txt = _get_text(root, 'cap_buffersize')
            if txt is None:
                self.cap_buffersize = None
            else:
                v = float(str(txt).strip())
                self.cap_buffersize = v
        except Exception:
            self.cap_buffersize = None

        # <stream_publish_fps>60</stream_publish_fps> (new, optional)
        # For NETWORK streams: how often we *publish* a frame to UI/predict loop.
        # This does NOT throttle the capture draining speed.
        try:
            txt = _get_text(root, 'stream_publish_fps')
            if txt is None:
                self.stream_publish_fps = 60.0
            else:
                self.stream_publish_fps = float(str(txt).strip() or 60.0)
        except Exception:
            self.stream_publish_fps = 60.0

        # <stream_drain_grab_max>200</stream_drain_grab_max> (new, optional)
        # For NETWORK streams: max grab() attempts per publish cycle to drop backlog.
        try:
            txt = _get_text(root, 'stream_drain_grab_max')
            if txt is None:
                self.stream_drain_grab_max = 200
            else:
                self.stream_drain_grab_max = int(float(str(txt).strip() or 200))
        except Exception:
            self.stream_drain_grab_max = 200



        # Logs
        logger.info(
            f"read_base_config: vid={self.vid}, freq={self.freq}, onelabel={self.onelabel}, "
            f"detecttimes={self.detecttimes}, saveimagescore={self.saveimagescore}, "
            f"dealer=({self.dealer_id}@{self.dealer_host}:{self.dealer_port})"
        )
        logger.info(
            f"save_folder={self.save_folder}, save_big_image={self.save_big_image}, "
            f"save_small_image={self.save_small_image}, video_loop={self.video_loop}"
        )
        try:
            logger.info(
                f"max_grab_fps={getattr(self, 'max_grab_fps', 0.0)}, "
                f"cap_buffersize={getattr(self, 'cap_buffersize', None)}, "
                f"stream_publish_fps={getattr(self, 'stream_publish_fps', 60.0)}, "
                f"stream_drain_grab_max={getattr(self, 'stream_drain_grab_max', 200)}"
            )
        except Exception:
            pass
        return True

    # 璇诲彇瑙嗛鍒楄〃
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
                #鏈夊彲鑳戒細鐢ㄩ噰闆嗗崱閲囬泦瑙嗛锛屽垯stream鐨勬牸寮忔槸0,1,2,3杩欑锛屽緱瑙ｆ瀽鎴恑nt绫诲瀷
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

    # 璇诲彇瀹氫綅鐨勯厤缃枃浠?
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

    # 璇诲垎鏁板垪琛?
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
