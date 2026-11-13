import unittest
from types import SimpleNamespace as NS
from agent.daily_actions import GuildInvest, TreasureQuickFree


class InvestReplay(GuildInvest):
    def __init__(self, used=0, outcome="ok", priced=True):
        self.param = {"scope": "coin"}
        self.used, self.outcome, self.priced = used, outcome, priced
        self.clicks, self.frames, self.disabled = 0, 0, {}
        self.context = NS(override_pipeline=self.disabled.update)
    def state(self, scope): return self.used
    def offer(self, scope): return NS(text="投资") if self.priced else None
    def pause(self, *args): pass
    def log(self, *args): pass
    def find(self, *args): return None
    def close_reward(self): return False
    def capture(self):
        self.frames += 1
        if self.clicks and self.outcome == "ok" and self.frames >= 5: self.used = 1
    def click_row(self, *args):
        self.clicks += 1
        self.frames = 0
        if self.outcome == "unknown": self.used = None


class QuickReplay(TreasureQuickFree):
    def __init__(self, free=1, outcome="ok"):
        self.free, self.outcome, self.clicks, self.frames = free, outcome, 0, 0
    def remaining(self): return self.free
    def pause(self, *args): pass
    def log(self, *args): pass
    def find(self, *args): return NS(text="开始探查")
    def close_reward(self): return False
    def capture(self):
        self.frames += 1
        if self.clicks and self.outcome == "ok" and self.frames >= 5: self.free = 0
    def click_row(self, *args):
        self.clicks += 1
        self.frames = 0
        if self.outcome == "unknown": self.free = None


class DailyReceiptRecoveryTests(unittest.TestCase):
    def test_delayed_investment_is_confirmed_without_a_second_click(self):
        model = InvestReplay()
        self.assertTrue(model.execute())
        self.assertEqual(model.clicks, 1)
        self.assertEqual(model.disabled, {"公会-投资金币": {"enabled": False}})

    def test_completed_investment_is_skipped(self):
        model = InvestReplay(used=1)
        self.assertTrue(model.execute())
        self.assertEqual(model.clicks, 0)

    def test_unknown_investment_result_is_never_retried(self):
        model = InvestReplay(outcome="unknown")
        with self.assertRaisesRegex(RuntimeError, "结果不明"): model.execute()
        self.assertEqual(model.clicks, 1)

    def test_unverified_investment_price_prevents_input(self):
        model = InvestReplay(priced=False)
        with self.assertRaisesRegex(RuntimeError, "价格无法确认"): model.execute()
        self.assertEqual(model.clicks, 0)

    def test_two_unchanged_investment_attempts_fail(self):
        model = InvestReplay(outcome="dropped")
        with self.assertRaisesRegex(RuntimeError, "仍为0/1"): model.execute()
        self.assertEqual(model.clicks, 2)

    def test_free_exploration_waits_for_counter_change(self):
        model = QuickReplay()
        self.assertTrue(model.execute())
        self.assertEqual(model.clicks, 1)

    def test_no_free_exploration_never_clicks(self):
        model = QuickReplay(free=0)
        self.assertTrue(model.execute())
        self.assertEqual(model.clicks, 0)

    def test_unknown_exploration_state_never_clicks(self):
        model = QuickReplay(free=None)
        with self.assertRaisesRegex(RuntimeError, "未确认剩余1次"): model.execute()
        self.assertEqual(model.clicks, 0)

    def test_unknown_post_exploration_state_is_not_retried(self):
        model = QuickReplay(outcome="unknown")
        with self.assertRaisesRegex(RuntimeError, "结果不明"): model.execute()
        self.assertEqual(model.clicks, 1)

    def test_reward_closes_back_to_treasure_page_without_a_second_submission(self):
        model = QuickReplay(outcome="unknown")
        seen = []
        def close_reward():
            if model.clicks and not seen:
                seen.append(True)
                return True
            return False
        model.close_reward = close_reward
        self.assertTrue(model.execute())
        self.assertEqual(model.clicks, 1)


if __name__ == "__main__": unittest.main()
