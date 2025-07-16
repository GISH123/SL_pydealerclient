# encoding=utf-8

from dev_mgr_protocol import DevMgrProtocol
from twisted.internet import protocol
import pylogger as logger

class DevMgrFactory(protocol.ClientFactory):
    #protocol = DealerProtocol

    def __init__(self, devmgr, vid):
        self.devmgr = devmgr
        self.seq = 0
        self.vid = vid

    def buildProtocol(self, addr): # Create an instance of a subclass of Protocol.
        logger.info('buildProtocol')
        self.protocol = DevMgrProtocol(self, self.vid)
        return self.protocol

    def clientConnectionLost(self, connector, reason): # Called when an established connection is lost.
        logger.info('connection lost reason: %s' % reason)
        if self.devmgr:
            self.devmgr.connectionDealerLost()

    def clientConnectionFailed(self, connector, reason): # Called when a connection has failed to connect.
        logger.info('connection failed reason: %s' % reason)
        if self.devmgr:
            self.devmgr.connectionDealerFailed()

    def handleMsg(self, type, body):
        if self.devmgr:
            self.devmgr.handleMsg(type, body)

    def sendMsg(self, type, data):
        if self.protocol:
            logger.info('devmgr factory, sendMsg, type=%s len=%d' % (type, len(data)))
            self.protocol.sendMsg(type, data)





