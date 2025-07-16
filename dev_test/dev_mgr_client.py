#encoding=utf-8

from twisted.internet import reactor, threads
import pylogger as logger
from dev_mgr_factory import  DevMgrFactory
import config
import random
import commu_pb2
import version
from twisted.internet.task import LoopingCall
import time

DEV_Stat_IDLE = 0
DEV_Stat_CONNECTING = 1
DEV_Stat_CONNECTED = 2
DEV_Stat_LOGINING = 3
DEV_Stat_LOGIN = 4

CHECK_PEER_TICK = 5*1000

class DevMgrClient(object):

    def __init__(self, devmgrIp, devmgrPort, vid):
        self.vid = vid
        self.devmgrIp = devmgrIp
        self.devmgrPort = devmgrPort
        self.devmgrConnected = False
        self.devStat = DEV_Stat_IDLE
        self.auth = False
        self.gamecode = ''
        self.connectDevMgr()

    def getTimeStamp(self):
        return int(time.time() * 1000)

    def connectDevMgr(self):
        logger.info('connect degmgr %s:%s ...' %(self.devmgrIp,  self.devmgrPort))
        self.devMgrFactory = DevMgrFactory(self, self.vid)
        reactor.connectTCP(self.devmgrIp, self.devmgrPort, self.devMgrFactory)
        self.devStat = DEV_Stat_CONNECTING

    def connectionDealerLost(self):
        # 重新连接荷官端
        reactor.callLater(config.TRY_CONNECT_DEVMGR_SECOND, self.connectDevMgr)
        self.devmgrConnected = False
        self.devStat = DEV_Stat_IDLE

    def connectionDealerFailed(self):
        # 重新连接荷官端
        reactor.callLater(config.TRY_CONNECT_DEVMGR_SECOND, self.connectDevMgr)
        self.devmgrConnected = False
        self.devStat = DEV_Stat_IDLE

    def connectionDealerMade(self):
        self.devmgrConnected = True
        logger.info('connectionDealerMade...')
        self.devStat = DEV_Stat_CONNECTED
        self.sendLogin()
        self.lashCheckTimestamp = self.getTimeStamp()
        reactor.callLater(0.5, self.onTick)

    def sendLogin(self):
        loginMsg = commu_pb2.Login()
        loginMsg.DevType = 'detect'
        loginMsg.TableId = self.vid
        loginMsg.Version = version.VERSION
        data = loginMsg.SerializeToString()
        #logger.info('sendData, len=%d' % (len(data)))
        if self.devMgrFactory:
            self.devMgrFactory.sendMsg('ivi.Login', data)

    def sendHeartInfo(self):
        if self.cuid:
            if self.devStat == DEV_Stat_LOGIN:
                heartInfoMsg = commu_pb2.HeartInfo()
                heartInfoMsg.Cuid = self.cuid
                data = heartInfoMsg.SerializeToString()
                if self.devMgrFactory:
                    self.devMgrFactory.sendMsg('ivi.HeartInfo', data)
        else:
            logger.info('cuid is null')
        #logger.info('sendData, len=%d' % (len(data)))

    def onLoginRet(self, code, cuid):
        if 0 == code:
            logger.info('login success, code=%d, cuid=%s' % (code, cuid))
            self.cuid = cuid
            self.devStat = DEV_Stat_LOGIN
            self.lashCheckTimestamp = self.getTimeStamp()
        else:
            logger.error('login failed, code=%d, cuid=%s' % (code, cuid))
            self.devStat = DEV_Stat_IDLE

    def handleMsg(self, type, body):
        logger.info('handleMsg, msgType=%s body=%s(%d)' % (type, body, len(body)))
        if 'ivi.LoginReply' == type:
            target = commu_pb2.LoginReply()
            target.ParseFromString(body)
            print(target)
            if not target.error is None:
                print('error=', target.error)
                self.onLoginRet(target.error, target.Cuid)
            else:
                self.onLoginRet(0, target.Cuid)
        else:
            logger.error('invalid msgType %s' % (type))

    def _toString(self, data):
        return ''.join([c for c in data if c != '\000'])

    def _mapStripNull(self, s):
        return map(lambda x: self._toString(x) if type(x) is str else x, s)

    def onRefresh(self, timestamp):
        if self.devStat == DEV_Stat_LOGIN:
            if timestamp - self.lashCheckTimestamp > CHECK_PEER_TICK:
                self.lashCheckTimestamp = timestamp
                self.sendHeartInfo()

    def onTick(self):
        self.onRefresh(int(time.time() * 1000))
        reactor.callLater(0.5, self.onTick)





