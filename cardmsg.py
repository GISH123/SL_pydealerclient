# endcoding=utf-8

import struct


CMD_HEAD_LEN = 12

# 心跳包
CMD_KEEPALIVE = 0xAB0001


class PK_KeepAlive(object):
    def __init__(self):
        self.cmd = CMD_KEEPALIVE
        self.size = 12
        self.seq = 0

    def pack(self):
        return struct.pack('!3i', self.cmd, self.size, self.seq)


# 登录包
CMD_LOGIN = 0xAB0002
class PK_Login(object):
    def __init__(self):
        self.cmd = CMD_LOGIN
        self.size = 16
        self.seq = 0

    def pack(self, svrid):
        return struct.pack('!3i4s', self.cmd, self.size, self.seq, bytes(svrid, 'utf-8'))


# 登录回包
CMD_LOGIN_R = 0xBA0002
FMT_BODY_PK_LOGIN_R = '!i4s4s'

# 开始识别
CMD_START_PREDICT = 0xBA0003
FMT_BODY_PK_START_PREDICT = '!14sh'
#FMT_BODY_PK_START_PREDICT = '!14s'
# 结束识别
CMD_STOP_PREDICT = 0xBA0004
FMT_BODY_PK_STOP_PREDICT = '!14sh'
#FMT_BODY_PK_STOP_PREDICT = '!14s'
# 扫描结果
CMD_SCAN_RESULT = 0xBA0005
FMT_BODY_SCAN_RESULT = '!14s2h'

class ScanResult:
    def __init__(self, index, cardVal):
        self.index = index
        self.cardVal = cardVal

CMD_DISPATCH_INDEX = 0xBA0006
FMT_BODY_DISPATCH_INDEX = '!14sh'

# 保存最终结果
CMD_SAVE_RESULT = 0xBA0007
FMT_BODY_SAVE_RESULT = '!14s'

# 清理对比结果
CMD_CANCEL_RESULT = 0xBA0008
FMT_BODY_CANCEL_RESULT = '!14s'

# 标准预测
CMD_PREDICT_REF = 0xBA0009
FMT_BODY_PREDICT_REF = '!14s'

# 预测结果
CMD_PREDICT_RESULT = 0xAB0004
class PredictResult:
    def __init__(self, index, cardVal, confidence):
        self.index = index
        self.cardVal = cardVal
        self.confidence = confidence


