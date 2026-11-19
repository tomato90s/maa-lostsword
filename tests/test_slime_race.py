import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.slime_race_actions import (SlimeRace, balanced_allocation, expected_reward, pending_race,
                                     race_seconds, settled_allocations, settled_result, week_spent, ROW_Y, RANK_REWARDS)


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
    def betting_seconds(self): return 300
    def allocations(self): return self.selected
    def verify_rewards(self): return "slime", RANK_REWARDS
    def runner_names(self): return ["A", "B", "C", "D", "E"]
    def capture(self): pass
    def tick(self): pass
    def log(self, message): pass
    def pause(self, seconds=0): raise RuntimeError("test cutoff")
    def journal(self, row=None):
        if row is not None: self.records.append({"username": self.username, **row})
        return self.records
    def click(self, x, y, delay=0):
        if x == 735:
            selected = list(self.selected)
            selected[ROW_Y.index(y)] += 1
            self.selected = tuple(selected)
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

    def test_all_seven_tickets_are_balanced_across_five_runners(self):
        replay = RaceReplay()
        row = replay.submit(7)
        self.assertEqual((row["strategy"], row["tickets"]), ("balanced", 7))
        self.assertEqual(row["allocation"], [1, 1, 1, 2, 2])
        self.assertEqual(row["names"], ["A", "B", "C", "D", "E"])
        self.assertEqual(len(replay.commits), 1)

    def test_existing_selection_is_never_overwritten(self):
        replay = RaceReplay()
        replay.selected = (1, 0, 0, 0, 0)
        with self.assertRaisesRegex(RuntimeError, "已有选手票数"): replay.submit(7)
        self.assertEqual(replay.commits, [])

    def test_dropped_post_submit_observation_does_not_repeat_the_click(self):
        replay = RaceReplay()
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

    def test_balancing_uses_only_the_available_tickets(self):
        for count in range(1,8):
            allocation = balanced_allocation(count)
            self.assertEqual(sum(allocation), count)
            self.assertLessEqual(max(allocation)-min(allocation), 1)
        self.assertEqual(balanced_allocation(7), (1,1,1,2,2))
        for count in (0,8,True):
            with self.assertRaises(RuntimeError): balanced_allocation(count)

    def test_late_or_non_betting_panels_never_add_a_ticket(self):
        for seconds in (None,0,19):
            replay = RaceReplay()
            replay.betting_seconds = lambda:seconds
            self.assertIsNone(replay.submit(7))
            self.assertEqual((replay.selected,replay.commits,replay.records), ((0,0,0,0,0),[],[]))

    def test_deadline_ending_during_allocation_never_confirms_a_bet(self):
        replay = RaceReplay()
        replay.betting_seconds = lambda:0 if sum(replay.selected) >= 3 else 300
        self.assertIsNone(replay.submit(7))
        self.assertEqual((sum(replay.selected),replay.commits,replay.records), (3,[],[]))

    def test_deadline_ending_at_final_confirmation_cancels_without_spending(self):
        replay = RaceReplay()
        final = [False]
        original = replay.click
        def click(x,y,delay=0):
            if (x,y) == (770,652):
                final[0] = True
            elif (x,y) == (509,484):
                return
            original(x,y,delay)
        replay.click = click
        replay.betting_seconds = lambda:0 if final[0] else 300
        self.assertIsNone(replay.submit(7))
        self.assertEqual(replay.commits, [])
        self.assertEqual(replay.records[-1]["status"], "not_submitted")
        self.assertIsNone(pending_race(replay.records,"Player","week"))

    def result_fixture(self):
        pending = {"names":["A","B","C","D","E"],"allocation":[1,1,1,2,2],"tickets":7}
        results = [{"name":name,"rank":rank,"tickets":count,"coins":expected_reward(count,rank)}
                   for rank,(name,count) in enumerate(zip(pending["names"],pending["allocation"]),1)]
        return pending, results

    def test_every_runner_reward_is_checked_before_settling_the_total(self):
        pending, results = self.result_fixture()
        receipt = settled_allocations(results,pending)
        self.assertEqual((receipt["tickets"],receipt["coins"]),(7,2350))
        for rows in (results[:-1],results[:1]+results[:1]+results[2:],
                     [{**row,"coins":row["coins"]+1} for row in results],
                     [{**row,"tickets":3} if row["name"] == "E" else row for row in results]):
            with self.assertRaises(RuntimeError): settled_allocations(rows,pending)

    def test_balanced_receipts_and_legacy_single_bets_both_count_once(self):
        pending, results = self.result_fixture()
        row = {"status":"settled","attempt":"balanced","username":"Player","week":"week",
               **pending,**settled_allocations(results,pending)}
        self.assertEqual(week_spent([row,dict(row)],"Player","week"),7)
        self.assertEqual(week_spent([{**row,"coins":1}],"Other","week"),0)
        with self.assertRaisesRegex(RuntimeError,"已有史莱姆结算记录"):
            week_spent([{**row,"coins":1}],"Player","week")

    def test_golden_event_uses_its_observed_reward_table_and_preserves_weekly_limit(self):
        pending, results = self.result_fixture()
        pending.update(currency="golden", rank_rewards=[1000,450,300,200,100])
        for row in results:
            row["coins"] = expected_reward(row["tickets"], row["rank"], pending["rank_rewards"])
        receipt = settled_allocations(results, pending)
        self.assertEqual(receipt["coins"], 2350)
        row = {"status":"settled", "attempt":"golden", "username":"Player", "week":"week", **pending, **receipt}
        self.assertEqual(week_spent([row,row],"Player","week"),7)
        with self.assertRaisesRegex(RuntimeError,"奖励表无法核对"):
            settled_allocations(results,{**pending,"rank_rewards":[500,400,350,300,250]})

    def test_resume_keeps_the_result_frame_until_the_account_has_been_checked(self):
        action = SlimeRace()
        action.image, action.param = ["result"], {}
        pending = {"status":"submitted", "username":"Player", "attempt":"pending"}
        action.journal = lambda:[pending]
        action.result = lambda:action.image[0] == "result"
        action.selection = action.confirmation = lambda:False
        action.phase = lambda:"result" if action.image[0] == "arena" else None
        action.click = lambda *args:setattr(action,"image",["arena"])
        action.find = lambda *args:NS(text="Player") if action.image[0] == "arena" else None
        visited = []
        def reconcile(row, close_result=True):
            self.assertEqual((action.username,action.image,close_result),("Player",["result"],False))
            self.assertIs(row,pending)
            visited.append("result")
            return {"tickets":7,"coins":2800}
        action.read_result = reconcile
        action.home = lambda:visited.append("home")
        action.wait_and_play = lambda *args:self.fail("A saved result must not start another bet")
        self.assertTrue(action.execute())
        self.assertEqual(visited,["result","home"])
        self.assertEqual(action.image,["arena"])

    def test_result_and_racing_countdowns_wait_until_the_betting_phase(self):
        replay = RaceReplay()
        replay.on_panel = False
        phases, index, opened = ["result","racing",None,"betting"], [0], []
        replay.phase = lambda:phases[index[0]]
        def pause(*args):
            if replay.commits:raise RuntimeError("test cutoff")
            index[0] = min(index[0]+1,len(phases)-1)
        def open_selection():
            self.assertEqual(replay.phase(),"betting")
            opened.append(index[0])
            replay.on_panel = True
        replay.pause, replay.open_selection = pause, open_selection
        with self.assertRaisesRegex(RuntimeError,"test cutoff"):
            replay.wait_and_play(None)
        self.assertEqual(opened,[3])
        self.assertEqual(replay.selected,(1,1,1,2,2))
        self.assertEqual(len(replay.commits),1)

    def test_a_late_window_is_not_reopened_until_a_new_betting_phase(self):
        replay = RaceReplay()
        phases, index, opened = ["betting",None,"betting","racing","betting"], [0], []
        replay.phase = lambda:phases[index[0]]
        replay.betting_seconds = lambda:300 if index[0] == 4 else 19
        def pause(*args):
            if replay.commits:raise RuntimeError("test cutoff")
            index[0] = min(index[0]+1,len(phases)-1)
        def open_selection():
            opened.append(index[0])
            replay.on_panel = True
        replay.pause, replay.open_selection = pause, open_selection
        with self.assertRaisesRegex(RuntimeError,"test cutoff"):
            replay.wait_and_play(None)
        self.assertEqual(opened,[4])
        self.assertEqual(len(replay.commits),1)


if __name__ == "__main__": unittest.main()
