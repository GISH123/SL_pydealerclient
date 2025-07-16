# encoding=utf-8
from twisted.internet import reactor
from twisted.internet.protocol import Factory, Protocol
import pylogger as logger
import win32api
import win32con
class SingleInstanceStart(Protocol):
    def __init__(self, listenport):
        self.listenport = listenport
        self.factory = Factory()

    def isStarted(self):
        try:
            num = reactor.listenTCP(self.listenport, self.factory)
        except:
            win32api.MessageBox(0, "detect already started", "warning", win32con.MB_ICONWARNING)
            exit(-1)
        return num.connected

singleInstanceStart=SingleInstanceStart(15826)
singleInstanceStart.isStarted()
