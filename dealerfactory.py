# encoding=utf-8

from dealerprotocol import DealerProtocol
from twisted.internet import protocol
import pylogger as logger

class DealerFactory(protocol.ClientFactory):
    #protocol = DealerProtocol

    def __init__(self, dealer, loginId):
        self.dealer = dealer
        self.seq = 0
        self.loginId = loginId

    def buildProtocol(self, addr):
        logger.info('buildProtocol')
        self.protocol = DealerProtocol(self)
        return self.protocol

    def clientConnectionLost(self, connector, reason):
        logger.info('connection lost reason: %s' % reason)
        if self.dealer:
            self.dealer.connectionDealerLost()

    def clientConnectionFailed(self, connector, reason):
        logger.info('connection failed reason: %s' % reason)
        if self.dealer:
            self.dealer.connectionDealerFailed()

    def handleCmd(self, cmd, seq, body):
        if self.dealer:
            self.dealer.handleCmd(cmd, seq, body)

    def sendData(self, data):
        if self.protocol:
            logger.info('dealer factory, sendData, len=%d' % (len(data)))
            self.protocol.sendData(data)





