# encoding=utf-8

import threading
from cardlist import Cardlist_box
import time
import enum
import pylogger as logger
from twisted.internet.task import LoopingCall
from config import cfg

class DataManager(object):
	def __init__(self):
		'''
		初始化
		'''
		self.gmcode = ''
		self.gmtype = ''
		self.predictFlag = False
		self.lock = threading.Lock()
		self.mapcard = dict()
		'''
		mapcard = {1: Cardlist_box1, 2: Cardlist_box2, 3:Cardlist_box3, ...., 6: Cardlist_box6}, 1~6表index即六張牌框格
		'''
		self.isDirty = False
		self.lashCheckTimestamp = 0
		self.detecttimes = cfg.detecttimes
		self.curcardlist = [] # 紀錄目前第幾個index要預測
		self.imageSaver = None

	def setgametype(self, gmetype):
		self.gmtype = gmetype

	def getPredictFlag(self):
		'''
		获取预测标记
		:return:
		'''
		self.lock.acquire()
		predict = self.predictFlag
		self.lock.release()
		return predict

	def getGamecode(self):
		'''
		获取当前局号
		:return:
		'''
		self.lock.acquire()
		gmcode = self.gmcode
		self.lock.release()
		return gmcode

	# ==========================================================================================================================
	# 使其他Instance能使用datamanager去傳送資料使用，如dealerclient.py DataMgrInstance().register_senddata(self.sendPredictResult)
	def register_senddata(self, senddata):
		self.senddata = senddata
	def register_ImageSaver(self, imageSaver):
		self.imageSaver = imageSaver
	def notify_ImageSaver(self):
		if self.imageSaver:
			self.imageSaver.setSnapshotFlag()
	# ==========================================================================================================================
	# 取得當前最佳結果使用 - return 6個格子的list，每個格子有當前最佳預測結果
	# def getBestResultlist(self, gmcode, minCardCount):
	# 	self.lock.acquire()
	# 	if gmcode == self.gmcode and self.predictFlag:
	# 		resultlist = self.getBestResultNolock(minCardCount)
	# 	else:
	# 		resultlist = []
	# 	self.lock.release()
	# 	return resultlist

	# def getBestResultNolock(self, minCardCount):
	# 	resultlist = []
	# 	for value in self.mapcard.values():
	# 		best = value.bestcardEx(minCardCount)
	# 		if best is not None:
	# 			resultlist.append(best)
	# 	return resultlist

	# 取得當前格子最佳預測結果使用 # 20241211 目前沒使用到
	# def getBestIndexResult(self, cardindex, minCardCount):
	# 	self.lock.acquire()
	# 	return self.getBestIndexResultNolock(cardindex, minCardCount)
	# 	self.lock.release()

	# def getBestIndexResultNolock(self, cardindex, minCardCount):
	# 	value = self.mapcard.get(cardindex)
	# 	if value is not None:
	# 		best = value.bestcardEx(minCardCount)
	# 		return best

	# ==========================================================================================================================

	def addResultlist(self, gmcode, resultlist):
		if len(resultlist) > 0:
			self.lock.acquire()
			self.addResultlistNoLock(gmcode, resultlist)
			self.lock.release()
		else:
			logger.error('addResultlist invalid, len=0, gmcode=%s' % (gmcode))

	def addResultlistNoLock(self, gmcode, resultlist):
		if gmcode == self.gmcode and self.predictFlag:
			self.isDirty = True
			for result in resultlist:
				# 每次在这里检查是否该发，如果发了就在这里退出
				self.addCardNolock(result.index, result)
				logger.info('addResultlist, gmcode=%s, index=%d, value=%d' % (gmcode, result.index, result.dealer_classid))
				cardlist_box = self.mapcard.get(result.index)
				# 如果大于等于cfg.detecttimes(以前5)张牌了就判断是否可发
				if cardlist_box is not None:
					if cardlist_box.CardNum >= cfg.detecttimes:
						logger.info('addResultlist, gmcode=%s, [%d]cardlist.CardNum=%d' % (gmcode, result.index, cardlist_box.CardNum))
						self.check_resultEx(result.index, cardlist_box.CardNum)

	def addCardNolock(self, index, card):
		cardlist_box = self.mapcard.get(index)
		if cardlist_box is not None:
			# cardlist.addcard(card)
			cardlist_box.addcardEx(card)
		else:
			cardlist_box = Cardlist_box()
			# cardlist.addcard(card)
			cardlist_box.addcardEx(card)
			self.mapcard[index] = cardlist_box

	def clearCardNolock(self):
		self.mapcard.clear()

	# ==========================================================================================================================
	def check_resultEx(self, index, count):
		'''
		检查结果
		:param :
		:return:
		'''
		resultlist = self.getsendResultNolock(index, count)
		if len(resultlist) > 0 and self.senddata:
			logger.info('check_resultEx, gmcode=%s, resultsize:%d' % (self.gmcode, len(resultlist)))
			# logger.info(f'------------------------printing resultlist cards before senddata-----------------------------------------------')
			# for i in resultlist:
			# 	for (key,resultValue) in i:
			# 		logger.info(f'{i}')
			# logger.info(f'---------------------------------printing resultlist finished-----------------------------------------------')
			self.senddata(resultlist)

	def getsendResultNolock(self, cardindex, count):
		'''
		获取发送列表
		:param :
		:return:
		'''
		resultlist = []
		cardlist_box = self.mapcard.get(cardindex)
		if cardlist_box is not None:
			if count >= cfg.detecttimes and cardlist_box.getIsdispatch() == False: # 當index牌框超過detectimes且未發牌時，進入選牌邏輯
				result = cardlist_box.bestcardEx(minCardCount = 1) # 20241225 align to cpp CardList::getbestcard()
			# 20241225 因目前cpp版本以及現場detectimes=5，則代表以下code完全用不到，先放在comment代表一個很久之前曾經用過的紀錄
			# else:
			# 	result = cardlist_box.getSendResultList(cfg.detecttimes)
				
			# 如果有挑出卡牌
			if result is not None:
				resultlist.append(result)
				cardlist_box.setIsDispatch(True)
				logger.info(f'getsendResultNolock 回傳選出來的預測結果 dealer_classid = {result.dealer_classid} , gmcode = {self.gmcode} ,count= {count}')
				return resultlist
			
		return resultlist # return empty list if not matched with forementioned rules

	# ==========================================================================================================================

	def getIsDispatch(self, gmcode, index):
		'''
		是否已经发牌
		:param :
		:return:
		'''
		isdispatch = False
		self.lock.acquire()
		if self.gmcode == gmcode:
			isdispatch = self.getIsDispatchNolock(index)
		self.lock.release()

		return isdispatch

	def getIsDispatchNolock(self, index):
		'''
		是否已经发牌
		:param :
		:return:
		'''
		if index in self.mapcard:
			isDispatch = self.mapcard[index].getIsdispatch()
			return isDispatch
		return False

	# ==========================================================================================================================

	def startPredict(self, gmcode, gmstate):
		'''
		开始预测
		:param gmcode:
		:return:
		'''
		logger.info('datamanager start predict, gmcode=%s, cardcount=%d, gmstate=%d' % (
		self.gmcode, len(self.mapcard), gmstate))
		self.lock.acquire()
		self.gmcode = gmcode
		oldFlag = self.predictFlag
		self.predictFlag = True
		self.gmstate = gmstate
		if oldFlag != self.predictFlag:
			# if self.gmtype == 'NN' or self.gmtype == 'BAC':
			if gmstate == 0:
				self.clearCardNolock()
				self.curcardlist.clear()
			# else:
			# self.clearCardNolock()
		self.lock.release()

	def stopPredict(self, gmcode, gmstate):
		'''
		停止预测
		:param gmcode:
		:return:
		'''
		logger.info(
			'datamanager stopPredict, gmcode=%s, cardcount=%d, gmstate=%d' % (self.gmcode, len(self.mapcard), gmstate))
		self.lock.acquire()

		if gmstate == 0:
			self.clearCardNolock()
			self.curcardlist.clear()
			self.gmcode = ''
		self.predictFlag = False
		self.lock.release()

	# ==========================================================================================================================

	def ReScan(self,gmcode):
		if self.gmtype == 'DT':
			self.curcardlist.clear()
			self.curcardlist.append(1)
			self.curcardlist.append(2)
		elif self.gmtype == 'BAC':
			self.curcardlist.clear()
			counter = 1
			while counter <= 6:
				self.curcardlist.append(counter)
				counter += 1
		elif self.gmtype == 'NN':
			self.curcardlist.clear()
			counter = 1
			while counter <= 20:
				self.curcardlist.append(counter)
				counter += 1
		elif self.gmtype == 'VNN':
			self.curcardlist.clear()
			counter = 1
			while counter <= 10:
				self.curcardlist.append(counter)
				counter += 1
		elif self.gmtype == 'VBR':
			self.curcardlist.clear()
			counter = 1
			while counter <= 6:
				self.curcardlist.append(counter)
				counter += 1
		elif self.gmtype == 'DZ':
			self.curcardlist.clear()
			counter = 1
			while counter <= 9:
				self.curcardlist.append(counter)
				counter += 1
		elif self.gmtype == 'TEB':
			self.curcardlist.clear()
			counter = 1
			while counter <= 8:
				self.curcardlist.append(counter)
				counter += 1
		else:
			logger.error('invalid gmtype %s' % (self.gmtype))

	# ==========================================================================================================================

	def isincurCardList(self, gmcode, cardindex):
		'''
		牛牛判断是否在当前发牌的列表
		:return:
		'''
		isincurlist = False
		self.lock.acquire()
		if self.gmcode == gmcode:
			isincurlist = self.isincurCardListNolock(cardindex)
		self.lock.release()
		return isincurlist

	def isincurCardListNolock(self, cardindex):
		if cardindex in self.curcardlist:
			return True
		else:
			return False
	
	# ==========================================================================================================================

	def dispatchCard(self, gmcode, index, scan_full_list=False):
		self.lock.acquire()
		self.dispatchCardNoLock(gmcode, index, scan_full_list)
		self.lock.release()

	def dispatchCardNoLock(self, gmcode, index, scan_full_list):
		logger.info('dispatchCardNoLock, gmcode=%s, gmtype=%s, self.curcardlist=%d, index=%d' % (self.gmcode, self.gmtype, len(self.curcardlist), index))
		if self.gmtype == 'DT':
			self.curcardlist.clear()
			self.curcardlist.append(1)
			self.curcardlist.append(2)
		elif self.gmtype == 'BAC':
			newlist = self.curcardlist
			for cardindex in newlist:
				if self.getIsDispatchNolock(cardindex) == True:
					self.curcardlist.remove(cardindex)

			# # 20241114 refactor: 發什麼index就去預測對應的位置，不要提前預測後面的index，之前那個寫法不知道為什麼要去預測後面index
			# if index == 1:
			# 	self.curcardlist.clear()
			# 	self.curcardlist.append(1)
			# elif index >= 2 and index <= 6:
			# 	self.curcardlist.append(index)

			# 20241127 因牌速問題，，設定一個參數scan_full_list,如果True則發第一張牌就先掃描全部
			if scan_full_list and index == 1:
				for i in range(2,7):
					self.curcardlist.append(i)
			
			# 20250407 PH BAC 因應BAC一次發兩張牌，回歸原本BAC curcardlist放法
			if index == 1:
				self.curcardlist.clear()
				self.curcardlist.append(1)
				self.curcardlist.append(3)
			if index >= 2 and index <= 4:
				self.curcardlist.append(2)
				self.curcardlist.append(3)
				self.curcardlist.append(4)
			elif index == 5:
				#self.curcardlist.clear()
				#试验下不那么着急把庄家的第2和第4个位置停止扫描
				#self.curcardlist.append(2)
				#self.curcardlist.append(4)
				self.curcardlist.append(5)
			elif index == 6:
				#self.curcardlist.clear()
				# 试验下不那么着急把庄家的第2和第4个位置停止扫描
				#self.curcardlist.append(2)
				#self.curcardlist.append(4)
				self.curcardlist.append(6)

		# 20241144 其他遊戲的邏輯，目前只有BAC就先關掉吧
		# elif self.gmtype == 'NN' or self.gmtype == 'VNN':
		# 	newlist = self.curcardlist
		# 	for cardindex in newlist:
		# 		if self.getIsDispatchNolock(cardindex) == True:
		# 			self.curcardlist.remove(cardindex)
		# 	if index == 0:
		# 		self.curcardlist.clear()
		# 		self.curcardlist.append(0)
		# 	elif (index >= 1 and index <= 5):
		# 		#self.curcardlist.clear()
		# 		self.curcardlist.append(1)
		# 		self.curcardlist.append(2)
		# 		self.curcardlist.append(3)
		# 		self.curcardlist.append(4)
		# 		self.curcardlist.append(5)
		# 	elif (index >= 6 and index <= 10):
		# 		#self.curcardlist.clear()
		# 		self.curcardlist.append(6)
		# 		self.curcardlist.append(7)
		# 		self.curcardlist.append(8)
		# 		self.curcardlist.append(9)
		# 		self.curcardlist.append(10)
		# 	elif (index >= 11 and index <= 15):
		# 		#self.curcardlist.clear()
		# 		self.curcardlist.append(11)
		# 		self.curcardlist.append(12)
		# 		self.curcardlist.append(13)
		# 		self.curcardlist.append(14)
		# 		self.curcardlist.append(15)
		# 	elif (index >= 16 and index <= 20):
		# 		#self.curcardlist.clear()
		# 		self.curcardlist.append(16)
		# 		self.curcardlist.append(17)
		# 		self.curcardlist.append(18)
		# 		self.curcardlist.append(19)
		# 		self.curcardlist.append(20)
		# elif self.gmtype == 'VBR':
		# 	newlist = self.curcardlist
		# 	for cardindex in newlist:
		# 		if self.getIsDispatchNolock(cardindex) == True:
		# 			self.curcardlist.remove(cardindex)
		# 	if (index >= 1 and index <= 3):
		# 		# self.curcardlist.clear()
		# 		self.curcardlist.append(1)
		# 		self.curcardlist.append(2)
		# 		self.curcardlist.append(3)
		# 	elif (index >= 4 and index <= 6):
		# 		# self.curcardlist.clear()
		# 		self.curcardlist.append(4)
		# 		self.curcardlist.append(5)
		# 		self.curcardlist.append(6)
		# 	else:
		# 		logger.error('invalid index %d, gmcode=%s' % (index, gmcode))
		# elif self.gmtype == 'DZ':
		# 	newlist = self.curcardlist
		# 	for cardindex in newlist:
		# 		if self.getIsDispatchNolock(cardindex) == True:
		# 			self.curcardlist.remove(cardindex)
		# 	if (index >= 1 and index <= 2):
		# 		# self.curcardlist.clear()
		# 		self.curcardlist.append(1)
		# 		self.curcardlist.append(2)
		# 	elif (index >= 3 and index <= 4):
		# 		# self.curcardlist.clear()
		# 		self.curcardlist.append(3)
		# 		self.curcardlist.append(4)
		# 	elif (index >= 5 and index <= 7):
		# 		# self.curcardlist.clear()
		# 		self.curcardlist.append(5)
		# 		self.curcardlist.append(6)
		# 		self.curcardlist.append(7)
		# 	elif (index >= 8 and index <= 9):
		# 		# self.curcardlist.clear()
		# 		self.curcardlist.append(8)
		# 		self.curcardlist.append(9)
		# 	else:
		# 		logger.error('invalid index %d, gmcode=%s' % (index, gmcode))
		# elif self.gmtype == 'TEB':
		# 	newlist = self.curcardlist
		# 	for cardindex in newlist:
		# 		if self.getIsDispatchNolock(cardindex) == True:
		# 			self.curcardlist.remove(cardindex)
		# 	if (index >= 1 and index <= 2):
		# 		# self.curcardlist.clear()
		# 		self.curcardlist.append(1)
		# 		self.curcardlist.append(2)
		# 	elif (index >= 3 and index <= 4):
		# 		# self.curcardlist.clear()
		# 		self.curcardlist.append(3)
		# 		self.curcardlist.append(4)
		# 	elif (index >= 5 and index <= 6):
		# 		# self.curcardlist.clear()
		# 		self.curcardlist.append(5)
		# 		self.curcardlist.append(6)
		# 	elif (index >= 7 and index <= 8):
		# 		# self.curcardlist.clear()
		# 		self.curcardlist.append(8)
		# 		self.curcardlist.append(7)
		# 	else:
		# 		logger.error('invalid index %d, gmcode=%s' % (index, gmcode))
		# else:
		# 	logger.error('invalid gmtype %s' % (self.gmtype))

dataMgr = DataManager()

def DataMgrInstance():
	return dataMgr


