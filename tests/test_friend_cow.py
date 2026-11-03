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

    def test_three_runs_survive_restart_after_the_first_confirmed_run(self):
        class Replay(seasonal.SecretCow):
            def __init__(self):
                self.param = {"limit": 1}
                self.records, self.entries, self.free = [], 0, 3
            def ledger(self, record=None):
                if record is not None: self.records.append(record)
                return self.records
            def open_dungeon(self): pass
            def ensure_single_battle(self): pass
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
        replay.param = {"limit": 3}
        self.assertTrue(replay.execute())
        self.assertEqual((replay.entries, replay.free), (3, 0))
        self.assertEqual(seasonal.cow_attempts(replay.records), 3)
        self.assertTrue(replay.execute())
        self.assertEqual(replay.entries, 3)

    def test_unverified_auto_progress_never_allows_an_entry(self):
        action = seasonal.SecretCow()
        with self.assertRaisesRegex(RuntimeError, "暂停奶牛自动进入"):
            action.ensure_single_battle()

    def test_cow_exit_uses_the_stage_exit_and_exact_confirmation(self):
        class ExitReplay(seasonal.SecretCow):
            phase = "battle"
            def __init__(self): self.sent = []
            def capture(self): pass
            def pause(self, *args): pass
            def node(self, name): return self.phase == "home"
            def title(self): return None
            def find(self, pattern, roi):
                choices = {"battle":["秘密奶牛副本第16层"],
                           "prompt":["是否确定退场？","退场"], "home":[]}[self.phase]
                return next((NS(text=text) for text in choices if re.search(pattern,text)),None)
            def click(self,x,y,delay):
                self.sent.append((x,y))
                self.phase = "prompt"
            def click_row(self,row,delay):
                self.sent.append(row.text)
                self.phase = "home"
        replay = ExitReplay()
        self.assertTrue(replay.leave_battle())
        self.assertEqual(replay.sent,[(1236,100),"退场"])

    def test_cow_exit_never_clicks_in_an_unknown_screen(self):
        action = seasonal.SecretCow()
        action.capture = action.pause = lambda *args: None
        action.node = action.title = lambda *args: None
        action.find = lambda *args: None
        sent = []
        action.click = action.click_row = lambda *args: sent.append(args)
        with self.assertRaisesRegex(RuntimeError,"手动退场"):
            action.leave_battle()
        self.assertEqual(sent,[])

    def test_week_uses_game_reset_timezone(self):
        # Sunday 15:30 UTC is already Monday in UTC+9.
        self.assertEqual(seasonal.game_week(datetime(2026, 11, 1, 15, 30, tzinfo=timezone.utc)), "2026-W45")
        self.assertEqual(seasonal.game_week(datetime(2026, 11, 1, 14, 30, tzinfo=timezone.utc)), "2026-W44")


if __name__ == "__main__":
    unittest.main()
