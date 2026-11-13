import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.slime_race_actions import SlimeRace, expected_reward, pending_race, race_seconds, settled_result, week_spent


class RaceReplay(SlimeRace):
    def __init__(self):
        self.username = "Player"
        self.param = {}
        self.records, self.commits = [], []
        self.remaining, self.selected = 7, (0, 0, 0, 0, 0)
        self.on_panel = True
        self.frame_index = 0
    def selection(self): return self.on_panel
    def result(self): return False
    def confirmation(self): return True
    def dialogue(self): return False
    def phase(self): return "betting" if self.on_panel else "racing"
    def tickets(self): return self.remaining
    def allocations(self): return self.selected
    def verify_rewards(self): pass
    def runner_names(self): return ["A", "B", "C", "D", "E"]
    def capture(self): pass
    def tick(self): pass
    def log(self, message): pass
    def pause(self, seconds=0): raise RuntimeError("test cutoff")
    def journal(self, row=None):
        if row is not None: self.records.append({"username": self.username, **row})
        return self.records
    def click(self, x, y, delay=0):
        if x == 777:
            self.selected = (0, 0, 7, 0, 0)
        elif (x, y) == (770, 652):
            assert self.records[-1]["status"] == "submitted"
        elif (x, y) == (770, 484):
            assert self.records[-1]["status"] == "confirmation_submitted"
            self.commits.append((x, y))
            self.remaining, self.on_panel = 0, False
        elif x == 1177:
            self.on_panel = False
        else:
            raise AssertionError((x, y))


class SlimeRaceTests(unittest.TestCase):
    def test_rank_rewards_are_per_ticket(self):
        self.assertEqual([expected_reward(7, rank) for rank in range(1, 6)], [3500, 2800, 2450, 2100, 1750])
        for tickets, rank in ((0, 1), (8, 1), (True, 1), (1, 0), (1, 6)):
            with self.assertRaises(RuntimeError): expected_reward(tickets, rank)

    def test_clock_must_be_a_valid_minute_second_pair(self):
        self.assertEqual(race_seconds(" 06：41 "), 401)
        self.assertIsNone(race_seconds("00:99"))

    def test_unresolved_previous_week_blocks_a_new_submission(self):
        row = {"status": "submitted", "attempt": "a", "username": "Player", "week": "2026-W45"}
        self.assertEqual(pending_race([row], "Player", "2026-W46"), row)
        self.assertIsNone(pending_race([row, {"status": "settled", "attempt": "a"}], "Player", "2026-W46"))

    def test_multiple_pending_records_are_not_silently_picked(self):
        rows = [{"status": "submitted", "attempt": a, "username": "Player"} for a in ("a", "b")]
        with self.assertRaisesRegex(RuntimeError, "多笔"): pending_race(rows, "Player", "week")

    def test_only_the_random_runner_gets_all_seven_tickets(self):
        replay = RaceReplay()
        with patch("agent.slime_race_actions.secrets.randbelow", return_value=2):
            row = replay.submit(7)
        self.assertEqual((row["runner"], row["name"], row["tickets"]), (3, "C", 7))
        self.assertEqual(row["allocation"], [0, 0, 7, 0, 0])
        self.assertEqual(len(replay.commits), 1)

    def test_existing_selection_is_never_overwritten(self):
        replay = RaceReplay()
        replay.selected = (1, 0, 0, 0, 0)
        with self.assertRaisesRegex(RuntimeError, "已有选手票数"): replay.submit(7)
        self.assertEqual(replay.commits, [])

    def test_dropped_post_submit_observation_does_not_repeat_the_click(self):
        replay = RaceReplay()
        with patch("agent.slime_race_actions.secrets.randbelow", return_value=2):
            with self.assertRaisesRegex(RuntimeError, "test cutoff"): replay.wait_and_play(None)
        pending = pending_race(replay.records, "Player", "week")
        self.assertIsNotNone(pending)
        with self.assertRaisesRegex(RuntimeError, "test cutoff"): replay.wait_and_play(pending)
        self.assertEqual(len(replay.commits), 1)

    def test_zero_tickets_skips_without_submission(self):
        replay = RaceReplay()
        replay.remaining = 0
        self.assertTrue(replay.wait_and_play(None))
        self.assertEqual(replay.commits, [])

    def test_an_unexplained_pending_balance_cannot_submit_again(self):
        replay = RaceReplay()
        with self.assertRaisesRegex(RuntimeError, "上次应援结果尚未确认"):
            replay.wait_and_play({"before": 7, "tickets": 7})
        self.assertEqual(replay.commits, [])

    def test_a_no_bet_result_does_not_settle_an_unknown_submission(self):
        replay = RaceReplay()
        replay.records = [{"status": "confirmation_submitted", "attempt": "pending"}]
        replay.ocr = lambda *args: [NS(text="本次比赛中未给任何人应援，未能获得奖励。")]
        with self.assertRaisesRegex(RuntimeError, "本场显示未应援"):
            replay.read_result({"attempt": "pending"})
        self.assertEqual(len(replay.records), 1)

    def test_retained_live_result_proves_the_exact_awarded_total(self):
        pending = {"name": "姆巴嘭", "tickets": 7}
        self.assertEqual(settled_result("排名 4 姆巴嘭 X7 选手 已领奖励 2100", pending),
                         {"rank": 4, "tickets": 7, "coins": 2100, "name": "姆巴嘭"})

    def test_mismatched_runner_count_or_reward_cannot_settle(self):
        for text in ("排名4 另一只 X7 已领奖励2100", "排名4 姆巴嘭 X6 已领奖励2100",
                     "排名4 姆巴嘭 X7 已领奖励300", "排名4 姆巴嘭 X7 奖励2100"):
            with self.assertRaises(RuntimeError): settled_result(text, {"name": "姆巴嘭", "tickets": 7})

    def test_weekly_skip_counts_each_confirmed_attempt_once_for_this_account(self):
        row = {"status": "settled", "username": "Player", "week": "2026-W46", "attempt": "a",
               "tickets": 7, "rank": 4, "coins": 2100}
        self.assertEqual(week_spent([row, dict(row)], "Player", "2026-W46"), 7)
        self.assertEqual(week_spent([row], "Other", "2026-W46"), 0)
        self.assertEqual(week_spent([row], "Player", "2026-W47"), 0)

    def test_an_uncertain_result_does_not_justify_skipping_the_week(self):
        row = {"status": "result_observed", "username": "Player", "week": "2026-W46", "tickets": 7}
        self.assertEqual(week_spent([row], "Player", "2026-W46"), 0)
        with self.assertRaises(RuntimeError):
            week_spent([{**row, "status": "settled", "attempt": "a", "rank": 4, "coins": 300}], "Player", "2026-W46")


if __name__ == "__main__": unittest.main()
