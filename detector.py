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

class Detector(object):
    def __init__(self):
        logger.info('Detector constructed...')
        logger.info(f"Detector tf list_physical_devices: {tf.config.list_physical_devices('GPU')}")
        model_path = os.path.join(os.getcwd(), cfg.dnn_model)

        # Print model path for debugging
        logger.info(f"Loading model from: {model_path}")

        if not os.path.exists(model_path):
            raise FileNotFoundError(f"Model path does not exist: {model_path}")

        # 20240827 load and use infer model using Basic_CNNs_TensorFlow2_c54_poker training tool codes
        self.model = tf.saved_model.load(model_path)

        # tf1 codes
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

    # 20240827 就我認知，目前都用do_predict_one_label
    # def do_predict_multi_label(self, image, gmcode, index):
    #     '''
    #     多标签预测  花色及牌值
    #     :param image_expanded:
    #     :param gmcode:
    #     :return:
    #     '''
    #     image_expanded = np.expand_dims(image, axis=0)
    #     start_time = lambda: int(round(time.time() * 1000))
    #     start_time = start_time()
    #     logger.info('do_predict_multi_label start, gmcode=%s, index=%d' % (gmcode, index))
    #     # tf1 codes
    #     # (boxes, scores, classes, num) = self.sess.run(
    #     #     [self.detection_boxes, self.detection_scores, self.detection_classes, self.num_detections],
    #     #     feed_dict={self.image_tensor: image_expanded})

    #     # end_time = lambda: int(round(time.time() * 1000))

    #     # tf2 codes
    #     # Perform inference
    #     output_dict = self.infer(tf.constant(image_expanded))
    #     # 20240619 [INFO][MainThread] Model output signature: {'output_1': TensorSpec(shape=(None, 54), dtype=tf.float32, name='output_1')}

    #     end_time = time.time()
    #     logger.info('do_predict_multi_label finished, gmcode=%s, index=%d, span=%dms' % (gmcode, index, end_time - start_time))

    #     suites = predict.PredictResult()
    #     cardval = predict.PredictResult()

    #     # tf1 codes
    #     # (boxes, scores, classes, num) = self.sess.run(
    #     #     [self.detection_boxes, self.detection_scores, self.detection_classes, self.num_detections],
    #     #     feed_dict={self.image_tensor: image_expanded})

    #     # end_time = lambda: int(round(time.time() * 1000))
    #     # end_time = end_time()
    #     # logger.info('do_predict_multi_label finished, gmcode=%s, index=%d, span=%dms' % (gmcode, index, end_time - start_time))

    #     # suites = predict.PredictResult()
    #     # cardval = predict.PredictResult()

    #     # 标记是否预测成功
    #     is_success = False
    #     #是否保存
    #     is_savetmp = False
    #     suitesjudge = predict.PredictResult()
    #     cardvaljudge = predict.PredictResult()
    #     rows, cols = classes.shape
    #     for i in range(rows):
    #         for j in range(cols):
    #             classid = classes[i, j]
    #             score = scores[i][j]
    #             box = boxes[i][j]

    #             if classid >= 1 and classid <= 52 and score >= 0.85:
    #                 suitesjudge, cardvaljudge = self.predit_savemagetmp_result(classid, score, box)
    #                 is_savetmp = True

    #             # 获取预测的花色
    #             if not suites.init and predict.is_suites(classid):
    #                 if score >= cfg.scoremap[classid]:
    #                     suites.setvalue(classid, score, box)

    #             # 获取预测的点数
    #             if not cardval.init and predict.is_cardVal(classid):
    #                 if score >= cfg.scoremap[classid]:
    #                     cardval.setvalue(classid, score, box)

    #             # 花色和牌值全部预测成功
    #             if suites.init and cardval.init:
    #                 is_success = True
    #                 break

    #         if is_success:
    #             break

    #     if suites.init and not cardval.init:
    #         logger.info('suite:%s classid=%d, score:%.4f(%d,%d)' %
    #                     (suites.to_str(), suites.classid, suites.score))

    #     if not suites.init and cardval.init:
    #         logger.info('cardval:%s classid=%d, score:%.4f(%d,%d)' %
    #                     (cardval.to_str(), cardval.classid, cardval.score))

    #     if suites.init and cardval.init:
    #         logger.info('card:%s_%s, '
    #                     ' suites_classid=%d, suites_score:%.4f'
    #                     ' cardval_classid=%d, cardval_score:%.4f ' %
    #                     (suites.to_str(), cardval.to_str(),
    #                      suites.classid, suites.score,
    #                      cardval.classid, cardval.score))

    #     # 判断>0.85逻辑保存
    #     if suitesjudge.init and not cardvaljudge.init:
    #         save_descjudge = suitesjudge.to_str()
    #         save_scorejudge = suitesjudge.score
    #     if not suitesjudge.init and cardvaljudge.init:
    #         save_descjudge = cardvaljudge.to_str()
    #         save_scorejudge = cardvaljudge.score
    #     if suitesjudge.init and cardvaljudge.init:
    #         save_descjudge = "%s_%s" % (suitesjudge.to_str(), cardvaljudge.to_str())
    #         save_scorejudge = float((suitesjudge.score + cardvaljudge.score) / 2.0)
    #     return suites, cardval, save_descjudge, save_scorejudge

    # 20240619 : obsolete, tf2新模型不偵測位置，只純分類，無法使用模型去擷取牌的位置
    # def get_puke_area(self, image):
    #     #     image = cv2.imread(imgpath)
    #     height = image.shape[0]
    #     width = image.shape[1]
    #     # img_gray = cv2.cvtColor(image, cv2.COLOR_BGR2GRAY)
    #     image_expanded = np.expand_dims(image, axis=0)

    #     # # tf2 codes # 不要使用，tf2新模型沒有偵測位置，只有純分類
    #     # output_dict = self.infer(tf.constant(image_expanded))
    #     # scores = output_dict['detection_scores'].numpy()[0]
    #     # wanted_index = np.argmax(scores)
    #     # ymin, xmin, ymax, xmax = output_dict['detection_boxes'].numpy()[0][wanted_index]

    #     # ymin = int(ymin * height)
    #     # xmin = int(xmin * width)
    #     # ymax = int(ymax * height)
    #     # xmax = int(xmax * width)

    #     # tf1 codes    
    #     (boxes, scores, classes, num) = self.sess.run(
    #         [self.detection_boxes, self.detection_scores, self.detection_classes, self.num_detections],
    #         feed_dict={self.image_tensor: image_expanded})
    #     scores_list = scores[0].tolist()
    #     wanted_index = scores_list.index(max(scores_list))
    #     ymin = boxes[0][wanted_index][0] * height  # ymin
    #     xmin = boxes[0][wanted_index][1] * width  # xmin
    #     ymax = boxes[0][wanted_index][2] * height  # ymax
    #     xmax = boxes[0][wanted_index][3] * width  # xmax
    #     # print(xmin, ymin, xmax, ymax)


    #     return int(xmin), int(ymin), int(xmax), int(ymax)

    def do_predict_one_label(self, image, gmcode, index, rotation, frame_id):
        '''
        单标签预测，为与多分类统一接口，将预测的结果分为花色和牌值进行返回
        :param image_expanded:
        :param gmcode:
        :return:
        '''
        # 20240827 用traing tool之preprocess
        def load_and_preprocess_image(image, data_augmentation=False):
            # 20240827 依照training_tool之configuration
            IMAGE_HEIGHT = 299
            IMAGE_WIDTH = 299
            CHANNELS = 3
            # decoder # 20241209, dont encode then decode
            # image_raw = tf.io.encode_jpeg(image)
            # image_tensor = tf.io.decode_image(contents=image, channels=CHANNELS , dtype=tf.dtypes.float32)

            # 20241209
            # Ensure image is a NumPy array or TensorFlow tensor
            image_tensor = tf.convert_to_tensor(image, dtype=tf.dtypes.float32) / 255.0  # Normalize
            # np.save(f"img_{frame_id}.npy", image_tensor.numpy())

            if data_augmentation:
                image = tf.image.random_flip_left_right(image=image_tensor)
                image = tf.image.resize_with_crop_or_pad(image=image,
                                                        target_height=int(IMAGE_HEIGHT * 1.2),
                                                        target_width=int(IMAGE_WIDTH * 1.2))
                image = tf.image.random_crop(value=image, size=[IMAGE_HEIGHT, IMAGE_WIDTH, CHANNELS])
                image = tf.image.random_brightness(image=image, max_delta=0.5)
            else:
                image = tf.image.resize(image_tensor, [IMAGE_HEIGHT, IMAGE_WIDTH])

            return image

        # 20241205 為了檢驗preprocess有沒有錯誤，寫一個function在local disk寫入preprocess好的tensor轉回image
        def save_image_from_tensor(tensor, output_path):
            # Convert tensor to NumPy array
            image_array = tensor.numpy()
            
            # Scale values back to the range [0, 255] if necessary
            image_array = (image_array * 255).astype(np.uint8)
            
            # Save the image
            # Generate a timestamp
            from datetime import datetime
            timestamp = datetime.now().strftime('%Y%m%d_%H%M%S')
            filename = f"{output_path}_{timestamp}.png"

            cv2.imwrite(filename, image_array)
            print(f"Image saved to {filename}")

        # 20240619 obsolete : 無法偵測牌的位置
        # if detectPos:
        #     xmin, ymin, xmax, ymax = self.get_puke_area(image)
        #     image = image[ymin:ymax, xmin:xmax]
        #     # cv2.imwrite("test.jpg", image)

        # 20240827 tf1 code
        # if rotation:
        #     predict_image_rotation = cv2.flip(image, -1)
        #     image_expanded_rotation = np.expand_dims(predict_image_rotation, axis=0)
        # image_expanded = np.expand_dims(image, axis=0)

        # 20240827 tf2 code
        # if rotation:
        #     predict_image_rotation = cv2.flip(image, -1)
        #     image_expanded_rotation = np.expand_dims(predict_image_rotation.astype(np.float32) / 255.0, axis=0)
        # image_expanded = np.expand_dims(image.astype(np.float32) / 255.0, axis=0)
        # logger.info(f'image_expanded : {image_expanded}')

        # make cv image into bytes
        image_tensor = load_and_preprocess_image(image)

        #20241205 save temp image from tensor to see the result of preprocessing
        # save_image_from_tensor(image_tensor, f'processed_image_{frame_id}')

        image_tensor = tf.expand_dims(image_tensor, axis=0)

        suites = predict.PredictResult()
        cardval = predict.PredictResult()

        suitesjudge = predict.PredictResult()
        cardvaljudge = predict.PredictResult()

        save_descjudge = ''
        save_scorejudge = 0.0
        start_time = lambda: int(round(time.time() * 1000))
        start_time = start_time()
        #logger.info('do_predict_one_label start, gmcode=%s, index=%d' % (gmcode, index))

        # 20240827 use training tool code, 以下因新模型只output 54 classes機率，code要做對應的修正，沒有detection_boxes
        # Perform inference
        pred = self.model(image_tensor, training=False)
        # logger.info(f'output dict from tf model : {pred}')
        confidence= np.array(   tf.math.abs(pred).numpy()  ).max()
        idx = tf.math.argmax(pred, axis=-1).numpy()[0]

        # try:
        #     pass
        # except Exception as e:
        #     logger.error('tensorflow use model error occured: {}'.format(e))
        #     return suites, cardval, save_descjudge, save_scorejudge

        end_time = lambda: int(round(time.time() * 1000))
        end_time = end_time()
        # logger.info('do_predict_one_label finished, gmcode=%s, index=%d, span=%dms' % (gmcode, index, end_time - start_time)) # 20241112 comment out to clean terminal

        score = pred[0][idx]
        classid = idx
        # 20240815 測試boxes隨便給值會不會出問題，按照JK，onebox有產出但後續程式根本沒用到，需確認onebox是否真的不影響後面
        # 給值比照c++版puke_recognizer的值
        box = [0,1,2,3]

        # 20240827 因應目前訓練也會拿斜圖做訓練，不先實裝rotation
        if rotation:
            scores_list_rotation = scores_rotation[0].tolist()
            rotation_wanted_index = scores_list_rotation.index(max(scores_list_rotation))
            score_rotation = scores_rotation[0][rotation_wanted_index]
            classid_rotation = classes_rotation[0][wanted_index]
            box_rotation = boxes_rotation[0][rotation_wanted_index]
            #if score_rotation < cfg.scoremap[classid_rotation]:
            #    logger.info('do_predict_one_label gmcode=%s, index=%d, rotation predict score is too low' % (gmcode, index))

        # if score < cfg.scoremap[classid]:
        #     logger.warning('do_predict_one_label gmcode=%s, index=%d, predict score is too low' % (gmcode, index))

        # # 當判斷為牌時
        # if classid >= 1 and classid <= 52:
        #     logger.info(f'classid range in 1~52, classid = {classid}')
        # else:
        #     logger.info(f'classid range not in 1~52, classid = {classid}')

        # 20240827 因應目前訓練也會拿斜圖做訓練，不先實裝rotation
        if rotation:
            if classid_rotation == classid:
                if score >= cfg.scoremap[classid] and score_rotation >= cfg.scoremap[classid_rotation]:
                    # 梅花
                    if classid >= 1 and classid <= 13:
                        if score >= cfg.scoremap[classid]:
                            suites.setvalue(cardinfo.SUITES_CLUB, score, box)
                            cardval.setvalue(classid, score, box)
                    # 方块
                    if classid >= 14 and classid <= 26:
                        if score >= cfg.scoremap[classid]:
                            suites.setvalue(cardinfo.SUITES_DIAMOND, score, box)
                            cardval.setvalue(classid - 13, score, box)

                    # 红桃
                    if classid >= 27 and classid <= 39:
                        if score >= cfg.scoremap[classid]:
                            suites.setvalue(cardinfo.SUITES_HAEART, score, box)
                            cardval.setvalue(classid - 26, score, box)

                    # 黑桃
                    if classid >= 40 and classid <= 52:
                        if score >= cfg.scoremap[classid]:
                            suites.setvalue(cardinfo.SUITES_SPADE, score, box)
                            cardval.setvalue(classid - 39, score, box)
            #else:
                #logger.info('classid=%d, classid_rotation=%d they are not equal' % (classid, classid_rotation))
        else:
            # 梅花
            if classid >= 1 and classid <= 13:
                if score >= cfg.scoremap[classid]:
                    suites.setvalue(cardinfo.SUITES_CLUB, score, box)
                    cardval.setvalue(classid, score, box)
            # 方块
            elif classid >= 14 and classid <= 26:
                if score >= cfg.scoremap[classid]:
                    suites.setvalue(cardinfo.SUITES_DIAMOND, score, box)
                    cardval.setvalue(classid - 13, score, box)

            # 红桃
            elif classid >= 27 and classid <= 39:
                if score >= cfg.scoremap[classid]:
                    suites.setvalue(cardinfo.SUITES_HAEART, score, box)
                    cardval.setvalue(classid - 26, score, box)

            # 黑桃
            elif classid >= 40 and classid <= 52:
                if score >= cfg.scoremap[classid]:
                    suites.setvalue(cardinfo.SUITES_SPADE, score, box)
                    cardval.setvalue(classid - 39, score, box)
            else:
                # logger.info(f'predict classid not in range 1~52, suits & cardval not initialized, classid = {classid}')
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
            # logger.info(f'suits and cardval not initialized, the card not detected')
            pass

        return suites, cardval, save_descjudge, save_scorejudge, classid
