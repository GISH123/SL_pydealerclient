#encoding=utf-8

import threading
import time
import pylogger as logger
import csvtool as csvtooler
from twisted.internet.task import LoopingCall
from config import cfg
from datamanager import DataMgrInstance
from datetime import datetime
from cardmsg import ScanResult

class ScanResultManager(object):
    def __init__(self):
        '''
        初始化
        '''
        self.gmcode = ''
        self.gmlastcode = ''
        self.predictFlag = False
        self.lock = threading.Lock()
        # 扫描牌结果
        self.scanmapcard = dict()
        # 保存每一张牌的csv
        self.csvmap = {}
        # 保存最后结果的csv（key = gmcode bytes(14)）
        self.csvResutmap = {}
        self.tickTimer = LoopingCall(self.onTick)
        self.tickTimer.start(0.2, False)
        self.lashCheckTimestamp = 0
        self.detecttimes = cfg.detecttimes
        self.curDate = datetime.now().strftime('%Y-%m-%d')
        self.gmCount = 0

    def onRefresh(self, timestamp):
        if timestamp - self.lashCheckTimestamp >= 1:
            self.lashCheckTimestamp = timestamp

    def onTick(self):
        self.onRefresh(int(time.time() * 1000))

    # ---------------------------------------------------------------- utils
    @staticmethod
    def _normalize_gmcode(gmcode):
        """確保使用原始 14-byte 值（老架構有時會傳 tuple/list）。"""
        if isinstance(gmcode, (tuple, list)):
            return gmcode[0]
        return gmcode

    def _toString(self, data):
        """移除字串中的 NUL 字元。"""
        return ''.join([c for c in data if c != '\000'])

    @staticmethod
    def _gmcode_text(gmcode):
        """
        將 gmcode 轉為可寫入 CSV/日誌的純文字：
        - bytes/bytearray: 去尾端 NUL 後以 ASCII 解碼（忽略無法解碼字元）
        - tuple/list: 取第一個元素再遞迴處理
        - 其他: 轉成字串並去除 NUL
        """
        if isinstance(gmcode, (tuple, list)):
            gmcode = gmcode[0]
        if isinstance(gmcode, (bytes, bytearray)):
            try:
                s = gmcode.rstrip(b'\x00').decode('ascii', 'ignore')
            except Exception:
                # 保底：用 str()，再做簡單清理
                s = str(gmcode)
        else:
            s = str(gmcode)
        return s.replace('\x00', '')

    # ---------------------------------------------------------------- scan/save (per-card)
    def saveScanResult(self, gmcode, index, cardVal):
        self.saveScanResultNolock(gmcode, index, cardVal)

    def saveScanResultNolock(self, gmcode, index, cardVal):
        self.gmcode = gmcode
        # logger.info('datamanager saveScanResult gmcode=%s, index=%d, cardVal=%d' % (gmcode, index, cardVal))
        self.scanmapcard[index] = cardVal

    # ---------------------------------------------------------------- final save for a round
    def SaveFinalResult(self, gmcode):
        gmcode = self._normalize_gmcode(gmcode)

        curDate = datetime.now().strftime('%Y-%m-%d')
        if curDate == self.curDate:
            self.gmCount += 1
        else:
            self.curDate = curDate
            self.gmCount = 0

        # logger.info('gmSaveFinalResult, gmcode=%s, len(scanmap)=%d, gmCount=%d' %
        #             (gmcode, len(self.scanmapcard), self.gmCount))

        # Write the final CSV rows for THIS gmcode
        self.savetocsvfinaresult(gmcode)

        # Clear caches for THIS gmcode
        self.clearCardMap(gmcode)

        # Notify snapshot if enabled
        DataMgrInstance().notify_ImageSaver()

    def savetocsvfinaresult(self, gmcode):
        """Write final result rows for the given gmcode to CSV."""
        gmcode = self._normalize_gmcode(gmcode)
        self.lock.acquire()
        try:
            messagelist = []
            if gmcode in self.csvResutmap.keys():
                csvlistm = self.csvResutmap[gmcode]
                # logger.info('scanresultsave.py savetocsvfinaresult(), gmcode=%s, len(csvlistm)=%d'
                #             % (gmcode, len(csvlistm)))
                # logger.info(f"csvlistm: {csvlistm}")
                for csvlist in csvlistm:
                    messagelist.append(csvlist)
            else:
                # logger.info('savetocsvfinaresult() no entry for gmcode=%s; csvResutmap keys=%s'
                #             % (gmcode, list(self.csvResutmap.keys())))
                pass

            if len(messagelist) > 0:
                # logger.info("scanresultsave.py savetocsvfinaresult(), csvtooler.tocsv to save csvfile.")
                csvtooler.tocsv(messagelist, True)
        finally:
            self.lock.release()

    # ---------------------------------------------------------------- cleanup
    def clearCardMap(self, gmcode):
        # logger.info('clearCarMap, gmcode=%s' % (gmcode))
        self.lock.acquire()
        try:
            if len(self.csvmap) > 0:
                self.csvmap.clear()
            if len(self.csvResutmap) > 0:
                self.csvResutmap.clear()
            if len(self.scanmapcard) > 0:
                self.scanmapcard.clear()
        finally:
            self.lock.release()

    # ---------------------------------------------------------------- collect predicted finalists
    def saveFinaDeclareResult(self, gmcode, resultlist):
        self.lock.acquire()
        try:
            self.saveFinaDeclareResultNoLock(gmcode, resultlist)
        finally:
            self.lock.release()

    def saveFinaDeclareResultNoLock(self, gmcode, resultlist):
        # 這邊將當前卡牌框格預測的最後結果儲存到messagelist裡面，主要是為了最後寫入到csv用
        strgmcode = self._gmcode_text(gmcode)  # ← 取代 str(gmcode, encoding='utf-8')
        messagelist = []
        for res in resultlist:
            message = []
            message.append(strgmcode)
            message.append(res.index)
            message.append(res.dealer_classid)   # 20241115 add dealer_classid
            message.append(res.predict_classid)  # prediction_classid
            message.append(res.score)
            message.append(res.card_point)       # 卡牌的數值
            message.append(0)                    # 20241115 按照jieqi的格式, endid 先預設為0
            messagelist.append(message)

            # 注意：這裡仍以「原始 gmcode 物件」當作 key，避免破壞舊邏輯
            if gmcode in self.csvResutmap.keys():
                self.csvResutmap[gmcode].append(message)
                # logger.info('saveFinaDeclareResultNoLock append, gmcode=%s, message=%s' %
                #             (strgmcode, message))
            else:
                self.csvResutmap[gmcode] = messagelist
                # logger.info('saveFinaDeclareResultNoLock new list, gmcode=%s, message=%s' %
                #             (strgmcode, message))


dataMgr = ScanResultManager()

def ScanRMgrInstance():
    return dataMgr
