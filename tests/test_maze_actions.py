import unittest
import sys
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

from agent.maze_actions import MazeDaily, choose_resource, resource_kind


class MazePreferenceTests(unittest.TestCase):
    def test_stone_is_preferred_regardless_of_card_order(self):
        self.assertEqual(choose_resource(["金币宝箱", "经验宝箱", "石头"]), "石头")

    def test_missing_stone_uses_experience_then_gold(self):
        self.assertEqual(choose_resource(["金币宝箱", "经验宝箱"]), "经验宝箱")
        self.assertEqual(choose_resource(["金币宝箱"]), "金币宝箱")

    def test_other_resources_require_the_fallback_switch(self):
        self.assertEqual(choose_resource(["其他资源"]), "其他资源")
        self.assertIsNone(choose_resource(["其他资源"], allow_other=False))

    def test_user_can_change_the_preference_order(self):
        self.assertEqual(choose_resource(["石头", "金币宝箱"], ("金币宝箱", "石头")), "金币宝箱")

    def test_no_available_resource_does_not_create_a_choice(self):
        self.assertIsNone(choose_resource([]))

    def test_live_resource_names_map_to_the_user_preferences(self):
        for text, kind in (("铁矿石4个", "石头"), ("石料8个", "石头"),
                           ("经验值宝箱5个", "经验宝箱"), ("金币宝箱3个", "金币宝箱")):
            self.assertEqual(resource_kind(text), kind)
        self.assertIsNone(resource_kind("攻击力提升30%"))

    def test_story_choices_are_checked_before_any_dialogue_click(self):
        action = MazeDaily()
        magic = NS(text="魔法卡！")
        action.find = lambda pattern, roi: magic if "魔法卡" in pattern else None
        action.click_row = lambda row, delay: self.assertIs(row, magic)
        action.click = lambda *args: self.fail("Must not click through a choice")
        action.advance_story()

    def test_unknown_choices_stop_without_sending_input(self):
        action = MazeDaily()
        action.allow_other = True
        action.find = lambda *args: None
        action.ocr = lambda *args: [NS(text="未知交易")]
        action.click = lambda *args: self.fail("Unknown choices must remain untouched")
        with self.assertRaisesRegex(RuntimeError, "未识别"):
            action.advance_story()

    def test_card_fallback_excludes_paid_choices_and_sacrifices(self):
        action = MazeDaily()
        action.priorities, action.allow_other = list(("石头", "经验宝箱", "金币宝箱")), True
        rows = [NS(text=text, box=NS(x=x-60,w=120)) for x,text in (
            (340,"随机使1名存活的我军阵亡"),(640,"钻石100个 购买"),(940,"攻击力提升20% 增益型"))]
        action.ocr = lambda *args: rows
        action.find = lambda *args: NS(text="选择")
        action.cards = lambda: True
        action.log = lambda *args: None
        action.journal = lambda **kwargs: None
        sent = []
        action.click = lambda *args: sent.append(args[:2])
        action.click_row = lambda *args: None
        action.select_card()
        self.assertEqual(sent, [(940,410)])

    def test_completion_requires_both_the_end_title_and_final_boss_route(self):
        action = MazeDaily()
        action.find = lambda pattern, roi: NS(text="完成") if pattern == "^完成$" else None
        self.assertFalse(action.completed())
        action.find = lambda pattern, roi: NS(text="matched")
        self.assertTrue(action.completed())

    def test_completed_weekly_maze_never_starts_another_challenge(self):
        action = MazeDaily()
        action.param = {}
        action.completed = lambda: True
        records = []
        action.journal = lambda **record: records.append(record)
        action.log = lambda *args: None
        action.open_maze = action.start_auto = action.depart_final = lambda: self.fail("Must skip")
        self.assertTrue(action.execute())
        self.assertEqual(records[-1]['status'],'skipped')

    def test_completed_maze_found_after_navigation_is_an_explicit_skip(self):
        action = MazeDaily()
        action.param = {}
        arrived = [False]
        action.completed = lambda: arrived[0]
        action.page = action.story = action.cards = action.final_team = action.in_battle = lambda: False
        action.find = lambda *args: None
        action.open_maze = lambda: arrived.__setitem__(0,True)
        action.start_auto = action.depart_final = lambda: self.fail("No new challenge after completion")
        records = []
        action.journal = lambda **record: records.append(record)
        action.log = lambda *args: None
        self.assertTrue(action.execute())
        self.assertEqual(records[-1]['reason'],'weekly_completed')

    def test_actual_auto_settings_caption_is_used_without_changing_difficulty(self):
        action = MazeDaily()
        action.priorities, action.allow_other = list(("石头","经验宝箱","金币宝箱")), True
        start = NS(text="自动进行")
        action.find = lambda pattern, roi: start if pattern == "^自动进行$" else NS(text="自动进行迷宫 优先级1")
        action.journal = lambda **kwargs: None
        sent = []
        action.click_row = lambda row, delay: sent.append(row.text)
        action.click = lambda *args: self.fail("Route and difficulty settings should be preserved")
        action.start_auto()
        self.assertEqual(sent,["自动进行"])


if __name__ == "__main__":
    unittest.main()
