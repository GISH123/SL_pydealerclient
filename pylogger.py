# encoding=utf-8

import os
import datetime as d
import threading, time

class PyLogger(object):
    def __init__(self, dir):
        self.dir = dir
        if not os.path.exists(dir):
            os.mkdir(dir)

        date = self.curDate()
        self.curDir = dir + '/' + date
        if not os.path.exists(self.curDir):
            os.mkdir(self.curDir)

        self.filename = self.curDir + '/' + self.curFileName()
        self.file = open(self.filename, 'a+')

        # 启动日志记录线程
        #self.thread = threading.Thread(target=self.run)
        #self.msgqueue = []
        #self.thread.start()
        #self.lock = threading.Lock()
        #self._stop_event = threading.Event()

    def stop(self):
        self.file.close()

    def curDate(self):
        curDate = d.datetime.now().strftime('%Y-%m-%d')
        return curDate

    def curFileName(self):
        filename = d.datetime.now().strftime('%Y%m%d%H.log')
        return filename

    def write(self, message):
        newDir = self.dir + '/' + self.curDate()
        if newDir != self.curDir:
            self.curDir = newDir
            if not os.path.exists(newDir):
                os.mkdir(newDir)

        newfile = self.curDir + '/' + self.curFileName()
        if self.filename != newfile:
            # 先关闭原来的文件
            if not self.file.closed:
                self.file.close()

            self.filename = newfile
            self.file = open(self.filename, 'a+')

        if not self.file.closed and self.file.writable():
            self.file.write(message)
            self.file.flush()

    def run(self):
        while True:
            time.sleep(1)
            self.lock.acquire()
            tmpdata = self.msgqueue
            for data in tmpdata:
                self.write(data)
            self.msgqueue = []
            self.lock.release()


    def fmt_str(self, level, message):
        threadid = threading.current_thread().name
        curTime = d.datetime.now().strftime('%Y-%m-%d %H:%M:%S.%f')[:-3]
        str = '%s [%s][%s] %s' % (curTime, level, threadid, message)
        return str

    def post(self, message):
        '''
        将数据添加至队列
        :param message:
        :return:
        '''
        self.write(message)
        #self.lock.acquire()
        #self.msgqueue.append(message)
        #self.lock.release()

    def info(self, message):
        str = self.fmt_str('INFO', message)
        print(str)
        str += '\n'
        self.post(str)

    def debug(self, message):
        str = self.fmt_str('DEBUG', message)
        print(str)
        str += '\n'
        self.post(str)

    def warning(self, message):
        str = self.fmt_str('WARNING', message)
        print(str)
        str += '\n'
        self.post(str)

    def error(self, message):
        str = self.fmt_str('ERR', message)
        print(str)
        str += '\n'
        self.post(str)

log = PyLogger('./log')

def info(message):
    log.info(message)

def debug(message):
    log.debug(message)

def warning(message):
    log.warning(message)

def error(message):
    log.error(message)

def stop():
    log.stop()