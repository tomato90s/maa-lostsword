import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.daily_actions import ScreenAction
from agent.seasonal_actions import DailyFreeSummon, RaidSweep


class SummonReplay(DailyFreeSummon):
    def __init__(self, free=True, receipt=True, spent=False):
        self.param = {}
        self.available = {"领取角色": free, "领取宠物": free}
        self.kind, self.phase, self.clock = None, "page", 0
        self.commits, self.skips = [], 0
        self.receipt, self.spent = receipt, spent

    def diamond_balance(self): return 157487
    def open_menu(self, name): assert name == "召唤"
    def select_tab(self, name): self.kind, self.phase = name, "page"
    def capture(self): pass
    def pause(self, seconds=.4): self.clock += seconds
    def log(self, message): pass
    def node(self, name): return self.phase == "page" and not self.available[self.kind]
    def ocr(self, *args, **kwargs): return [NS(text="1")]
    def ticket_balance(self, name): return 229 - int(self.spent and self.kind in self.commits)

    def find(self, pattern, roi=None):
        if self.phase == "intro": choices = ["Skip+>"] if self.receipt else []
        elif self.phase == "view": choices = ["查看全部"]
        elif self.phase == "confirm": choices = ["确认"]
        else:
            choices = [self.kind, "召唤1次"] + (["免费"] if self.available[self.kind] else [])
        return next((NS(text=text) for text in choices if re.search(pattern, text)), None)

    def click_row(self, row, delay=.5):
        if row.text == "召唤1次":
            assert self.available[self.kind]
            self.commits.append(self.kind)
            self.phase = "intro"
        elif row.text.startswith("Skip"):
            self.skips += 1
            self.phase = "view"
        elif row.text == "查看全部": self.phase = "confirm"
        elif row.text == "确认":
            self.available[self.kind] = False
            self.phase = "page"
        else: raise AssertionError(row.text)


class DailySummonTests(unittest.TestCase):
    def run_model(self, model):
        with patch("agent.seasonal_actions.time.monotonic", lambda: model.clock):
            return model.execute()

    def test_character_and_pet_are_each_summoned_once(self):
        model = SummonReplay()
        self.assertTrue(self.run_model(model))
        self.assertEqual(model.commits, ["领取角色", "领取宠物"])
        self.assertEqual(model.skips, 2)
        self.assertTrue(self.run_model(model))
        self.assertEqual(len(model.commits), 2)

    def test_paid_buttons_are_never_clicked(self):
        model = SummonReplay(free=False)
        self.assertTrue(self.run_model(model))
        self.assertEqual(model.commits, [])

    def test_uncertain_result_cannot_repeat_a_summon(self):
        model = SummonReplay(receipt=False)
        with self.assertRaisesRegex(RuntimeError, "结果未确认"):
            self.run_model(model)
        self.assertEqual(model.commits, ["领取角色"])

    def test_changed_ticket_balance_stops_the_second_category(self):
        model = SummonReplay(spent=True)
        with self.assertRaisesRegex(RuntimeError, "召唤券发生变化"):
            self.run_model(model)
        self.assertEqual(model.commits, ["领取角色"])

    def test_ticket_count_follows_the_category_icon_in_both_header_layouts(self):
        for name, icon, x, count in (("领取角色", "character", 939, 5),
                                     ("领取角色", "character", 1082, 34),
                                     ("领取宠物", "pet", 1082, 168)):
            with self.subTest(name=name, x=x):
                action = DailyFreeSummon()
                action.image = object()
                hit = NS(box=[x, 19, 24, 35])
                def recognize(kind, params, image):
                    self.assertEqual(kind, "TemplateMatch")
                    expected = [f"local_summon_{icon}_ticket.png"]
                    if icon == "character":
                        expected.append("local_summon_character_ticket_diamonds.png")
                    self.assertEqual(params.template, expected)
                    return NS(hit=True, filtered_results=[hit], best_result=hit)
                action.context = NS(run_recognition_direct=recognize)
                def number(roi):
                    self.assertEqual(roi, (x + 50, 14, 75, 40))
                    return count
                action.number = number
                self.assertEqual(action.ticket_balance(name), count)

    def test_missing_or_ambiguous_ticket_icon_never_reads_a_balance(self):
        for hit, rows in ((False, []), (True, [NS(), NS()])):
            action = DailyFreeSummon()
            action.image = object()
            action.context = NS(run_recognition_direct=lambda *args:
                                NS(hit=hit, filtered_results=rows))
            action.number = lambda roi: self.fail("must not read a diamond count")
            with self.assertRaisesRegex(RuntimeError, "图标未唯一确认"):
                action.ticket_balance("领取角色")

    def test_native_null_custom_parameters_are_treated_as_empty(self):
        action = ScreenAction()
        action.capture = lambda: None
        action.execute = lambda: action.param == {}
        self.assertTrue(action.run(NS(), NS(custom_action_param="null")))

    def test_raid_paid_button_after_third_sweep_means_no_free_runs(self):
        action = RaidSweep()
        action.ocr = lambda *args: [NS(text="扫荡", box=NS(x=969)), NS(text="312", box=NS(x=896))]
        self.assertEqual(action.free_remaining(), 0)
        action.ocr = lambda *args: [NS(text="扫荡", box=NS(x=920)), NS(text="2/3", box=NS(x=970))]
        self.assertEqual(action.free_remaining(), 2)
        action.ocr = lambda *args: [NS(text="扫荡", box=NS(x=969))]
        self.assertIsNone(action.free_remaining())


if __name__ == "__main__": unittest.main()
