import sys
import re
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from agent import seasonal_actions as seasonal
except ImportError as exc:  # maafw is bundled only with the runtime
    raise unittest.SkipTest(str(exc))


class FriendPointsTest(unittest.TestCase):
    def test_reads_live_counters(self):
        self.assertEqual(seasonal.friend_points("今日已赠送友情点数15/30 今日已领取友情点数4/30"), (15, 4))

    def test_missing_counter_is_unknown(self):
        self.assertIsNone(seasonal.friend_points("今日已赠送友情点数15/30"))


class CowFreeStateTest(unittest.TestCase):
    def test_bell_cost_is_not_free(self):
        # Live screen after this week's free entries: bell icon, "1", "进入".
        self.assertEqual(seasonal.cow_free_state("1 进入"), 0)
        self.assertEqual(seasonal.cow_free_state("进入"), 0)

    def test_explicit_free_marker(self):
        self.assertEqual(seasonal.cow_free_state("免费 2/3 进入"), 2)
        self.assertEqual(seasonal.cow_free_state("免费进入"), -1)
        self.assertEqual(seasonal.cow_free_state("进入 0/3"), 0)

    def test_live_enter_counter_is_free_and_unrelated_ratio_is_unknown(self):
        for text, value in (("进入3/3", 3), ("进入 2 ／ 3", 2), ("进入1/3", 1)):
            self.assertEqual(seasonal.cow_free_state(text), value)
        self.assertIsNone(seasonal.cow_free_state("3/3"))
        self.assertIsNone(seasonal.cow_free_state("奖励3/3"))

    def test_submission_and_result_count_as_one_attempt(self):
        records = [{"attempt": "first", "status": "submitted"},
                   {"attempt": "first", "status": "confirmed"}]
        self.assertEqual(seasonal.cow_attempts(records), 1)
        records += [{"attempt": "second", "status": "submitted"},
                    {"attempt": "second", "status": "confirmed"}]
        self.assertEqual(seasonal.cow_attempts(records), 2)
        records += [{"attempt": "third", "status": "submitted"},
                    {"attempt": "third", "status": "cancelled"}]
        self.assertEqual(seasonal.cow_attempts(records), 2)

    def test_old_weekly_receipts_do_not_double_count(self):
        self.assertEqual(seasonal.cow_attempts([{"status": "submitted"}, {"status": "confirmed"}]), 1)

    def test_exhausted_free_entries_skip_the_normal_task_without_entering(self):
        action = seasonal.SecretCow()
        action.param = {"limit":3}
        action.ledger = lambda: [{"attempt":"old", "status":"submitted"},
                                 {"attempt":"old", "status":"safety_stopped"}]
        action.open_dungeon = lambda: None
        action.to_team = lambda: True
        action.title = lambda: NS(text="秘密奶牛副本第16层")
        action.ocr = lambda *args: [NS(text="1 进入")]
        action.find = lambda *args: NS(text="进入")
        action.log = lambda *args: None
        action.ensure_single_battle = lambda: self.fail("Paid entry must not be prepared")
        action.click_row = lambda *args: self.fail("Exhausted task must not enter")
        self.assertTrue(action.execute())

    def test_custom_five_entry_setting_is_kept_and_exhaustion_is_checked(self):
        action = seasonal.SecretCow()
        action.param = {"limit":5}
        action.ledger = lambda: [{"attempt":str(i), "status":"confirmed"} for i in range(3)]
        action.log = lambda *args: None
        visits = []
        action.open_dungeon = lambda: visits.append(True)
        action.to_team = lambda: True
        action.title = lambda: NS(text="秘密奶牛副本第16层")
        action.find = lambda *args: NS(text="进入")
        action.ocr = lambda *args: [NS(text="1 进入")]
        action.click_row = lambda *args: self.fail("Free entries are exhausted")
        self.assertTrue(action.execute())
        self.assertEqual(visits,[True])

    def test_an_unreadable_counter_is_not_reported_as_an_exhausted_skip(self):
        action = seasonal.SecretCow()
        action.param = {"limit":3}
        action.ledger = lambda: []
        action.open_dungeon = lambda: None
        action.to_team = lambda: True
        action.title = lambda: NS(text="秘密奶牛副本第16层")
        action.find = lambda *args: NS(text="进入")
        action.ocr = lambda *args: [NS(text="剩余次数未知")]
        action.click_row = lambda *args: self.fail("Unknown counter must not enter")
        with self.assertRaisesRegex(RuntimeError,"未确认"):
            action.execute()

    def test_free_runs_do_not_consume_a_custom_bell_quota_after_restart(self):
        class Replay(seasonal.SecretCow):
            def __init__(self):
                self.param = {"use_custom_count": True, "limit": 0}
                self.records, self.entries, self.free = [], 0, 3
            def ledger(self, record=None):
                if record is not None: self.records.append(record)
                return self.records
            def open_dungeon(self): pass
            def ensure_single_battle(self): return self.free, 0
            def to_team(self): return True
            def title(self): return NS(text="秘密奶牛副本第16层")
            def ocr(self, *args): return [NS(text=f"进入{self.free}/3")]
            def bells(self): return 263
            def find(self, *args): return NS(text="进入")
            def log(self, *args): pass
            def click_row(self, *args): self.entries += 1
            def battle(self, bells, before_free):
                self.free -= 1
                self.last_cow_free = self.free
                return True
        replay = Replay()
        self.assertTrue(replay.execute())
        replay.param = {"use_custom_count": True, "limit": 0}
        self.assertTrue(replay.execute())
        self.assertEqual((replay.entries, replay.free), (3, 0))
        self.assertEqual(seasonal.cow_attempts(replay.records), 3)
        self.assertEqual(seasonal.cow_paid_attempts(replay.records), 0)
        self.assertTrue(replay.execute())
        self.assertEqual(replay.entries, 3)

    def test_entry_requires_a_current_team_page_with_explicit_free_attempts(self):
        action = seasonal.SecretCow()
        action.capture = lambda: None
        action.title = lambda: True
        action.find = lambda *args: NS(text="队伍编排")
        action.ocr = lambda *args: [NS(text="1 进入")]
        with self.assertRaisesRegex(RuntimeError, "未确认每周免费次数"):
            action.ensure_single_battle()
        action.ocr = lambda *args: [NS(text="进入3/3")]
        action.ensure_single_battle()

    def test_team_page_never_counts_as_an_observed_battle(self):
        action = seasonal.SecretCow()
        action.find = lambda pattern, roi: NS(text="matched")
        self.assertFalse(action.battle_active())

    def test_failed_battle_start_still_attempts_to_exit(self):
        action = seasonal.SecretCow()
        action.wait_battle_start = lambda: (_ for _ in ()).throw(RuntimeError("entry delayed"))
        exits = []
        action.leave_battle = lambda: exits.append(True)
        with self.assertRaisesRegex(RuntimeError, "entry delayed"):
            action.battle(196,3)
        self.assertEqual(exits,[True])

    def test_battle_start_waits_until_the_entry_controls_disappear(self):
        class EnterReplay(seasonal.SecretCow):
            def __init__(self): self.frames = 0
            def capture(self): self.frames += 1
            def pause(self, *args): pass
            def log(self, *args): pass
            def find(self, pattern, roi):
                if roi == (960, 75, 300, 55): return NS(text="秘密奶牛副本第16层")
                return NS(text="队伍编排") if self.frames < 3 else None
        action = EnterReplay()
        self.assertTrue(action.wait_battle_start())
        self.assertEqual(action.frames, 3)

    def test_cow_exit_uses_the_stage_exit_and_exact_confirmation(self):
        class ExitReplay(seasonal.SecretCow):
            phase = "battle"
            def __init__(self): self.sent = []
            def capture(self): pass
            def pause(self, *args): pass
            # The old generic home template can falsely match combat.
            def node(self, name): return True
            def title(self): return None
            def find(self, pattern, roi):
                choices = {"battle":["秘密奶牛副本第16层"],
                           "prompt":["是否确定退场？","退场"],
                           "home":["战斗","角色","召唤"]}[self.phase]
                return next((NS(text=text) for text in choices if re.search(pattern,text)),None)
            def click(self,x,y,delay):
                self.sent.append((x,y))
                self.phase = "prompt"
            def click_row(self,row,delay):
                self.sent.append(row.text)
                self.phase = "home"
        replay = ExitReplay()
        self.assertTrue(replay.leave_battle())
        self.assertEqual(replay.sent,[(1236,36),"退场"])

    def test_cow_exit_never_clicks_in_an_unknown_screen(self):
        action = seasonal.SecretCow()
        from unittest.mock import patch
        clock = [0]
        action.capture = lambda: None
        action.pause = lambda *args: clock.__setitem__(0,clock[0]+1)
        action.node = action.title = lambda *args: None
        action.find = lambda *args: None
        sent = []
        action.click = action.click_row = lambda *args: sent.append(args)
        with patch("agent.seasonal_actions.time.monotonic",lambda:clock[0]):
            with self.assertRaisesRegex(RuntimeError,"手动退场"):
                action.leave_battle()
        self.assertEqual(sent,[])

    def test_team_overlay_is_closed_instead_of_being_reported_as_an_exit(self):
        class PanelReplay(seasonal.SecretCow):
            def __init__(self): self.phase, self.sent = "panel", []
            def capture(self): pass
            def pause(self, *args): pass
            def log(self, *args): pass
            def title(self): return self.phase == "panel"
            def node(self, name): return True
            def find(self, pattern, roi):
                texts = {"panel":["队伍编排","进入"],
                         "battle":["秘密奶牛副本第16层"],
                         "menu":["退场"],"village":["冒险"]}[self.phase]
                return next((NS(text=text) for text in texts if re.search(pattern,text)),None)
            def click(self,x,y,delay):
                self.sent.append((x,y))
                self.phase = "battle" if self.phase == "panel" else "menu"
            def click_row(self,row,delay):
                self.sent.append(row.text)
                self.phase = "village"
        action = PanelReplay()
        self.assertTrue(action.leave_battle())
        self.assertEqual(action.sent, [(1236,36),(1236,36),"退场"])

    def test_next_free_entry_requires_a_reward_exit_and_unchanged_bells(self):
        for after_bells, after_free, succeeds in ((263,2,True),(262,2,False),(263,3,False)):
            action = seasonal.SecretCow()
            events = []
            action.wait_battle_start = lambda: events.append("battle")
            action.wait_first_reward = lambda bells: events.append("reward")
            action.leave_battle = lambda: events.append("exit")
            action.open_dungeon = lambda: events.append("reopen")
            action.to_team = lambda: True
            action.bells = lambda: after_bells
            action.ocr = lambda *args: [NS(text=f"进入{after_free}/3")]
            action.log = lambda *args: None
            if succeeds:
                self.assertTrue(action.battle(263,3))
                self.assertEqual(action.last_cow_free,2)
            else:
                with self.assertRaises(RuntimeError): action.battle(263,3)
                self.assertFalse(hasattr(action,"last_cow_free"))
            self.assertEqual(events,["battle","reward","exit","reopen"])

    def test_week_uses_game_reset_timezone(self):
        # Sunday 15:30 UTC is already Monday in UTC+9.
        self.assertEqual(seasonal.game_week(datetime(2026, 11, 1, 15, 30, tzinfo=timezone.utc)), "2026-W45")
        self.assertEqual(seasonal.game_week(datetime(2026, 11, 1, 14, 30, tzinfo=timezone.utc)), "2026-W44")


if __name__ == "__main__":
    unittest.main()
