"""Regressions from the November 14-17 saved failure screens."""
import re
import time
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

import numpy as np
from maa.define import Rect
from agent.daily_actions import GuildClaimReward, GuildInvest, TreasureQuickFree
from agent.maze_actions import MazeDaily
from agent.seasonal_actions import RaidSweep


def row(text, y=646, x=921):
    return NS(text=text, box=Rect(x,y,100,28), score=.9)


class DailyFlowRegressionTests(unittest.TestCase):
    def test_raid_last_two_attempts_reuse_the_readable_counter_crop(self):
        for remaining in (1,2,3):
            with self.subTest(remaining=remaining):
                action = RaidSweep()
                calls = []
                def ocr(pattern, roi):
                    calls.append((pattern,roi))
                    return [row(f"扫荡 {remaining}/3")]
                action.ocr = ocr
                action.find = lambda *args: self.fail("Must not use the failing narrow recognition")
                self.assertEqual(action.free_remaining(), remaining)
                self.assertEqual(action.sweep_button().text, f"扫荡 {remaining}/3")
                self.assertEqual({roi for _,roi in calls}, {(880,635,160,65)})

    def test_raid_split_caption_is_readable_but_paid_or_unknown_buttons_are_rejected(self):
        action = RaidSweep()
        action.ocr = lambda *args: [row("扫荡",x=920),row("1／3",x=975)]
        self.assertEqual(action.free_remaining(),1)
        self.assertEqual(action.sweep_button().text,"扫荡")
        for caption in ("1扫荡","扫荡0/3","扫荡","扫荡1/8"):
            action.ocr = lambda *args: [row(caption)]
            self.assertIsNone(action.sweep_button())

    def test_treasure_title_decoration_does_not_hide_the_returned_page(self):
        action = TreasureQuickFree()
        visible = { (500,90,350,75): "◇宝藏探索",
                    (650,545,200,75): "快速探查",
                    (875,545,225,75): "获取宝藏" }
        action.find = lambda pattern,roi: row(visible[roi]) if re.search(pattern,visible[roi]) else None
        self.assertTrue(action.treasure_page())
        visible[(875,545,225,75)] = "开始探查"
        self.assertFalse(action.treasure_page())

    def maze(self, texts, pale=True):
        action = MazeDaily()
        action.allow_other = True
        action.image = np.zeros((720,1280,3),np.uint8)
        choices = [row(text,y=205+index*100,x=560) for index,text in enumerate(texts)]
        if pale:
            for choice in choices:
                y = choice.box.y + choice.box.h//2
                action.image[y-30:y+30,140:1140] = (225,240,250)
        action.ocr = lambda *args: choices
        action.find = lambda *args: None
        action.log = lambda *args: None
        action.records,action.clicks = [],[]
        action.journal = lambda **record: action.records.append(record)
        action.click_row = lambda r,delay: action.clicks.append(r.text)
        action.click = lambda *args: self.fail("A choice must not be skipped as narration")
        return action

    def test_unseen_two_and_three_option_stories_select_one_visible_choice(self):
        for texts in (("生火休息。","只拿东西就走。"),("战斗。","路过。","使用诱饵。")):
            action = self.maze(texts)
            with patch("agent.maze_actions.random.choice", side_effect=lambda rows: rows[-1]):
                action.advance_story()
            self.assertEqual(action.clicks,[texts[-1]])
            self.assertEqual(action.records[-1]["event"],"unknown_random")

    def test_partial_option_ocr_never_sends_an_input(self):
        action = self.maze(("只读到一条",))
        with self.assertRaisesRegex(RuntimeError,"选项布局"):
            action.advance_story()
        self.assertEqual(action.clicks,[])

    def test_scenery_text_after_a_choice_continues_the_normal_dialogue(self):
        action = self.maze(("地面文字","远处标记"),pale=False)
        dialogue = []
        action.click = lambda *args: dialogue.append(args)
        action.advance_story()
        self.assertEqual(dialogue,[(640,625,1.2)])
        self.assertEqual(action.clicks,[])

    def test_story_random_fallback_excludes_explicit_diamond_cost(self):
        action = self.maze(("支付100钻石","继续前进"))
        action.advance_story()
        self.assertEqual(action.clicks,["继续前进"])

    def test_guild_later_stage_reward_remains_available_to_parent_flow(self):
        action = GuildClaimReward()
        action.context = NS(override_pipeline=unittest.mock.Mock())
        state = {"stage":2,"pending":True,"popup":False}
        clicks = []
        action.claim = lambda: row("领取奖励") if state["pending"] else None
        action.stage = lambda: state["stage"]
        def click(*args):
            clicks.append(state["stage"])
            state.update(stage=state["stage"]+1,popup=True)
            state["pending"] = state["stage"] < 4
        action.click_row = click
        def close():
            visible = state["popup"]
            state["popup"] = False
            return visible
        action.close_reward = close
        action.find = lambda *args: row("简介")
        action.pause = action.capture = action.log = lambda *args: None
        self.assertTrue(action.execute())
        self.assertTrue(action.execute())
        self.assertEqual(clicks,[2,3])
        action.context.override_pipeline.assert_not_called()

    def test_guild_unchanged_claim_result_is_not_repeated(self):
        action = GuildClaimReward()
        action.claim = lambda: row("领取报酬")
        action.stage = lambda: 2
        action.click_row = unittest.mock.Mock()
        action.close_reward = lambda: False
        action.find = lambda *args: row("简介")
        action.pause = action.capture = action.log = lambda *args: None
        with self.assertRaisesRegex(RuntimeError,"领奖结果尚未确认"):
            action.execute()
        action.click_row.assert_called_once()

    def test_investment_that_unlocks_a_stage_claims_it_before_verifying_the_counter(self):
        action = GuildInvest()
        action.param = {"scope":"coin"}
        action.deadline = time.monotonic()+90
        action.image = None
        action.context = NS(override_pipeline=unittest.mock.Mock())
        current = {"used":0,"claim":False}
        action.state = lambda scope:current["used"]
        action.offer = lambda scope:row("投资")
        action.capture = action.pause = action.log = lambda *args:None
        action.close_reward = lambda:False
        def click(*args):current.update(used=None,claim=True)
        action.click_row = unittest.mock.Mock(side_effect=click)
        action.find = lambda *args:row("领取奖励") if current["claim"] else None
        with patch("agent.daily_actions.GuildClaimReward") as factory:
            claim = factory.return_value
            claim.timeout = 25
            claim.execute.side_effect = lambda:current.update(used=1,claim=False)
            self.assertTrue(action.execute())
            claim.execute.assert_called_once()
        action.click_row.assert_called_once()
        action.context.override_pipeline.assert_called_once_with({"公会-投资金币":{"enabled":False}})


if __name__ == "__main__":
    unittest.main()
