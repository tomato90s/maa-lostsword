import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.seasonal_actions import BingoCraft


class BingoNavigationTests(unittest.TestCase):
    def model(self):
        action = BingoCraft()
        action.capture = lambda: None
        action.pause = lambda delay: None
        action.daily_counter = lambda: 0
        return action

    def test_tab_ignored_during_transition_is_retried_without_crafting(self):
        action = self.model()
        clicks = []
        def find(pattern, roi=None):
            text = "活动" if roi == (1030, 60, 195, 75) else (
                "宾果票券" if len(clicks) == 2 else "经验值宝箱15个")
            return NS(text=text) if re.search(pattern, text) else None
        action.find = find
        action.click_row = lambda row, delay=.5: clicks.append(row.text)
        self.assertEqual(action.select_activity_ticket().text, "宾果票券")
        self.assertEqual(clicks, ["活动", "活动"])

    def test_unconfirmed_recipe_is_not_reported_as_completed(self):
        action = self.model()
        action.find = lambda pattern, roi=None: NS(text="活动") if roi == (1030, 60, 195, 75) else None
        action.click_row = lambda *args: None
        with self.assertRaisesRegex(RuntimeError, "未确认.*配方"):
            action.select_activity_ticket()

    def test_detected_material_survives_a_recognition_only_miss(self):
        action = self.model()
        action.ocr = lambda pattern, roi, only_rec=False: [NS(text="13700/20" if not only_rec else "1370020")]
        self.assertEqual(action.material(), (13700, 20))

    def test_five_done_is_skipped_even_when_locked_label_is_legible(self):
        action = self.model()
        clicks = []
        action.find = lambda pattern, roi=None: NS(text="活动" if roi == (1030,60,195,75) else "宾果票券")
        action.click_row = lambda row, delay=.5: clicks.append(row.text)
        action.daily_counter = lambda: 5
        self.assertIsNone(action.select_activity_ticket())
        self.assertEqual(clicks, ["活动"])

    def test_material_reading_waits_for_transition_without_guessing(self):
        action = self.model()
        frames = [0]
        action.capture = lambda: frames.__setitem__(0, frames[0] + 1)
        action.ocr = lambda *args, **kwargs: [NS(text="13700/20" if frames[0] else "13700")]
        self.assertEqual(action.material(), (13700, 20))

    def test_conflicting_material_readings_are_rejected(self):
        action = self.model()
        action.ocr = lambda pattern, roi, only_rec=False: [NS(text="13700/20" if only_rec else "1370/20")]
        with self.assertRaisesRegex(RuntimeError, "识别冲突"):
            action.material()
