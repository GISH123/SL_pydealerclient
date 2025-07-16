# encoding=utf-8

import os
import datetime as d
import pandas as pd

class csvtool(object):
    def __init__(self, dir):
        self.dir = dir
        self.firstwrite = True
        if not os.path.exists(dir):
            os.mkdir(dir)

        date = self.curDate()
        self.curDir = dir + '/' + date
        if not os.path.exists(self.curDir):
            os.mkdir(self.curDir)

        self.filename = self.curDir + '/' + self.curFileName()
        self.file = open(self.filename, 'a+')

    def curDate(self):
        curDate = d.datetime.now().strftime('%Y-%m-%d')
        return curDate

    def curFileName(self):
        filename = (d.datetime.now()).strftime('%Y%m%d.csv')
        return filename

    def write(self, messagelist, isFinalResult):
        newDir = self.dir + '/' + self.curDate()
        if newDir != self.curDir:
            self.curDir = newDir
        if not os.path.exists(newDir):
             os.mkdir(newDir)
        if isFinalResult:
            newfile = self.curDir + '/' + 'finalresult_' + self.curFileName()
        else:
            newfile = self.curDir + '/' + self.curFileName()
        self.filename = newfile
        if self.firstwrite:
            # 20241115 增加header，直接寫死，實在沒興致再去refactor之前的old code，請去對應 scanresultsave.py的 saveFinaDeclareResultNoLock()
            column_names=["game","idx",'class_dealer', 'class_model','score', 'card_number', 'endid']
            messagelist.insert(0, column_names)
            self.firstwrite = False
        data_df = pd.DataFrame(messagelist)

        data_df.to_csv(self.filename, header=False, index=False,mode='a')

csvtooler = csvtool('./csv')
def tocsv(message, isFinalResult):
    csvtooler.write(message, isFinalResult)