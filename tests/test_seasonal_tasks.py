"""Seasonal resource guards and uncertain-write behavior, without game inputs."""
import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.seasonal_actions import BingoCraft, RaidSweep, RouletteFree, SeasonalScreen, material_ratio, unsigned_number
from agent.daily_actions import ScreenAction


class CraftReplay(BingoCraft):
    def __init__(self, coins=100, limit=5, cap=5, receipt=True, valid_recipe=True, initial=0, step=1):
        super().__init__()
        self.param = {"limit": limit}
        self.clock, self.deadline = 0, 1000
        self.context = NS(tasker=NS(stopping=False))
        self.coins, self.tickets, self.quantity = coins, 0, initial
        self.cap, self.receipt, self.valid_recipe = cap, receipt, valid_recipe
        self.step = step
        self.used = 5 - cap
        self.commits, self.clicks, self.messages = 0, [], []

    def capture(self):
        self.check()

    def pause(self, seconds=.4):
        self.clock += seconds

    def log(self, message):
        self.messages.append(message)

    def open_menu(self, label):
        assert label == "制作"

    def recipe(self):
        return self.valid_recipe

    def material(self):
        return self.coins, 20 * max(1, self.quantity)

    def daily_counter(self): return self.used

    def selected_quantity(self): return self.quantity

    def number(self, roi):
        return {(1000, 15, 70, 40): self.tickets, (1120, 15, 90, 40): self.coins,
                (800, 650, 120, 50): self.quantity}[roi]

    def find(self, pattern, roi=None):
        for text in ("活动", "宾果票券", "制作"):
            if re.search(pattern, text):
                return NS(text=text)
        return None

    def click_row(self, row, delay=.5):
        if row.text == "制作":
            self.commits += 1
            if self.receipt:
                self.tickets += self.quantity
                self.coins -= self.quantity * 20
                self.used += self.quantity

    def click(self, x, y, delay=.5):
        assert (x, y) == (973, 678)
        self.clicks.append((x, y))
        self.quantity = min(self.quantity + self.step, self.cap)

    def close_reward(self):
        return False


class RaidReplay(RaidSweep):
    def __init__(self, quantity=1, receipt=True, valid=True, initial_dialog=True, previous=None, free=None):
        super().__init__()
        self.clock, self.deadline = 0, 1000
        self.context = NS(tasker=NS(stopping=False))
        self.quantity, self.receipt, self.valid = quantity, receipt, valid
        self.tickets, self.commits, self.reward_closed = 403, 0, False
        self.initial_dialog, self.records = initial_dialog, [] if previous is None else [previous]
        self.free = free

    def free_remaining(self): return self.free

    def ledger(self, record=None):
        if record is not None: self.records.append(record)
        return self.records[-1] if self.records else None

    def capture(self):
        self.check()

    def pause(self, seconds=.4):
        self.clock += seconds

    def log(self, message):
        pass

    def dialog(self):
        return self.initial_dialog and self.valid and (not self.commits or not self.receipt)

    def number(self, roi):
        return self.quantity if roi == (620, 373, 45, 36) else self.tickets

    def find(self, pattern, roi=None):
        if not self.valid:
            return None
        return NS(text="扫荡")

    def click_row(self, row, delay=.5):
        self.commits += 1
        if self.receipt:
            if self.free:
                self.free -= 1
            else:
                self.tickets -= 1

    def close_reward(self):
        if self.commits and self.receipt and not self.reward_closed:
            self.reward_closed = True
            return True
        return False


class RouletteReplay(RouletteFree):
    def __init__(self, free=1, receipt=True, spent=False, paid=False):
        super().__init__()
        self.clock, self.deadline = 0, 1000
        self.context = NS(tasker=NS(stopping=False))
        self.free, self.receipt, self.spent = free, receipt, spent
        self.paid = paid
        self.commits, self.reward_closed = 0, False

    def open_activity(self, label):
        assert label == "贝迪兔女郎轮盘"

    def page(self): return True
    def free_remaining(self):
        if self.commits and self.receipt:
            return None if self.paid else 0
        return self.free
    def paid_only(self): return self.paid and (self.free is None or bool(self.commits))
    def number(self, roi): return 243 if self.commits and self.spent else 244
    def find(self, pattern, roi=None): return NS(text="PUSH")
    def capture(self): self.check()
    def pause(self, seconds=.4): self.clock += seconds
    def log(self, message): pass

    def click_row(self, row, delay=.5):
        assert row.text == "PUSH"
        self.commits += 1

    def close_reward(self):
        if self.commits and self.receipt and not self.reward_closed:
            self.reward_closed = True
            return True
        return False


class SeasonalTests(unittest.TestCase):
    def test_bingo_counter_handles_split_ocr_rows(self):
        screen = BingoCraft()
        screen.ocr = lambda *args, **kwargs: [NS(text="每日可制作次数："), NS(text="0/5")]
        self.assertEqual(screen.daily_counter(), 0)
        screen.material = lambda: (13160, 100)
        self.assertEqual(screen.selected_quantity(), 5)

    def test_numeric_detection_reads_zero_without_accepting_punctuation(self):
        screen = SeasonalScreen()
        calls = []
        def recognize(pattern, roi, only_rec=False):
            calls.append(only_rec)
            return [NS(text="。" if only_rec else "0")]
        screen.ocr = recognize
        self.assertEqual(screen.number((800, 650, 120, 50)), 0)
        self.assertEqual(calls, [False])
        screen.ocr = lambda *args, **kwargs: [NS(text="0/5")]
        with self.assertRaises(RuntimeError):
            screen.number((800, 650, 120, 50))

    def run_craft(self, model):
        with patch("agent.seasonal_actions.time.monotonic", lambda: model.clock):
            return model.execute()

    def test_numeric_crops_do_not_accept_prices_or_labels(self):
        self.assertEqual(unsigned_number("143,077"), 143077)
        for value in ("免费1次", "US$3.79", "0/5", "-1", "1.5"):
            self.assertIsNone(unsigned_number(value))
        self.assertEqual(material_ratio("1,000 ／ 100"), (1000, 100))
        self.assertIsNone(material_ratio("南瓜币100/20"))

    def test_no_materials_never_selects_or_commits(self):
        model = CraftReplay(coins=19)
        self.assertTrue(self.run_craft(model))
        self.assertEqual((model.commits, model.clicks), (0, []))

    def test_daily_five_crafts_commit_once_and_verify_both_balances(self):
        model = CraftReplay()
        self.assertTrue(self.run_craft(model))
        self.assertEqual((model.commits, model.tickets, model.coins), (1, 5, 0))

    def test_default_one_is_counted_toward_the_requested_limit(self):
        for limit in (1, 5):
            with self.subTest(limit=limit):
                model = CraftReplay(coins=13160, limit=limit, initial=1)
                self.assertTrue(self.run_craft(model))
                self.assertEqual((model.commits, model.tickets, model.coins), (1, limit, 13160 - limit * 20))
                self.assertEqual(len(model.clicks), limit - 1)

    def test_unknown_initial_quantity_is_not_reused(self):
        model = CraftReplay(initial=2)
        with self.assertRaisesRegex(RuntimeError, "初始数量"):
            self.run_craft(model)
        self.assertEqual((model.commits, model.clicks), (0, []))

    def test_repeat_button_may_jump_only_within_the_requested_limit(self):
        model = CraftReplay(initial=1, step=4)
        self.assertTrue(self.run_craft(model))
        self.assertEqual((model.commits, model.tickets), (1, 5))
        model = CraftReplay(initial=1, step=4, limit=2)
        with self.assertRaisesRegex(RuntimeError, "制作数量变化异常"):
            self.run_craft(model)
        self.assertEqual(model.commits, 0)

    def test_game_remaining_cap_and_materials_bound_the_quantity(self):
        for coins, cap, expected in ((40, 5, 2), (200, 3, 3), (200, 0, 0)):
            with self.subTest(coins=coins, cap=cap):
                model = CraftReplay(coins=coins, cap=cap)
                self.assertTrue(self.run_craft(model))
                self.assertEqual(model.tickets, expected)
                self.assertEqual(model.commits, int(expected > 0))

    def test_unconfirmed_craft_is_not_repeated(self):
        model = CraftReplay(receipt=False)
        with self.assertRaisesRegex(RuntimeError, "结果尚未确认"):
            self.run_craft(model)
        self.assertEqual(model.commits, 1)

    def test_craft_result_modal_is_closed_before_checking_balances(self):
        class ResultCraft(CraftReplay):
            result_open = False
            close_reward = ScreenAction.close_reward
            def recipe(self):
                return not self.result_open and super().recipe()
            def find(self, pattern, roi=None):
                if self.result_open:
                    return NS(text="制作结果") if re.search(pattern, "制作结果") else None
                return super().find(pattern, roi)
            def click_row(self, row, delay=.5):
                super().click_row(row, delay)
                if row.text == "制作": self.result_open = True
            def click(self, x, y, delay=.5):
                if self.result_open:
                    assert (x,y) == (640,680)
                    self.result_open = False
                else:
                    super().click(x,y,delay)
        model = ResultCraft(initial=1)
        self.assertTrue(self.run_craft(model))
        self.assertEqual((model.commits,model.tickets,model.coins,model.used),(1,5,0,5))

    def test_wrong_recipe_cannot_consume_anything(self):
        model = CraftReplay(valid_recipe=False)
        with self.assertRaisesRegex(RuntimeError, "配方名称"):
            self.run_craft(model)
        self.assertEqual(model.commits, 0)

    def test_zero_limit_and_invalid_budget_never_commit(self):
        model = CraftReplay(limit=0)
        self.assertTrue(self.run_craft(model))
        self.assertEqual(model.commits, 0)
        with self.assertRaisesRegex(RuntimeError, "0至5"):
            self.run_craft(CraftReplay(limit=6))

    def test_raid_popup_commits_one_default_sweep_and_requires_reward(self):
        model = RaidReplay()
        self.assertTrue(self.run_craft(model))
        self.assertEqual((model.commits, model.tickets, model.reward_closed), (1, 402, True))

    def test_raid_without_confirmation_checks_ticket_before_the_first_click(self):
        model = RaidReplay(initial_dialog=False)
        self.assertTrue(self.run_craft(model))
        self.assertEqual((model.commits, model.tickets), (1, 402))
        self.assertEqual(model.records[-1]["status"], "confirmed")

    def test_raid_free_sweep_changes_daily_counter_without_spending_a_ticket(self):
        model = RaidReplay(initial_dialog=False, free=3)
        self.assertTrue(self.run_craft(model))
        self.assertEqual((model.commits, model.free, model.tickets), (1, 2, 403))

    def test_raid_previous_receipt_prevents_a_second_sweep(self):
        for status in ("confirmed", "unknown", "reward_observed"):
            model = RaidReplay(previous={"status":status})
            if status == "confirmed":
                self.assertTrue(self.run_craft(model))
            else:
                with self.assertRaisesRegex(RuntimeError,"已经提交过"):
                    self.run_craft(model)
            self.assertEqual(model.commits,0)

    def test_raid_rejects_changed_quantity_and_foreign_screens(self):
        for model in (RaidReplay(quantity=2), RaidReplay(valid=False)):
            with self.assertRaises(RuntimeError):
                self.run_craft(model)
            self.assertEqual(model.commits, 0)

    def test_raid_unknown_write_cannot_loop_on_background_button(self):
        model = RaidReplay(receipt=False)
        with self.assertRaisesRegex(RuntimeError, "结果未确认"):
            self.run_craft(model)
        self.assertEqual(model.commits, 1)

    def test_roulette_free_once_keeps_all_existing_tickets(self):
        for paid in (False, True):
            model = RouletteReplay(paid=paid)
            self.assertTrue(self.run_craft(model))
            self.assertEqual((model.commits, model.number(None), model.reward_closed), (1, 244, True))

    def test_roulette_without_explicit_free_chance_never_spends_tickets(self):
        for free in (0, None):
            model = RouletteReplay(free=free)
            if free == 0:
                self.assertTrue(self.run_craft(model))
            else:
                with self.assertRaisesRegex(RuntimeError, "免费1/1"):
                    self.run_craft(model)
            self.assertEqual(model.commits, 0)
        model = RouletteReplay(free=None, paid=True)
        self.assertTrue(self.run_craft(model))
        self.assertEqual(model.commits, 0)

    def test_roulette_unknown_receipt_or_changed_balance_cannot_repeat(self):
        for model in (RouletteReplay(receipt=False), RouletteReplay(spent=True)):
            with self.assertRaises(RuntimeError):
                self.run_craft(model)
            self.assertEqual(model.commits, 1)


if __name__ == "__main__":
    unittest.main()
