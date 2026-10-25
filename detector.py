# encoding=utf-8

from config import cfg
import pylogger as logger
import tensorflow as tf
# import tensorflow.compat.v1 as tf # tf2 to use tf1 code
# tf.disable_v2_behavior()
import os
import predict
import time
import cardinfo
import numpy as np
import cv2
from prepare_data import load_and_preprocess_image
from prepare_data_jk import load_and_preprocess_image as load_and_preprocess_image_jk
from model_class_mapping import (
    default_mapping_mode_for_gametype,
    model_idx_to_predict_classid,
    read_mapping_mode_from_config,
)

class Detector(object):
    def __init__(self):
        logger.info('Detector constructed...')
        self.model_class_mapping_mode = cfg.model_class_mapping_mode
        logger.info(f'Model class mapping mode: {self.model_class_mapping_mode}')
        gpus = tf.config.list_physical_devices('GPU')
        logger.info(f"Detector tf list_physical_devices: {gpus}")
        gpu = next(iter(tf.config.list_physical_devices('GPU')), None)
        if gpu is None:
            self.gpu_name = "No GPU detected"
        else:
            # TF 2.x: returns e.g. "NVIDIA GeForce RTX 4080"
            details = tf.config.experimental.get_device_details(gpu)
            self.gpu_name = details.get('device_name', 'Unknown GPU')
        model_path = os.path.join(os.getcwd(), cfg.dnn_model)

        # Print model path for debugging
        logger.info(f"Loading model from: {model_path}")

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model path does not exist: {model_path}")

        # 20240827 load and use infer model using Basic_CNNs_TensorFlow2_c54_poker training tool codes
        self.model = tf.saved_model.load(model_path)

        # tf1 codes (kept for reference)
        # detection_graph = tf.Graph()
        # with detection_graph.as_default():
        #     od_graph_def = tf.GraphDef()
        #     with tf.gfile.GFile(model_path, 'rb') as fid:
        #         logger.info("loading model start...")
        #         serialized_graph = fid.read()
        #         od_graph_def.ParseFromString(serialized_graph)
        #         tf.import_graph_def(od_graph_def, name='')
        #         logger.info('loading model success...')
        #     self.sess = tf.Session(graph=detection_graph)
        # self.image_tensor = detection_graph.get_tensor_by_name('image_tensor:0')
        # self.detection_boxes = detection_graph.get_tensor_by_name('detection_boxes:0')
        # self.detection_scores = detection_graph.get_tensor_by_name('detection_scores:0')
        # self.detection_classes = detection_graph.get_tensor_by_name('detection_classes:0')
        # self.num_detections = detection_graph.get_tensor_by_name('num_detections:0')

    def do_predict_one_label(self, image, gmcode, index, rotation, frame_id):
        '''
        单标签预测，为与多分类统一接口，将预测的结果分为花色和牌值进行返回
        :param image_expanded:
        :param gmcode:
        :return:
        '''
        # make cv image into bytes
        # predict_image: NumPy HxWx3 (RGB)
        rgb_uint8 = image if image.dtype == np.uint8 else \
                    np.clip(image, 0, 255).astype(np.uint8)
        image = tf.io.encode_jpeg(tf.convert_to_tensor(rgb_uint8), format='rgb', quality=95)
        image_raw_mat = load_and_preprocess_image(image, False)
        image_tensor = tf.expand_dims(image_raw_mat, axis=0)

        suites = predict.PredictResult()
        cardval = predict.PredictResult()

        suitesjudge = predict.PredictResult()
        cardvaljudge = predict.PredictResult()

        save_descjudge = ''
        save_scorejudge = 0.0

        # ── model inference timing (only the forward pass) ─────────────────
        start_time = lambda: int(round(time.time() * 1000))
        time_start_time = start_time()
        pred = self.model(image_tensor, training=False)
        end_time = lambda: int(round(time.time() * 1000))
        time_end_time = end_time()

        # ───────────────────────────────────────────────────────────────────

        confidence = np.array(tf.math.abs(pred).numpy()).max()
        model_idx = int(tf.math.argmax(pred, axis=-1).numpy()[0])
        classid = model_idx_to_predict_classid(model_idx, self.model_class_mapping_mode)

        # Log both namespaces so model output and pydealer predict_classid are auditable.
        logger.info(f'[INFER] {self.gpu_name} gmcode={gmcode} index={index} frame_id={frame_id} '
                    f'model_idx={model_idx} predict_classid={classid} mapping={self.model_class_mapping_mode} '
                    f'conf={float(confidence):.4f}, do_predict_one_label prediction finished, span={time_end_time - time_start_time})')
        

        score = pred[0][model_idx]
        box = [0,1,2,3]

        # 20240827 rotation path is unused in current pipeline (rotation=False)
        if rotation:
            scores_list_rotation = scores_rotation[0].tolist()
            rotation_wanted_index = scores_list_rotation.index(max(scores_list_rotation))
            score_rotation = scores_rotation[0][rotation_wanted_index]
            classid_rotation = classes_rotation[0][wanted_index]
            box_rotation = boxes_rotation[0][rotation_wanted_index]

        # Map class to suit/value
        if rotation:
            if classid_rotation == classid:
                if score >= cfg.scoremap[classid] and score_rotation >= cfg.scoremap[classid_rotation]:
                    if classid >= 1 and classid <= 13:
                        if score >= cfg.scoremap[classid]:
                            suites.setvalue(cardinfo.SUITES_CLUB, score, box)
                            cardval.setvalue(classid, score, box)
                    if classid >= 14 and classid <= 26:
                        if score >= cfg.scoremap[classid]:
                            suites.setvalue(cardinfo.SUITES_DIAMOND, score, box)
                            cardval.setvalue(classid - 13, score, box)
                    if classid >= 27 and classid <= 39:
                        if score >= cfg.scoremap[classid]:
                            suites.setvalue(cardinfo.SUITES_HAEART, score, box)
                            cardval.setvalue(classid - 26, score, box)
                    if classid >= 40 and classid <= 52:
                        if score >= cfg.scoremap[classid]:
                            suites.setvalue(cardinfo.SUITES_SPADE, score, box)
                            cardval.setvalue(classid - 39, score, box)
        else:
            if classid >= 1 and classid <= 13:
                if score >= cfg.scoremap[classid]:
                    suites.setvalue(cardinfo.SUITES_CLUB, score, box)
                    cardval.setvalue(classid, score, box)
            elif classid >= 14 and classid <= 26:
                if score >= cfg.scoremap[classid]:
                    suites.setvalue(cardinfo.SUITES_DIAMOND, score, box)
                    cardval.setvalue(classid - 13, score, box)
            elif classid >= 27 and classid <= 39:
                if score >= cfg.scoremap[classid]:
                    suites.setvalue(cardinfo.SUITES_HAEART, score, box)
                    cardval.setvalue(classid - 26, score, box)
            elif classid >= 40 and classid <= 52:
                if score >= cfg.scoremap[classid]:
                    suites.setvalue(cardinfo.SUITES_SPADE, score, box)
                    cardval.setvalue(classid - 39, score, box)
            else:
                pass

        if suites.init and not cardval.init:
            save_descjudge = suites.to_str()
            save_scorejudge = suites.score
            logger.info('suite:%s classid=%d, score:%.4f' %(suites.to_str(), suites.classid, suites.score))
        elif not suites.init and cardval.init:
            save_descjudge = cardval.to_str()
            save_scorejudge = cardval.score
            logger.info('cardval:%s classid=%d, score:%.4f' %(cardval.to_str(), cardval.classid, cardval.score))
        elif suites.init and cardval.init:
            save_descjudge = "%s_%s" % (suites.to_str(), cardval.to_str())
            save_scorejudge = float((suites.score + cardval.score) / 2.0)
            logger.info('card:%s_%s, suites_classid=%d, suites_score:%.4f,cardval_classid=%d, cardval_score:%.4f '
                        %(suites.to_str(), cardval.to_str(),suites.classid, suites.score,cardval.classid, cardval.score))
        else:
            pass

        return suites, cardval, save_descjudge, save_scorejudge, classid

    def do_predict_one_label_jk_preprocess(self, image, gmcode, index, rotation, frame_id):
        '''
        单标签预测，为与多分类统一接口，将预测的结果分为花色和牌值进行返回
        :param image_expanded:
        :param gmcode:
        :return:
        '''
        def _jk_preprocess_from_numpy(image_np, assume_bgr):
            """
            JK Step4_3 preprocessing:
            NumPy RGB -> JPEG bytes -> load_and_preprocess_image_jk -> [1,H,W,C] float32
            """
            import numpy as np
            import tensorflow as tf
            import cv2

            # Ensure 8-bit and RGB order (JK trained on RGB)
            if assume_bgr and image_np.ndim == 3 and image_np.shape[-1] == 3:
                image_np = cv2.cvtColor(image_np, cv2.COLOR_BGR2RGB)
            if image_np.dtype != np.uint8:
                image_np = np.clip(image_np, 0, 255).astype(np.uint8)

            # Encode to JPEG so we exactly mirror JK's pipeline (he decodes bytes)
            image_bytes = tf.io.encode_jpeg(tf.convert_to_tensor(image_np), format='rgb', quality=95)

            # Same function JK used in Step4_3
            image_raw_mat = load_and_preprocess_image_jk(image_bytes, False)

            # Add batch dimension
            return tf.expand_dims(image_raw_mat, axis=0)

        # --- JK Step4_3-style preprocessing (matches training/eval pipeline) ---
        image_tensor = _jk_preprocess_from_numpy(image, assume_bgr=False)

        suites = predict.PredictResult()
        cardval = predict.PredictResult()

        suitesjudge = predict.PredictResult()
        cardvaljudge = predict.PredictResult()

        save_descjudge = ''
        save_scorejudge = 0.0

        # ── model inference timing (only the forward pass) ─────────────────
        start_time = lambda: int(round(time.time() * 1000))
        time_start_time = start_time()
        pred = self.model(image_tensor, training=False)
        end_time = lambda: int(round(time.time() * 1000))
        time_end_time = end_time()

        # ───────────────────────────────────────────────────────────────────

        confidence = np.array(tf.math.abs(pred).numpy()).max()
        model_idx = int(tf.math.argmax(pred, axis=-1).numpy()[0])
        classid = model_idx_to_predict_classid(model_idx, self.model_class_mapping_mode)

        # Log both namespaces so model output and pydealer predict_classid are auditable.
        logger.info(f'[INFER] {self.gpu_name} gmcode={gmcode} index={index} frame_id={frame_id} '
                    f'model_idx={model_idx} predict_classid={classid} mapping={self.model_class_mapping_mode} '
                    f'conf={float(confidence):.4f}, do_predict_one_label prediction finished, model_predict_span={time_end_time - time_start_time}')

        score = pred[0][model_idx]
        box = [0,1,2,3]

        # 20240827 rotation path is unused in current pipeline (rotation=False)
        if rotation:
            scores_list_rotation = scores_rotation[0].tolist()
            rotation_wanted_index = scores_list_rotation.index(max(scores_list_rotation))
            score_rotation = scores_rotation[0][rotation_wanted_index]
            classid_rotation = classes_rotation[0][wanted_index]
            box_rotation = boxes_rotation[0][rotation_wanted_index]

        if rotation:
            if classid_rotation == classid:
                if score >= cfg.scoremap[classid] and score_rotation >= cfg.scoremap[classid_rotation]:
                    if classid >= 1 and classid <= 13:
                        if score >= cfg.scoremap[classid]:
                            suites.setvalue(cardinfo.SUITES_CLUB, score, box)
                            cardval.setvalue(classid, score, box)
                    if classid >= 14 and classid <= 26:
                        if score >= cfg.scoremap[classid]:
                            suites.setvalue(cardinfo.SUITES_DIAMOND, score, box)
                            cardval.setvalue(classid - 13, score, box)
                    if classid >= 27 and classid <= 39:
                        if score >= cfg.scoremap[classid]:
                            suites.setvalue(cardinfo.SUITES_HAEART, score, box)
                            cardval.setvalue(classid - 26, score, box)
                    if classid >= 40 and classid <= 52:
                        if score >= cfg.scoremap[classid]:
                            suites.setvalue(cardinfo.SUITES_SPADE, score, box)
                            cardval.setvalue(classid - 39, score, box)
        else:
            if classid >= 1 and classid <= 13:
                if score >= cfg.scoremap[classid]:
                    suites.setvalue(cardinfo.SUITES_CLUB, score, box)
                    cardval.setvalue(classid, score, box)
            elif classid >= 14 and classid <= 26:
                if score >= cfg.scoremap[classid]:
                    suites.setvalue(cardinfo.SUITES_DIAMOND, score, box)
                    cardval.setvalue(classid - 13, score, box)
            elif classid >= 27 and classid <= 39:
                if score >= cfg.scoremap[classid]:
                    suites.setvalue(cardinfo.SUITES_HAEART, score, box)
                    cardval.setvalue(classid - 26, score, box)
            elif classid >= 40 and classid <= 52:
                if score >= cfg.scoremap[classid]:
                    suites.setvalue(cardinfo.SUITES_SPADE, score, box)
                    cardval.setvalue(classid - 39, score, box)
            else:
                pass

        if suites.init and not cardval.init:
            save_descjudge = suites.to_str()
            save_scorejudge = suites.score
            # logger.info('suite:%s classid=%d, score:%.4f' %(suites.to_str(), suites.classid, suites.score))
        elif not suites.init and cardval.init:
            save_descjudge = cardval.to_str()
            save_scorejudge = cardval.score
            # logger.info('cardval:%s classid=%d, score:%.4f' %(cardval.to_str(), cardval.classid, cardval.score))
        elif suites.init and cardval.init:
            save_descjudge = "%s_%s" % (suites.to_str(), cardval.to_str())
            save_scorejudge = float((suites.score + cardval.score) / 2.0)
            # logger.info('card:%s_%s, suites_classid=%d, suites_score:%.4f,cardval_classid=%d, cardval_score:%.4f '
            #             %(suites.to_str(), cardval.to_str(),suites.classid, suites.score,cardval.classid, cardval.score))
        else:
            # For non-card outputs (e.g., class 0 = card-back), still return a usable score
            # so VideoManager can threshold / log / save the frame.
            try:
                save_scorejudge = float(score.numpy()) if hasattr(score, 'numpy') else float(score)
            except Exception:
                try:
                    save_scorejudge = float(confidence)
                except Exception:
                    save_scorejudge = 0.0

        return suites, cardval, save_descjudge, save_scorejudge, classid
    
    def warmup(self, iters: int = 2, size: tuple[int, int] | None = None) -> None:
        """
        One-time GPU/TF graph warm-up using the same preprocessing and model call
        as do_predict_one_label(). Safe to run in a background thread.
        """
        if getattr(self, "_warmed_up", False):
            return

        try:
            import numpy as np
            import tensorflow as tf
        except Exception as e:
            try:
                logger.info("WARMUP: deps missing; skipping (%s)" % str(e))
            except Exception:
                pass
            self._warmed_up = True
            return

        # Decide frame size
        try:
            if size and len(size) == 2:
                H, W = int(size[0]), int(size[1])
            else:
                # Prefer config if present, else a safe default
                H = int(getattr(cfg, "videoheight", 720))
                W = int(getattr(cfg, "videowidth", 1280))
        except Exception:
            H, W = 720, 1280

        # Build a black dummy frame (RGB uint8)
        dummy_rgb = np.zeros((H, W, 3), dtype=np.uint8)

        # Use the same JPEG-bytes -> preprocess -> [1,H,W,C] pipeline
        image_bytes = tf.io.encode_jpeg(tf.convert_to_tensor(dummy_rgb),
                                        format='rgb', quality=95)
        try:
            image_raw_mat = load_and_preprocess_image(image_bytes, False)
        except Exception:
            # if the standard path is unavailable, try JK’s
            image_raw_mat = load_and_preprocess_image_jk(image_bytes, False)

        image_tensor = tf.expand_dims(image_raw_mat, axis=0)

        ok = False
        try:
            # Run a couple of real forwards to trigger kernel selection/allocs
            for _ in range(max(1, int(iters))):
                _ = self.model(image_tensor, training=False)
            ok = True
        except Exception as e:
            try:
                logger.info("WARMUP: model forward failed once (%s) — still marking warmed" % str(e))
            except Exception:
                pass

        self._warmed_up = True
        try:
            if ok:
                logger.info("WARMUP: detector completed (iters=%d, size=%dx%d, gpu=%s)" %
                            (iters, W, H, getattr(self, "gpu_name", "n/a")))
            else:
                logger.info("WARMUP: detector marked warmed (no-op)")
        except Exception:
            pass

