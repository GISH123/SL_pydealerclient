#encoding=utf-8

from cardinfo import CardInfo
import pylogger as logger
# 每个位置的牌
class Cardlist_box(object):
    def __init__(self):
        '''
        一個cardlist_box即為一個牌框，裡面存放一個牌框的資訊，如目前已預測的牌組(cardInfos)、以(indexcardmap)
        '''
        self.cardlist = []
        self.max_count = 10
        #每个位置可能识别成多种牌,根据牌值为key,card为value
        self.indexcardmap = {}
        '''
        indexcardmap =
        {
        // dealer_classid : cardlist([cardinfo1, cardinfo2, cardinfo3]) ，我修後的code這邊cardinfo會照預測信心分數排序 由大至小//
        36 : cardlist1 
        26 : cardlist2,
        ...
        }
        '''
        self.isDispatch = False  # 记录该区域的牌是否已发,发了就不会加牌和识别了
        self.CardNum = 0

    def addcardEx(self, card):
        '''
         将每个位置的牌按索引分类添加至列表，最多保留10张
         :param card:
         :return:
         '''
        cardlist = self.indexcardmap.get(card.dealer_classid)
        if cardlist is not None:
            cardlist.append(card)
            # sorted(cardlist, key=lambda card: card.score, reverse=True)
            # 20241125 原本的sorted根本不會改變cardlist，不知道為什麼那樣寫，反正我先改為以下code
            cardlist.sort(key=lambda card: card.score, reverse=True)

            #logger.info('addcardEx key=%d, len=%d' % (card.cardVal, len(cardlist)))
        else:
            cardlist =[]
            cardlist.append(card)
            self.indexcardmap[card.dealer_classid] = cardlist
            # logger.info('first tiem key=%d, len=%d' %(card.cardVal,len(cardlist)))
        self.CardNum = self.CardNum + 1

    def bestcardEx(self, minCardCount):
        # 20241223 implement jieqi getbestcard logic, cpp CardList::getbestcard()
        '''
        Example :
        舉一個最極端例子，當nScore加總剛好重疊
        indexcardmap(cpp:m_uMap) = {
            {10, [CardInfo(1, 10, 0.9), CardInfo(2, 10, 0.8)]},
            {12, [CardInfo(3, 12, 0.85)]},
            {15, [CardInfo(4, 15, 0.95), CardInfo(5, 15, 0.75)]}
        };

        由上可知10跟15的nScore都為1.7，因此當執行到15 group的時候，會覆蓋掉10 group
        cardValMap(cpp:mymap): {1.7: CardInfo(1, 10, 0.9), 0.85: CardInfo(3, 12, 0.85)}    =>     cardValMap(cpp:mymap): {1.7: CardInfo(4, 15, 0.95), 0.85: CardInfo(3, 12, 0.85)}  
        目前就先這樣處理，畢竟實務上nScore會相等幾乎不可能會發生

        cardValMap(cpp:mymap): {1.7: CardInfo(4, 15, 0.95), 0.85: CardInfo(3, 12, 0.85)}

        Output : 
        CardInfo(4, 15, 0.95)  ( from cardValMap[index] )

        '''

        #保存牌值类的分数的字典
        if len(self.indexcardmap) < minCardCount: return None

        cardValMap = {}
        for (cardVal, cardList) in self.indexcardmap.items():
            nScore = 0
            for card in cardList:
                nScore += card.score
            cardValMap[nScore] = cardList[0]
        # 20241125 python版的cardValMap排序寫法應是python2的寫法?反正應該就是要排序，我改為以下code
        cardValMap = dict(sorted(cardValMap.items(), key=lambda item: item[0], reverse=True)) # => 以總分作排序
        index = next(iter(cardValMap))
        # 註記 : 這邊相較於Jieqi的版本，我沒有implement挑選最靠近平均分數的邏輯，因為基本上回傳只要是該牌組(index group)的任何一張牌就能代表該牌的牌值跟花色，
        # 所以原本挑一個最靠近平均分數，甚或是挑一個最高分的牌，意義不大
        # 這也是參考舊版pydealerclient bestcardex的寫法 看起來比較簡潔也能做到同樣的結果.

        for (cardVal, cardList) in self.indexcardmap.items():
            logger.info(f'indexcardmap(m_uMap) key={cardVal}, value (a vector of cardlists) len={len(cardList)}')
        for (cardVal, a_card) in cardValMap.items():
            logger.info(f'cardValMap(mymap) key={cardVal}, value (cardinfo->cardvalue): {a_card.dealer_classid}')

        return cardValMap[index]

    def getIsdispatch(self):
        '''
        是否已发牌
        '''
        return self.isDispatch

    # def getSendResultList(self):
    #     for (key,resultValue) in self.indexcardmap.items():
    #         if len(resultValue) >=5:
    #             # 获取到了发送列表就该发牌，就置标记为已发牌
    #             #self.isDispatch = True
    #             logger.info('getSendResultList len(resultValue)=%d, self.isDispatch=%d' %(len(resultValue),self.isDispatch))
    #             return resultValue[0]
    #     return None


    def setIsDispatch(self, isdispatch):
        self.isDispatch = isdispatch




