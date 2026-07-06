# encoding=utf-8

import os
import sys
import datetime as d
import threading, time

# --- make console prints UTF-8 if possible (no behavior change if it fails) ---
try:
    sys.stdout.reconfigure(encoding="utf-8", errors="replace")
    sys.stderr.reconfigure(encoding="utf-8", errors="replace")
except Exception:
    pass

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
        # *** only change: force UTF-8 for the log file ***
        self.file = open(self.filename, 'a+', encoding='utf-8', errors='replace')

        # # 啟動日誌記錄線程（保留你的註解與行為）
        # self.thread = threading.Thread(target=self.run)
        # self.thread.start()
        # self.msgqueue = []
        # self.lock = threading.Lock()
        # self._stop_event = threading.Event()

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
            # 先關閉原來的文件
            if not self.file.closed:
                self.file.close()

            self.filename = newfile
            # *** only change: force UTF-8 for the new file too ***
            self.file = open(self.filename, 'a+', encoding='utf-8', errors='replace')

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
        s = '%s [%s][%s] %s' % (curTime, level, threadid, message)
        return s

    def post(self, message):
        '''
        :param message:
        :return:
        '''
        # 保留原本行為（直接寫檔）
        self.write(message)
        # self.lock.acquire()
        # self.msgqueue.append(message)
        # self.lock.release()

    def info(self, message):
        s = self.fmt_str('INFO', message)
        print(s)            # console print (now UTF-8 safe if reconfigure succeeded)
        s += '\n'
        self.post(s)

    def debug(self, message):
        s = self.fmt_str('DEBUG', message)
        print(s)
        s += '\n'
        self.post(s)

    def warning(self, message):
        s = self.fmt_str('WARNING', message)
        print(s)
        s += '\n'
        self.post(s)

    def error(self, message):
        s = self.fmt_str('ERR', message)
        print(s)
        s += '\n'
        self.post(s)

# 保留原有對外接口
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
