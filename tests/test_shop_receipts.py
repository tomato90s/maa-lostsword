import copy
import json
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.shop_actions import ShopBatch, amount, product_allowed, quantity, totals


class Replay(ShopBatch):
    def __init__(self, receipt=True, mismatch=False, wrong_balance=False):
        self.category = "消耗品"
        self.param = {"category": self.category}
        self.context = NS(tasker=NS(stopping=False))
        self.clock, self.deadline, self.commits = 0, 1000, 0
        self.receipt, self.mismatch, self.wrong_balance = receipt, mismatch, wrong_balance
        self.reward_closed = False
        self.records = []
        self.items = [dict(name="褪色的宝石箱", currency="金币", selected=True,
                           quantity=2, maximum=2, price=100),
                      dict(name="金币券", currency="信物", selected=True,
                           quantity=1, maximum=1, price=20)]

    def log(self, message): pass
    def capture(self): pass
    def pause(self, seconds=.4): self.clock += seconds
    def popup(self): return True
    def wallet(self):
        return {"金币": 10000 - (100 if self.commits and not self.wrong_balance else 0), "钻石": 1000}
    def category_balance(self): return 1000 - (20 if self.commits else 0)
    def open_category(self): pass
    def walk(self, configure=False): return copy.deepcopy(self.items)
    def summary(self): return {"金币": 99 if self.mismatch else 100, "信物": 20}
    def find(self, pattern, roi=None): return NS(text="批量购买", roi=roi) if re.search(pattern, "批量购买") else None
    def click(self, *args): pass
    def click_row(self, row, *args):
        if row.roi == (480, 600, 325, 65): self.commits += 1
    def close_reward(self):
        if self.commits and self.receipt and not self.reward_closed:
            self.reward_closed = True
            return True
        return False
    def ledger(self, record=None):
        if record is not None:
            self.records.append(record)
            return
        return self.records[-1] if self.records else None


class ShopReceiptTests(unittest.TestCase):
    def run_model(self, model):
        with patch("agent.shop_actions.time.monotonic", lambda: model.clock):
            return model.execute()

    def test_opening_waits_for_the_popup_and_only_retries_a_missed_navigation_tap(self):
        for missed_first, expected_clicks in ((False, 1), (True, 2)):
            model = ShopBatch()
            clock, clicks, opens_at = [0], [], [None]
            model.capture = lambda: None
            model.pause = lambda seconds=.4: clock.__setitem__(0, clock[0] + seconds)
            model.popup = lambda: opens_at[0] is not None and clock[0] >= opens_at[0]
            model.find = lambda pattern, roi: NS(text="page button")
            def click(row, delay):
                clicks.append(row)
                if not missed_first or len(clicks) > 1: opens_at[0] = clock[0] + 1.8
                clock[0] += delay
            model.click_row = click
            with patch("agent.shop_actions.time.monotonic", lambda: clock[0]):
                model.open_batch()
            self.assertEqual(len(clicks), expected_clicks)

    def test_unknown_page_does_not_receive_a_batch_open_tap(self):
        model = ShopBatch()
        clock, clicks = [0], []
        model.capture = lambda: None
        model.pause = lambda seconds=.4: clock.__setitem__(0, clock[0] + seconds)
        model.popup = lambda: False
        model.find = lambda *args: None
        model.click_row = lambda *args: clicks.append(args)
        with patch("agent.shop_actions.time.monotonic", lambda: clock[0]):
            with self.assertRaisesRegex(RuntimeError, "没有提交购买"):
                model.open_batch()
        self.assertEqual(clicks, [])

    def test_thousands_and_quantity_do_not_accept_compacted_or_joined_text(self):
        self.assertEqual(amount("3.400.000"), 3400000)
        self.assertEqual(quantity("1000/1000"), (1000, 1000))
        for text in ("1亿", "US$3.79", "1/1", "20金币"):
            self.assertIsNone(amount(text))
        for text in ("3/2", "10", "1/-1"):
            self.assertIsNone(quantity(text))

    def test_same_product_requires_the_matching_category_and_currency(self):
        self.assertTrue(product_allowed("突袭", "梅林的特制药水", "突袭币"))
        self.assertFalse(product_allowed("突袭", "梅林的特制药水", "信物"))
        self.assertFalse(product_allowed("消耗品", "领主召唤券：巨石阵", "钻石"))

    def test_mismatched_summary_never_commits(self):
        model = Replay(mismatch=True)
        with self.assertRaisesRegex(RuntimeError, "总价不一致"):
            self.run_model(model)
        self.assertEqual((model.commits, model.records), (0, []))

    def test_premium_or_unknown_selected_currency_cannot_commit(self):
        for currency in ("钻石", "unknown"):
            model = Replay()
            model.items[0]["currency"] = currency
            with self.assertRaises(RuntimeError):
                self.run_model(model)
            self.assertEqual(model.commits, 0)

    def test_success_requires_reward_and_exact_actual_balances(self):
        model = Replay()
        self.assertTrue(self.run_model(model))
        self.assertEqual(model.commits, 1)
        self.assertEqual([record["status"] for record in model.records], ["unknown", "confirmed"])
        self.assertTrue(self.run_model(model))
        self.assertEqual(model.commits, 1)

    def test_uncertain_purchase_is_not_submitted_again(self):
        for model in (Replay(receipt=False), Replay(wrong_balance=True)):
            with self.assertRaises(RuntimeError):
                self.run_model(model)
            self.assertEqual(model.commits, 1)
            self.assertEqual(model.records[-1]["status"], "unknown")
            with self.assertRaisesRegex(RuntimeError, "此前购买结果未确认"):
                self.run_model(model)
            self.assertEqual(model.commits, 1)

    def test_preview_and_insufficient_balance_never_commit(self):
        model = Replay()
        model.param["preview"] = True
        self.assertTrue(self.run_model(model))
        self.assertEqual((model.commits, model.records), (0, []))
        model = Replay()
        model.category_balance = lambda: 19
        self.assertTrue(self.run_model(model))
        self.assertEqual((model.commits, model.records), (0, []))

    def test_unapplied_click_needs_unchanged_wallet_and_item_limits(self):
        for changed in (False, True):
            model = Replay()
            record = {"status":"unknown", "before":{"金币":10000,"钻石":1000,"分类代币":1000},
                      "cost":{"金币":100,"信物":20},"items":copy.deepcopy(model.items)}
            model.records.append(record)
            model.param["reconcile_only"] = True
            if changed:
                model.items[0]["maximum"] -= 1
                with self.assertRaisesRegex(RuntimeError,"剩余数量"):
                    self.run_model(model)
                self.assertEqual(model.records[-1]["status"],"unknown")
            else:
                self.assertTrue(self.run_model(model))
                self.assertEqual(model.records[-1]["status"],"not_applied")
            self.assertEqual(model.commits,0)

    def test_unchanged_stock_cannot_clear_a_changed_wallet(self):
        model = Replay()
        model.records.append({"status":"unknown","before":{"金币":10001,"钻石":1000,"分类代币":1000}})
        model.param["reconcile_only"] = True
        with self.assertRaisesRegex(RuntimeError,"余额发生变化"):
            self.run_model(model)
        self.assertEqual((model.commits,model.records[-1]["status"]),(0,"unknown"))

    def test_missed_tap_can_retry_once_only_after_unapplied_proof(self):
        class LostTapReplay(Replay):
            presses = 0
            def click_row(self, row, *args):
                if row.roi == (480,600,325,65):
                    self.presses += 1
                    if self.presses > 1: self.commits += 1
        model = LostTapReplay()
        self.assertTrue(self.run_model(model))
        self.assertEqual((model.presses,model.commits),(2,1))
        self.assertEqual([record["status"] for record in model.records], ["unknown","not_applied","unknown","confirmed"])

    def test_pumpkin_batch_only_contains_daily_tickets(self):
        self.assertTrue(product_allowed("南瓜币", "南瓜票券", "金币"))
        self.assertTrue(product_allowed("南瓜币", "轮盘券", "南瓜币"))
        self.assertTrue(product_allowed("南瓜币", "Boss Raid Ticket", "南瓜币"))
        self.assertFalse(product_allowed("南瓜币", "角色召唤券", "南瓜币"))
        self.assertFalse(product_allowed("南瓜币", "轮盘券", "钻石"))
        pipeline = json.loads((ROOT / "assets/resource/pipeline/商店.json").read_text("utf-8"))
        node = pipeline["Local_ShopPumpkinBatch"]
        self.assertEqual(node["action"]["param"]["custom_action_param"]["category"], "南瓜币")

    def test_four_enabled_categories_use_verified_batch_action(self):
        pipeline = json.loads((ROOT / "assets/resource/pipeline/商店.json").read_text("utf-8"))
        for prefix, category in (("", "消耗品"), ("突袭-", "突袭"), ("公会-", "公会"), ("竞技场-", "竞技场")):
            node = pipeline["商店-" + prefix + "批量购买"]
            self.assertEqual(node["action"]["param"]["custom_action"], "LocalShopBatch")
            self.assertEqual(node["action"]["param"]["custom_action_param"]["category"], category)
            self.assertEqual(node["next"], [])


if __name__ == "__main__":
    unittest.main()
