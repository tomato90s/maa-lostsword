import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.daily_actions import ShopFreeGift

class GiftReplay(ShopFreeGift):
    def __init__(self, sold=False, dropped_open=False, receipt=True):
        super().__init__()
        self.clock, self.deadline = 0, 1000
        self.page, self.sold = "shop", sold
        self.dropped_open, self.receipt = dropped_open, receipt
        self.opens, self.commits, self.reward = 0, 0, False
        self.disabled = {}
        self.context = NS(tasker=NS(stopping=False), override_pipeline=self.disabled.update)
    def capture(self): self.check()
    def pause(self, seconds=.4): self.clock += seconds
    def log(self, message): pass
    def find(self, pattern, roi=None):
        values = []
        if self.page == "shop":
            if roi == (65,12,100,55): values = ["商店"]
            if roi == (340,140,230,55): values = ["每日免费礼包"]
            if roi == (315,195,265,215) and self.sold: values = ["售罄"]
            if roi == (315,360,260,60): values = ["免费"]
            if roi == (350,75,135,55): values = ["商品"]
        if self.page == "popup":
            if roi == (540,75,210,60): values = ["购买商品"]
            if roi == (270,480,260,65): values = ["每日免费礼包"]
            if roi == (500,580,280,65): values = ["免费"]
            if roi == (250,150,730,480) and self.sold: values = ["已领取"]
        return next((NS(text=text,roi=roi) for text in values if re.search(pattern,text)),None)
    def ocr(self, pattern, roi, **kwargs):
        return [NS(text="每日可购买次数：1/1" if self.sold else "每日可购买次数：0/1")]
    def click_row(self, row, delay=.5):
        if row.roi == (315,360,260,60):
            self.opens += 1
            if self.opens > int(self.dropped_open): self.page = "popup"
        elif self.page == "popup" and row.text == "免费":
            self.commits += 1
            if self.receipt: self.page = "reward"
        else:
            raise AssertionError("Unexpected card or paid control")
        self.pause(delay)
    def close_reward(self):
        if self.page == "reward":
            self.page, self.sold, self.reward = "popup", True, True
            return True
        return False
    def click(self,x,y,delay=.5):
        assert self.page == "popup" and self.sold and (x,y) == (1018,103)
        self.page = "shop"

class FreeGiftTests(unittest.TestCase):
    def run_gift(self, model):
        with patch("agent.daily_actions.time.monotonic",lambda:model.clock):
            return model.execute()
    def test_missed_open_can_retry_without_repeating_purchase(self):
        model = GiftReplay(dropped_open=True)
        self.assertTrue(self.run_gift(model))
        self.assertEqual((model.opens,model.commits,model.reward),(2,1,True))
        self.assertFalse(model.disabled["商店-商品"]["enabled"])
    def test_sold_out_card_skips_every_purchase(self):
        model = GiftReplay(sold=True)
        self.assertTrue(self.run_gift(model))
        self.assertEqual((model.opens,model.commits),(0,0))
    def test_unknown_purchase_receipt_is_never_resubmitted(self):
        model = GiftReplay(receipt=False)
        with self.assertRaisesRegex(RuntimeError,"结果未确认"):
            self.run_gift(model)
        self.assertEqual(model.commits,1)

if __name__ == "__main__": unittest.main()
