#encondig=utf-8

import struct
from twisted.internet import protocol
import pylogger as logger
import commu_pb2

import ctypes

CHECK_PEER_TICK = 10000

class DevMgrProtocol(protocol.Protocol):
    def __init__(self, factory, vid):
        self.cache = b''
        self.factory = factory
        self.vid = vid

    def connectionMade(self): # Called when a connection is made.
        logger.info('connect to %s success' % self.transport.getPeer())
        if self.factory.devmgr:
            self.factory.devmgr.connectionDealerMade()
        else:
            logger.info('dealer is null')

    def connectionLost(self, reason): # Called when the connection is shut down.
        logger.info('%s disconnected, reson=%s' % (self.transport.getPeer(), reason))

    def sendMsg(self, pbName, pbData):
        logger.info('sendMsg %s , datalen=%d' % (pbName, len(pbData)))
        nameLen = len(pbName)
        totalLen = 2 + 2 + nameLen + len(pbData) + 4
        buf = bytes(totalLen)
        s1 = struct.Struct('!hh%ds%ds' % (nameLen, len(pbData)))
        s2 = struct.Struct('!I')
        buf = ctypes.create_string_buffer(s1.size + s2.size)
        s1.pack_into(buf, 0, totalLen-2, nameLen, bytes(pbName, 'utf-8'), pbData)
        crcRes = self.adler32(buf[2:totalLen-4], totalLen-4-2)
        s2.pack_into(buf, s1.size, crcRes)
        logger.info('sendMsg totalLen = %d' % (totalLen))
        self.transport.write(buf)

    def adler32(self, buf, len):
        adler = 1
        s1 = adler & 0xffff
        s2 = (adler >> 16) & 0xffff

        for index in range(len):
            s1 = (s1 + buf[index]) % 65521
            s2 = (s2 + s1) % 65521
        return (s2 << 16) + s1

    def dataReceived(self, data): # Called whenever data is received.
        self.cache += data
        while len(self.cache) >= 8:
            #解压报文头
            totalLen, nameLen = struct.unpack('!2h', self.cache[:4])
            logger.info('dataReceived, totalLen=%d, nameLen=%d' % (totalLen, nameLen))

            # 数据没有接受完整
            if totalLen > 0 and len(self.cache) < totalLen + 2:
                break
            pktCrc = self.adler32(self.cache[2:2+totalLen-4], totalLen-4)
            fmt = '!%ds%dsI' % (nameLen, totalLen - 2 - nameLen - 4)
            pbName, pbData, crc = struct.unpack(fmt, self.cache[4:4+totalLen-2])
            if pktCrc != crc:
                logger.error('dataReceived, invalid crc')
                self.cache = self.cache[totalLen + 2:]
                break
            # 解压报文
            pbName = str(pbName, encoding='utf-8')
            logger.info('dataReceived, pbName=%s' % (pbName))
            self._handleMsg(pbName, pbData)
            self.cache = self.cache[totalLen + 2:]


    def _handleMsg(self, type, body):
        self.factory.handleMsg(type, body)





