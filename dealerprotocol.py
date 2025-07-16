#encondig=utf-8

import struct
import time
import cardmsg

from twisted.internet import protocol
from twisted.internet.task import LoopingCall
import pylogger as logger

CHECK_PEER_TICK = 10000

class DealerProtocol(protocol.Protocol):
    def __init__(self, factory):
        self.cache = b''
        self.lashCheckTimestamp = self.getTimeStamp()
        self.tickTimer = LoopingCall(self.onTick)
        self.factory = factory

    def getTimeStamp(self):
        return int(time.time() * 1000)

    def connectionMade(self):
        logger.info('connect to %s success' % self.transport.getPeer())
        loginId = '1001'
        if self.factory.dealer:
            self.factory.dealer.connectionDealerMade()
            loginId = self.factory.loginId
        else:
            logger.info('dealer is null')

        # 发送登录协议
        pkt = cardmsg.PK_Login()
        data = pkt.pack(loginId)
        self.sendData(data)
        logger.info('start login, id=%s...' % (loginId))
        self.tickTimer.start(0.2, False)

    def connectionLost(self, reason):
        logger.info('%s disconnected, reson=%s' % (self.transport.getPeer(), reason))
        self.tickTimer.stop()
        self.tickTimer = None

    def sendData(self, data):
        #logger.info('sendData, len=%d' % (len(data)))
        self.transport.write(data)

    def dataReceived(self, data):
        self.cache += data
        while len(self.cache) >= cardmsg.CMD_HEAD_LEN:
            #解压报文头
            head = self.cache[:cardmsg.CMD_HEAD_LEN]
            cmd, size, seq = struct.unpack('!IiI', head)
            logger.info('dataReceived, cmd=%s, size=%s, seq=%s' % (hex(cmd), size, seq))

            # 数据没有接受完整
            if size > 0 and len(self.cache) < size:
                break

            # 解压报文
            body = self.cache[cardmsg.CMD_HEAD_LEN:size]
            logger.info('dataReceived, cmd=%s seq=%s body=%s' % (hex(cmd), seq, body))
            self._handleCmd(cmd, seq, body)
            self.cache = self.cache[size::]


    def _handleCmd(self, cmd, seq, body):
        self.factory.handleCmd(cmd, seq, body)

    def ping(self):
        if self.transport:
            logger.info('ping....')
            pkt = cardmsg.PK_KeepAlive()
            data = pkt.pack()
            self.transport.write(data)

    def onRefresh(self, timestamp):
        if timestamp - self.lashCheckTimestamp > CHECK_PEER_TICK:
            self.lashCheckTimestamp = timestamp
            self.ping()

    def onTick(self):
        self.onRefresh(int(time.time() * 1000))




