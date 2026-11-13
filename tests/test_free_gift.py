import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.daily_actions import ShopFreeGift

class GiftReplay(ShopFreeGift):
    def __init__(self, sold=False, dropped_open=False, receipt=True, periods=None, paid=False):
        super().__init__()
        self.clock, self.deadline = 0, 1000
        self.page, self.sold = "shop", sold
        self.dropped_open, self.receipt = dropped_open, receipt
        self.opens, self.commits, self.reward = 0, 0, False
        self.param = {"periods": periods or ["每日"]}
        self.period, self.sold_periods = "每日", {"每日": sold, "每周": sold}
        self.paid = paid
        self.disabled = {}
        self.context = NS(tasker=NS(stopping=False), override_pipeline=self.disabled.update)
    def capture(self): self.check()
    def pause(self, seconds=.4): self.clock += seconds
    def log(self, message): pass
    def find(self, pattern, roi=None):
        values = []
        self.sold = self.sold_periods[self.period]
        if self.page == "shop":
            if roi == (65,12,100,55): values = ["商店"]
            if roi == (305,140,970,565): values = [self.period+"免费礼包"]
            if roi == (311,202,270,180) and self.sold: values = ["售罄"]
            if roi == (311,357,270,65): values = ["免费"]
            if roi == (350,75,135,55): values = ["商品"]
            if roi == (75,155,180,230): values = ["每日", "每周"]
        if self.page == "popup":
            if roi == (540,75,210,60): values = ["购买商品"]
            if roi == (270,480,260,65): values = [self.period+"免费礼包"]
            if roi == (500,580,280,65): values = ["100钻石" if self.paid else "免费"]
            if roi == (250,150,730,480) and self.sold: values = ["已领取"]
        return next((NS(text=text,roi=roi,box=NS(x=388,y=157,w=116,h=20)) for text in values if re.search(pattern,text)),None)
    def ocr(self, pattern, roi, **kwargs):
        return [NS(text="每日可购买次数：1/1" if self.sold else "每日可购买次数：0/1")]
    def click_row(self, row, delay=.5):
        if row.text == "商品":
            self.period = "每日"
        elif row.roi == (75,155,180,230):
            self.period = row.text
        elif row.roi == (311,357,270,65):
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
            self.sold_periods[self.period] = True
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

    def test_daily_and_weekly_are_separate_free_claims(self):
        model = GiftReplay(periods=["每日", "每周"])
        self.assertTrue(self.run_gift(model))
        self.assertEqual(model.commits, 2)
        self.assertEqual(model.sold_periods, {"每日": True, "每周": True})

    def test_sold_daily_does_not_skip_available_weekly(self):
        model = GiftReplay(sold=True, periods=["每日", "每周"])
        model.sold_periods["每周"] = False
        self.assertTrue(self.run_gift(model))
        self.assertEqual(model.commits, 1)

    def test_weekly_popup_with_a_price_is_never_bought(self):
        model = GiftReplay(periods=["每周"], paid=True)
        with self.assertRaisesRegex(RuntimeError, "没有确认礼包为免费"):
            self.run_gift(model)
        self.assertEqual(model.commits, 0)

    def test_claimed_weekly_gift_at_last_column_second_row_is_found_without_purchase(self):
        model = GiftReplay(periods=["每周"])
        model.sold_periods["每周"] = True
        model.pans = 0
        original = model.find
        def find(pattern, roi=None):
            if roi == (305,140,970,565) and model.period == "每周":
                model.sold = True
                text = "每周免费礼包" if model.pans else "每周金币礼包"
                return NS(text=text,roi=roi,box=NS(x=1070,y=447,w=120,h=20)) if re.search(pattern,text) else None
            return original(pattern,roi)
        def swipe(*args):
            self.assertEqual(args,(1115,420,390,420))
            model.pans += 1
        model.find, model.swipe = find, swipe
        self.assertTrue(self.run_gift(model))
        self.assertEqual(model.pans,1)
        self.assertEqual((model.opens,model.commits),(0,0))

if __name__ == "__main__": unittest.main()
