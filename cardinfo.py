#encoding=utf-8

import pylogger as logger

SUITES_CLUB = 14  # 梅花
SUITES_DIAMOND = 15 # 方块
SUITES_HAEART = 16 # 红桃
SUITES_SPADE = 17 # 红桃

class CardInfo(object):
    def __init__(self, index, dealer_classid, predict_classid, card_point, score):
        self.index = int(index)
        # self.cardVal = int(cardVal)
        self.dealer_classid = int(dealer_classid)
        self.predict_classid = predict_classid
        self.card_point = card_point
        self.score = float(score)

    def setAnchor(self, pos, xmin, ymin, width, height, desc):
        self.pos = pos
        self.xmin = xmin
        self.ymin = ymin
        self.width = width
        self.height= height
        self.desc = desc

def GetCardVal(suites, val):
    cardVal = 0
    if SUITES_CLUB == suites: # 梅花
        cardVal = 0
    elif SUITES_DIAMOND == suites: # 方块
        cardVal = 16
    elif SUITES_HAEART == suites: # 红桃
        cardVal = 48
    elif SUITES_SPADE == suites: # 黑桃
        cardVal = 32
    else:
        logger.error('invalid suites, %d' %(suites))
        return -1

    if val > 0 and val <= 13:
        return cardVal + val

    logger.error('invalid cardval, %d' % (val))
    return  -1