# encoding=utf-8

# 检查是否是花色
def is_suites(classid):
    if classid >= 14 and classid <= 17:
        return True
    return False


# 检查是否是牌值
def is_cardVal(classid):
    if classid >= 1 and classid <= 13:
        return True
    return False

# 定义预测结果的结构
class PredictResult:
    def __init__(self):
        self.init = False

    # def setvalue(self, row, col, classid, score, box):
    #     self.init = True
    #     self.row = row
    #     self.col = col
    #     self.classid = int(classid)
    #     self.score = score
    #     self.box = box

    def setvalue(self, classid, score, box):
        self.init = True
        self.classid = int(classid)
        self.score = score
        self.box = box

    def to_str(self):
        if not self.init:
            return 'unknown'
        if is_suites(self.classid):
            if self.classid == 14:
                return 'mei'
            elif self.classid == 15:
                return 'fang'
            elif self.classid == 16:
                return 'hong'
            elif self.classid == 17:
                return 'hei'
            else:
                return 'invalid'
        elif is_cardVal(self.classid):
            if self.classid == 1:
                return 'A'
            if self.classid == 11:
                return 'J'
            elif self.classid == 12:
                return 'Q'
            elif self.classid == 13:
                return 'K'
            return str(self.classid)
        return 'invalid'
