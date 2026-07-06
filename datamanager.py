# encoding=utf-8

import threading
from cardlist import Cardlist_box
import time
import enum
import pylogger as logger
from twisted.internet.task import LoopingCall
from config import cfg
from collections import defaultdict

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
		# ---- latency test (gmtype == 'lattest') ----
		# In 3-class latency mode: 0=cardback, 1=card, 2=empty.
		# We must NOT mark index as dispatched/done when best result is cardback/empty.
		# Also avoid spamming the same transient state repeatedly.
		self.lattest_last_sent_cls = {}
		# ---- lattest multi-dispatch support ----
		# Dispatch can be sent multiple times within a round. Each accepted dispatch starts a new
		# "dispatch-cycle" for that index.
		# - Ignore dispatch if index is still detecting (double-click / too fast dispatch).
		# - Cardback (cls==0) is treated as a normal prediction result and MUST complete the cycle.
		#   (Round ends only by stopPredict, NOT by cardback.)
		self.lattest_dispatch_in_progress = set()          # {index}
		self.lattest_dispatch_cycle_id = defaultdict(int)  # index -> cycle_id (starts at 0, first dispatch => 1)

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
				# logger.info('addResultlist, gmcode=%s, index=%d, value=%d' % (gmcode, result.index, result.dealer_classid))
				cardlist_box = self.mapcard.get(result.index)
				# 如果大于等于cfg.detecttimes(以前5)张牌了就判断是否可发
				if cardlist_box is not None:
					if cardlist_box.CardNum >= cfg.detecttimes:
						# logger.info('addResultlist, gmcode=%s, [%d]cardlist.CardNum=%d' % (gmcode, result.index, cardlist_box.CardNum))
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
		self.lattest_last_sent_cls.clear()
		# lattest multi-dispatch state
		self.lattest_dispatch_in_progress.clear()
		self.lattest_dispatch_cycle_id.clear()

	def get_lattest_dispatch_cycle_id(self, index: int) -> int:
		"""Return current dispatch-cycle id for the given index (lattest only).
		Cycle id is incremented when a dispatch is accepted. If no dispatch has happened yet, returns 0.
		"""
		self.lock.acquire()
		try:
			return int(self.lattest_dispatch_cycle_id.get(int(index), 0))
		finally:
			self.lock.release()

	def _ensure_box_and_set_dispatch(self, index: int, is_dispatch: bool) -> None:
		"""Internal helper: ensure mapcard[index] exists and set its dispatch flag."""
		idx = int(index)
		box = self.mapcard.get(idx)
		if box is None:
			box = Cardlist_box()
			self.mapcard[idx] = box
		box.setIsDispatch(bool(is_dispatch))

	def lattest_mark_cycle_done_nolock(self, index: int) -> None:
		"""Mark an index cycle as done (dispatch=true) and allow next dispatch."""
		idx = int(index)
		self._ensure_box_and_set_dispatch(idx, True)
		self.lattest_dispatch_in_progress.discard(idx)

	def lattest_mark_cycle_done(self, gmcode, index: int) -> bool:
		"""Thread-safe wrapper used by VideoManager (cardback path).

		Returns True if it marked the CURRENT round's index as dispatched; False otherwise.
		"""
		idx = int(index)
		self.lock.acquire()
		try:
			if gmcode != self.gmcode or not self.predictFlag:
				return False
			self.lattest_mark_cycle_done_nolock(idx)
			return True
		finally:
			self.lock.release()

	# ==========================================================================================================================
	def check_resultEx(self, index, count):
		'''
		检查结果
		:param :
		:return:
		'''
		resultlist = self.getsendResultNolock(index, count)
		if len(resultlist) > 0 and self.senddata:
			# logger.info('check_resultEx, gmcode=%s, resultsize:%d' % (self.gmcode, len(resultlist)))
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

				# lattest multi-dispatch:
				# - cls==0 (cardback) is treated as a normal prediction result (cycle completes)
				# - cls==2 (empty) remains VIEW-ONLY and must NOT complete the cycle (avoid accidental stop)
				# Also avoid spamming empty repeatedly.
				if self.gmtype == 'lattest':
					try:
						_cls = int(getattr(result, 'dealer_classid', getattr(result, 'classid', -999)))
					except Exception:
						_cls = getattr(result, 'dealer_classid', getattr(result, 'classid', None))
					if _cls == 2:
						last_cls = self.lattest_last_sent_cls.get(cardindex)
						if last_cls == _cls:
							return []
						self.lattest_last_sent_cls[cardindex] = _cls
						logger.info(f"[LATTEST_TRANSIENT] cardindex={cardindex} cls={_cls} (no dispatch)")
						return resultlist
					# record last sent cls for debugging only
					self.lattest_last_sent_cls[cardindex] = _cls

				cardlist_box.setIsDispatch(True)
				if self.gmtype == 'lattest':
					# cycle completed -> allow next dispatch
					self.lattest_dispatch_in_progress.discard(int(cardindex))

				first = (resultlist[0] if hasattr(resultlist,'__len__') and len(resultlist)>0 else None)
				cls = (getattr(first,'dealer_classid', getattr(first,'classid', None)) if first is not None else None)
				logger.info(f"getSendResultNolock selected: first_cls={cls}, count={len(resultlist) if hasattr(resultlist,'__len__') else 1}")

				logger.info(
					"[RESULT_READY] "
					f"count={len(resultlist) if hasattr(resultlist, '__len__') else 1} "
					f"sample={(str(resultlist[0]) if hasattr(resultlist, '__len__') and len(resultlist)>0 else str(resultlist))}"
				)

				# ---- 新增：先通知 HTTP 等候端（與是否能連上 Dealer 無關）----
				try:
					from predict_waiter import notify_result as _notify_http_waiter
				except Exception:
					_notify_http_waiter = None

				if _notify_http_waiter is not None:
					try:
						# 優先用 self 上的 gmcode；若本地變數有 gmcode 也可直接用它
						_gm_raw = getattr(self, "gamecode", None) or getattr(self, "gmcode", None)
						if _gm_raw is None:
							_gm_raw = gmcode  # 若你的函式本來就有 gmcode 變數
						_gm = _gm_raw.decode("ascii", "ignore") if isinstance(_gm_raw, (bytes, bytearray)) else str(_gm_raw)
						_gm = _gm.replace("\x00", "").strip()
						_notify_http_waiter(_gm, resultlist)
					except Exception as _e:
						logger.error("predict_waiter notify failed: %s", _e)
				# ---- 新增結束 ----

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
		logger.info('datamanager start predict, gmcode=%s, cardcount=%d, gmstate=%d' % (self.gmcode, len(self.mapcard), gmstate))
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
		logger.info('datamanager stopPredict, gmcode=%s, cardcount=%d, gmstate=%d' % (self.gmcode, len(self.mapcard), gmstate))
		self.lock.acquire()

		# Latency mode: stopPredict should always end the current round state.
		if self.gmtype == 'lattest':
			self.clearCardNolock()
			self.curcardlist.clear()
			self.gmcode = ''
			self.predictFlag = False
			self.lock.release()
			return

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
		# logger.info('dispatchCardNoLock, gmcode=%s, gmtype=%s, self.curcardlist=%d, index=%d' % (self.gmcode, self.gmtype, len(self.curcardlist), index))
		if self.gmtype == 'DT':
			# self.curcardlist.clear()
			# self.curcardlist.append(1)
			# self.curcardlist.append(2)
			# 20250915 偵測發什麼index就抓什麼index
			if index == 1:
				self.curcardlist.clear()
				self.curcardlist.append(1)
			elif index >= 2 and index <= 99:
				self.curcardlist.append(index)
		# 20251106 add lattest to test latency
		elif self.gmtype == 'lattest':
			# Latency mode: one ImageDetector instance per table.
			# We only scan index=1, and allow MULTIPLE dispatches within the same round.
			# If dispatch arrives while the previous dispatch-cycle is still detecting, ignore it.
			try:
				idx = int(index)
			except Exception:
				idx = 1
			if idx != 1:
				logger.info(f"[LATTEST] ignore dispatch index={idx} (only support index=1)")
				return
			if idx in self.lattest_dispatch_in_progress and not self.getIsDispatchNolock(idx):
				logger.info(f"[LATTEST] ignore dispatch index={idx} (still detecting)")
				return

			# accept dispatch -> new dispatch-cycle
			self.lattest_dispatch_in_progress.add(idx)
			self.lattest_dispatch_cycle_id[idx] = int(self.lattest_dispatch_cycle_id.get(idx, 0)) + 1
			self.lattest_last_sent_cls.pop(idx, None)

			# reset this index's aggregation state so each dispatch-cycle is independent
			self.mapcard[idx] = Cardlist_box()
			self.mapcard[idx].setIsDispatch(False)

			self.curcardlist.clear()
			self.curcardlist.append(1)
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
				self.curcardlist.append(5)
			elif index == 6:
				self.curcardlist.append(6)

dataMgr = DataManager()

def DataMgrInstance():
	return dataMgr
