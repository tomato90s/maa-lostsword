"""Replay the November 28 modals and delayed receipts without device input."""
import re
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from agent.daily_actions import StonehengeGate
from agent.local_actions import DailySweep
from test_daily_actions import ArenaModel, row
from test_seasonal_tasks import RaidReplay


class RefreshReplay(ArenaModel):
    def __init__(self, failures=1):
        super().__init__(limit=1, tickets=1)
        self.state = "all-won"
        self.clock = 0
        self.failures = failures
        self.refreshes = []
        self.dismissals = []

    def capture(self):
        self.clock += .05

    def pause(self, seconds=.4):
        self.clock += seconds

    def ocr(self, pattern, *args, **kwargs):
        if self.state in ("all-won", "notice") and pattern == r"^WIN$":
            return [row("WIN")] * 3
        return super().ocr(pattern, *args, **kwargs)

    def find(self, pattern, roi=None):
        if self.state in ("all-won", "notice"):
            visible = [("对战对手", "label"), ("刷新列表", "refresh")]
            if self.state == "notice":
                visible += [("请稍后再试。", "notice"), ("确认", "notice-confirm")]
            return next((row(text, tag=tag) for text, tag in visible
                         if re.search(pattern, text)), None)
        return super().find(pattern, roi)

    def click_row(self, item, delay=.5):
        if item.tag == "refresh":
            assert self.state == "all-won", "clicked behind the error modal"
            self.refreshes.append(self.clock)
            self.state = "notice" if len(self.refreshes) <= self.failures else "opponents"
        elif item.tag == "notice-confirm":
            self.dismissals.append(self.clock)
            self.state = "all-won"
        else:
            super().click_row(item, delay)
        self.pause(delay)


class DungeonExitReplay(DailySweep):
    def __init__(self, stuck=False):
        super().__init__()
        self.state = "reward"
        self.clock = 0
        self.stuck = stuck
        self.clicks = []
        self.frames = 0

    def capture(self):
        self.frames += 1

    def pause(self, seconds=.6):
        self.clock += seconds

    def find(self, pattern, roi=None):
        visible = {"reward": ["已获得道具。"], "dialog": ["副本一键扫荡"],
                   "preparation": ["队伍编排", "一键扫荡"],
                   "stage": ["冒险区域"], "list": ["战斗", "副本", "巨石阵"]}[self.state]
        return next((row(text) for text in visible if re.search(pattern, text)), None)

    def click(self, x, y, delay=.5):
        self.clicks.append((x, y))
        if self.state == "reward":
            assert (x, y) == (640, 680)
            if not self.stuck and len(self.clicks) > 1:
                self.state = "dialog"
        elif self.state == "dialog":
            assert (x, y) == (1151, 71)
            self.state = "preparation"
        elif self.state == "preparation":
            assert (x, y) in ((1235, 36), (1235, 35))
            self.state = "stage"
        elif self.state == "stage":
            assert (x, y) in ((1235, 36), (1235, 35))
            self.state = "list"
        else:
            raise AssertionError("clicked after returning to the dungeon list")
        self.pause(delay)
        self.capture()


class ModalConfirmationTests(unittest.TestCase):
    def test_arena_dismisses_refresh_rejection_and_waits_before_retry(self):
        model = RefreshReplay()
        with patch("agent.daily_actions.time.monotonic", lambda: model.clock):
            self.assertTrue(model.execute())
        self.assertEqual((len(model.refreshes), len(model.dismissals), model.results), (2, 1, 1))
        self.assertGreaterEqual(model.refreshes[1] - model.dismissals[0], 5)

    def test_arena_repeated_refresh_rejection_is_bounded_and_not_success(self):
        model = RefreshReplay(failures=10)
        with patch("agent.daily_actions.time.monotonic", lambda: model.clock):
            with self.assertRaisesRegex(RuntimeError, "请稍后再试"):
                model.execute()
        self.assertEqual((len(model.refreshes), len(model.dismissals), model.results), (3, 3, 0))
        self.assertNotEqual(model.state, "notice")

    def test_arena_challenge_rejection_is_not_retried_as_a_refresh(self):
        model = RefreshReplay()
        model.state = "notice"
        with patch("agent.daily_actions.time.monotonic", lambda: model.clock):
            with self.assertRaisesRegex(RuntimeError, "挑战结果未确认"):
                model.execute()
        self.assertEqual((model.refreshes, model.results, len(model.dismissals)), ([], 0, 1))

    def test_dungeon_confirms_reward_closed_and_returns_to_list(self):
        model = DungeonExitReplay()
        model.leave_dialog()
        self.assertEqual(model.state, "list")
        self.assertEqual(model.clicks, [(640, 680), (640, 680), (1151, 71), (1235, 36), (1235, 36)])

    def test_dungeon_leaves_preparation_when_free_attempts_are_exhausted(self):
        model = DungeonExitReplay()
        model.state = "preparation"
        model.leave_dialog()
        self.assertEqual(model.state, "list")
        self.assertEqual(model.clicks, [(1235, 36), (1235, 36)])

    def test_dungeon_does_not_report_success_when_reward_cannot_close(self):
        model = DungeonExitReplay(stuck=True)
        with self.assertRaisesRegex(RuntimeError, "奖励"):
            model.leave_dialog()
        self.assertLessEqual(len(model.clicks), 3)

    def test_stonehenge_closes_existing_reward_before_searching_for_entry(self):
        model = DungeonExitReplay()
        action = StonehengeGate()
        action.context = NS(get_node_data=lambda name: {"enabled": True},
                            override_next=Mock(return_value=True))
        action.argv = NS(node_name="Local_DungeonAfter")
        action.capture, action.pause, action.find = model.capture, model.pause, model.find
        action.click, action.log = model.click, lambda *args: None
        self.assertTrue(action.execute())
        self.assertEqual(model.state, "list")
        action.context.override_next.assert_called_once_with("Local_DungeonAfter", ["副本_点击巨石阵"])

    def test_raid_waits_for_stable_page_before_sending_first_input(self):
        class AnimatedRaid(RaidReplay):
            def click_row(self, item, delay=.5):
                assert self.clock >= 2, "sweep clicked while the entry animation was still running"
                super().click_row(item, delay)
        model = AnimatedRaid(limit=1)
        with patch("agent.seasonal_actions.time.monotonic", lambda: model.clock):
            self.assertTrue(model.execute())
        self.assertEqual((model.commits, model.free, model.tickets), (1, 2, 403))

    def test_raid_accepts_late_receipt_without_resubmitting(self):
        class SlowRaid(RaidReplay):
            def click_row(self, item, delay=.5):
                self.commits += 1
                self.receipt_at = self.clock + 35

            def close_reward(self):
                if self.commits and not self.reward_closed and self.clock >= self.receipt_at:
                    self.free -= 1
                    self.reward_closed = True
                    return True
                return False
        model = SlowRaid(limit=1)
        with patch("agent.seasonal_actions.time.monotonic", lambda: model.clock):
            self.assertTrue(model.execute())
        self.assertEqual((model.commits, model.free, model.records[-1]["status"]), (1, 2, "confirmed"))

    def test_existing_unknown_raid_is_observed_without_sending_another_sweep(self):
        pending = {"status": "unknown", "before_tickets": 403, "before_free": 3}
        model = RaidReplay(previous=pending, receipt=False)
        with patch("agent.seasonal_actions.time.monotonic", lambda: model.clock):
            with self.assertRaisesRegex(RuntimeError, "已经提交过"):
                model.execute()
        self.assertEqual(model.commits, 0)
        self.assertEqual(model.records, [pending])
        self.assertGreaterEqual(model.clock, 60)

    def test_existing_pending_raid_can_recover_a_reward_without_replaying_it(self):
        class PendingReward(RaidReplay):
            def close_reward(self):
                if not self.reward_closed:
                    self.reward_closed = True
                    self.free -= 1
                    return True
                return False
        model = PendingReward(previous={"status": "unknown", "before_tickets": 403,
                                        "before_free": 3}, limit=1)
        with patch("agent.seasonal_actions.time.monotonic", lambda: model.clock):
            self.assertTrue(model.execute())
        self.assertEqual((model.commits, model.free, model.tickets), (0, 2, 403))
        self.assertEqual(model.records[-1]["status"], "counter_confirmed")
        self.assertTrue(model.records[-1]["reward_verified"])

    def test_raid_server_notice_after_submission_does_not_repeat_the_sweep(self):
        class RejectedRaid(RaidReplay):
            def close_retry_notice(self):
                return self.commits > 0
        model = RejectedRaid(receipt=False)
        with patch("agent.seasonal_actions.time.monotonic", lambda: model.clock):
            with self.assertRaisesRegex(RuntimeError, "请稍后再试"):
                model.execute()
        self.assertEqual(model.commits, 1)
        self.assertEqual(model.records[-1]["status"], "unknown")


if __name__ == "__main__":
    unittest.main()
