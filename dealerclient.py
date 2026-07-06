#encoding=utf-8

from twisted.internet import reactor, threads
import pylogger as logger
from dealerfactory import  DealerFactory
# from dev_mgr_factory import  DevMgrFactory
import cardmsg
import struct
from cardinfo import CardInfo
import config
import random

from datamanager import DataMgrInstance
from scanresultsave import ScanRMgrInstance

import latency_round as _LAT   # NEW
from pathlib import Path             # (likely already present; harmless if duplicated once)

# ---- gmcode helpers (exactly 14 ASCII bytes; DTyymmddhhmmss) ----
def _norm_gmcode(gm):
    # return a 14-char ASCII string
    if isinstance(gm, bytes):
        gm = gm.decode("ascii", errors="ignore")
    gm = (gm or "").strip("\x00")
    return gm[:14] if len(gm) > 14 else gm

# alias (in case other places use the *_str name)
def _norm_gmcode_str(gm):
    return _norm_gmcode(gm)

def _gmcode_bytes_14(gm):
    # return exactly 14 bytes (ASCII, NUL-padded)
    s = _norm_gmcode(gm)
    b = s.encode("ascii", "ignore")[:14]
    return b + (b"\x00" * (14 - len(b)))

class DealerClient(object):
    '''
    This file likely handles client-specific logic
    處理荷官端特定的商業邏輯，如handleCMD，某些傳過來的packet代表的意思
    '''

    def __init__(self, dealerIp, dealerPort, loginId):
        self.dealerIp = dealerIp
        self.dealerPort = dealerPort
        self.loginId = loginId
        self.dealerConnected = False
        self.auth = False
        self.gamecode = ''
        self.current_gmcode = None 
        reactor.callLater(3, self.connectDealer)
        DataMgrInstance().register_senddata(self.sendPredictResult)

    # ============================
    # 使用 DataMgrInstance 傳送預測結果給荷官端（原始行為）
    def sendPredictResult(self, resultlist):
        count = len(resultlist)
        if count == 0:
            return

        gmcode_s = self.gamecode.decode('ascii','ignore') if isinstance(self.gamecode,(bytes,bytearray)) else str(self.gamecode)
        gmcode_s = gmcode_s.replace('\x00','').strip()
        logger.info(f"[WAIT_NOTIFY] gmcode={gmcode_s} count={len(resultlist) if hasattr(resultlist,'__len__') else 1}")
        from predict_waiter import notify_result as _notify; _notify(gmcode_s, resultlist)

        gmcode_b = self.gamecode if isinstance(self.gamecode, (bytes, bytearray)) \
                else str(self.gamecode).encode('ascii','ignore')
        gmcode_b = gmcode_b[:14].ljust(14, b'\x00')

        body = struct.pack('!14sh', gmcode_b, count)
        for res in resultlist:
            body += struct.pack('!2hd', int(res.index), int(res.dealer_classid), float(res.score))

        totalSize = cardmsg.CMD_HEAD_LEN + len(body)
        head = struct.pack('!3i', cardmsg.CMD_PREDICT_RESULT, totalSize, 0)
        data = head + body

        # === 新增：在送 Dealer 之前，就先通知 HTTP 等候端（備援層）===
        try:
            from predict_waiter import notify_result as _notify_http_waiter
        except Exception:
            _notify_http_waiter = None
        if _notify_http_waiter is not None:
            try:
                gmcode_s = self.gamecode.decode('ascii', 'ignore') if isinstance(self.gamecode, (bytes, bytearray)) else str(self.gamecode)
                gmcode_s = gmcode_s.replace('\x00', '').strip()
                _notify_http_waiter(gmcode_s, resultlist)
            except Exception as _e:
                logger.error("Prediction waiter notify failed: %s", _e)
        # === 新增結束 ===

        if self.factory:
            self.factory.sendData(data)

        # leave as-is if your saver expects str/bytes either way
        ScanRMgrInstance().saveFinaDeclareResult(self.gamecode, resultlist)
        
        # ---- 新增（備援通知）：函式末尾、保持原有送 Dealer 與 log 完整 ----
        try:
            from predict_waiter import notify_result as _notify_http_waiter
        except Exception:
            _notify_http_waiter = None

        if _notify_http_waiter is not None:
            try:
                gmcode_s = self.gamecode.decode("ascii","ignore") if isinstance(self.gamecode,(bytes,bytearray)) else str(self.gamecode)
                gmcode_s = gmcode_s.replace("\x00","").strip()
                _notify_http_waiter(gmcode_s, resultlist)
            except Exception as _e:
                logger.error("Prediction waiter notify failed: %s" % _e)

    # =============================================================================================

    # twisted connection

    def connectDealer(self):
        logger.info('connect dealer %s:%s ...' %(self.dealerIp,  self.dealerPort))
        self.factory = DealerFactory(self, self.loginId)
        reactor.connectTCP(self.dealerIp, self.dealerPort, self.factory)

    def connectionDealerLost(self):
        # 重新连接荷官端
        reactor.callLater(config.TRY_CONNECT_DEALER_SECOND, self.connectDealer)
        self.dealerConnected = False

    def connectionDealerFailed(self):
        # 重新连接荷官端
        reactor.callLater(config.TRY_CONNECT_DEALER_SECOND, self.connectDealer)
        self.dealerConnected = False

    def connectionDealerMade(self):
        self.dealerConnected = True
        logger.info('connectionDealerMade...')

    # =====================================================
    # 處理接收從荷官端發射訊號（header 已在外層處理；這裡只解 body）
    def handleCmd(self, cmd, seq, body):
        try:
            if cmd == cardmsg.CMD_LOGIN_R:
                code, gmtype, vid = struct.unpack(cardmsg.FMT_BODY_PK_LOGIN_R, body)
                self.onLoginRet(code, gmtype, vid)
                return

            # --- START_PREDICT -------------------------------------------------
            elif cmd == cardmsg.CMD_START_PREDICT:
                try:
                    if len(body) == 18:  # perf mode: !14s h h
                        gmcode_raw, gmstate, perf16 = struct.unpack('!14shh', body)
                    elif len(body) == 16:  # compat: !14s h
                        gmcode_raw, gmstate = struct.unpack('!14sh', body)
                        perf16 = None
                    else:
                        logger.error('onStartPredict unexpected body len=%d' % len(body))
                        return
                    
                    gmcode = gmcode_raw.rstrip(b'\x00').decode('ascii', 'ignore')

                    if len(body) == 18:
                        # !14s h h  (perf16 present)
                        logger.info('onStartPredict (!14shh), gmcode=%s, gmstate=%d, perf16=%d' %
                                    (gmcode, gmstate, perf16))
                    else:
                        # !14s h  (compat)
                        logger.info('onStartPredict (!14sh), gmcode=%s, gmstate=%d' %
                                    (gmcode, gmstate))

                    _LAT.mark_start(gmcode=gmcode, perf16=perf16 if len(body)==18 else None, gmstate=gmstate)
                    self.current_gmcode = gmcode
                    self.onStartPredict(gmcode, gmstate)
                except Exception as e:
                    logger.error('onStartPredict unpack error: %s' % e)
                    return

            # --- STOP_PREDICT ---------------------------------------------------
            elif cmd == cardmsg.CMD_STOP_PREDICT:
                if len(body) != 16:
                    logger.error('onStopPredict unexpected body len=%d' % len(body))
                    return

                gmcode_raw, gmstate = struct.unpack('!14sh', body)
                gmcode = gmcode_raw.rstrip(b'\x00').decode('ascii', 'ignore')
                logger.info('onStopPredict, gmcode=%s, gmstate=%d' % (gmcode, gmstate))

                # 先跑完 onStopPredict（這是 latency 的終點）
                self.onStopPredict(gmcode, gmstate)

                # 再記錄 latency + 寫 CSV + 打 [Latency] log
                _LAT.mark_stop_and_write(gmcode=gmcode)

            elif cmd in (getattr(cardmsg, 'CMD_DISPATCH_INDEX', None),
                         getattr(cardmsg, 'CMD_DISPATCH_CARD', None)):
                try:
                    # BE: !14s h  -> (gmcode_raw, index)
                    gmcode_raw, index = struct.unpack('!14sh', body)
                    gm_str = gmcode_raw.rstrip(b'\x00').decode('ascii', 'ignore')
                    logger.info('onDispatchCard, gmcode=%s index=%d' % (gm_str, index))
                    self.onDispatchCard(gmcode_raw, index)
                except Exception as e:
                    logger.error('onDispatchCard unpack error: %s' % e)
                return

            elif getattr(cardmsg, 'CMD_KEEPALIVE', None) == cmd:
                # 若需回應可在此 echo；目前僅記錄
                logger.debug('KEEPALIVE seq=%d' % seq)
                return

            else:
                logger.error('handleCmd unknown cmd=0x%08x, seq=%d' % (cmd, seq))
                return

        except Exception as e:
            logger.error('handleCmd exception: %s' % e)

    # =============================================================================================
    # helper function for handleCmd
    def onLoginRet(self, code, gmtype, vid):
        if 0 == code:
            logger.info('login success, code=%d, gmtype=%s, vid=%s' % (code, gmtype, vid))
            self.auth = True
        else:
            logger.error('login failed, code=%d, gmtype=%s, vid=%s' % (code, gmtype, vid))
            self.auth = False

        try:
            gm = gmtype.rstrip(b"\x00").decode("ascii","ignore").strip()
        except Exception:
            gm = str(gmtype)

        # Map dealer gmtype to internal DataManager mode
        if gm == "LAT":
            DataMgrInstance().setgametype("lattest")
        elif gm == "BAC":
            DataMgrInstance().setgametype("BAC")
        elif gm == "DT":
            DataMgrInstance().setgametype("DT")

    def onStartPredict(self, gmcode, gmstate):
        self.gamecode = gmcode
        logger.info('onStartPredict, gmcode=%s, gmstate=%d' % (str(gmcode), gmstate))
        DataMgrInstance().startPredict(self.gamecode, gmstate)

    def onDispatchCard(self, gmcode, index):
        logger.info('onDispatchCard, gmcode=%s index=%d' % (gmcode, index))
        DataMgrInstance().dispatchCard(gmcode, index)

    def onStopPredict(self, gmcode, gmstate):
        logger.info('onStopPredict, gmcode=%s, gmstate=%d' % (str(gmcode), gmstate))
        DataMgrInstance().stopPredict(gmcode, gmstate)

    def onSaveScanResult(self, gmcode, index, cardVal):
        logger.info('onSaveScanResult, gmcode=%s index=%d, cardVal=%d' % (gmcode, index, cardVal))
        ScanRMgrInstance().saveScanResult(gmcode, index, cardVal)

    def onSaveFinalResult(self, gmcode):
        # Normalize in case anything upstream passed a tuple/list
        if isinstance(gmcode, (tuple, list)):
            gmcode = gmcode[0]
        logger.info('onSaveFinalResult, gmcode=%s' % (gmcode))
        ScanRMgrInstance().SaveFinalResult(gmcode)

    def onCanselResult(self, gmcode):  # 20241114 這邊似乎沒用到
        logger.info('onCanselResult, gmcode=%s' % (gmcode))
        DataMgrInstance().ReScan(gmcode)
        ScanRMgrInstance().clearCardMap(gmcode)

    def onPredictReference(self, gmcode):  # 20241114 這邊似乎沒用到
        logger.info('onPredictReference, gmcode=%s' % (gmcode))

    def _toString(self, data):
        return ''.join([c for c in data if c != '\000'])

    def _mapStripNull(self, s):
        return map(lambda x: self._toString(x) if type(x) is str else x, s)
