import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.maid_cafe_actions import FOODS, MaidCafe, weekly_count, cafe_progress
from agent.seasonal_actions import game_week


class CafeReplay(MaidCafe):
    def __init__(self, enabled=(), receipt=True, jump=1):
        self.clock, self.deadline = 0, 10000
        self.context = NS(tasker=NS(stopping=False))
        self.param = {}
        self.username = "Player"
        self.enabled = set(enabled)
        self.counts = {f[0]: 0 for f in FOODS}
        self.records, self.commits, self.visits = [], [], 0
        self.receipt, self.jump = receipt, jump

    def policy(self, name):
        return {"enabled": name.removeprefix("LocalMaidCafe_") in self.enabled}
    def home(self): self.visits += 1
    def open_cafe(self): self.visits += 1
    def find(self, pattern, roi): return NS(text=self.username) if roi == (120,45,180,50) else None
    def menu(self): return True
    def capture(self): self.check()
    def pause(self, seconds=.4): self.clock += seconds
    def trace(self, *args): pass
    def log(self, message): pass
    def stats(self): return ["生命值 4936", "Lv.45"]
    def count(self, food): return self.counts[food[0]]
    def price(self, food): return food[3]
    def journal(self, record=None):
        if record is not None:
            self.records.append({"week": game_week(), "username": self.username, **record})
        return self.records
    def click(self, x, y, delay=.5):
        if x == 1120:
            food = next(f for f in FOODS if f[4] == y)
            self.commits.append(food[0])
            if self.receipt:
                self.counts[food[0]] += self.jump
        else:
            assert (x,y) == (1233,38)
        self.pause(delay)


class MaidCafeTests(unittest.TestCase):
    def test_progress_requires_both_level_and_unambiguous_experience(self):
        self.assertEqual(cafe_progress(["Lv.45","2,623/3,600"]),(45,2623,3600))
        self.assertEqual(cafe_progress(["LV.46","3;073/3,600"]),(46,3073,3600))
        self.assertIsNone(cafe_progress(["Lv.45"]))
        self.assertIsNone(cafe_progress(["Lv.45","2,623/3,600","4/5"]))

    def test_an_unchanged_count_and_experience_can_resume_the_authorized_weekly_quota(self):
        model = CafeReplay(("cookies",))
        model.counts["cookies"] = 3
        model.stats = lambda:["Lv.45","2,623/3,600"]
        model.records = [{"status":"submitted","attempt":"ignored","week":game_week(),"username":"Player",
                          "food":"cookies","before":3,"stats":["Lv.45","2,623/3,600"]}]
        self.assertTrue(self.run_cafe(model))
        self.assertEqual(model.commits,["cookies"]*2)
        self.assertTrue(any(r["status"] == "unchanged_observed" for r in model.records))

    def test_rita_can_be_interacted_with_from_the_counter_edge(self):
        action = MaidCafe()
        phase = ["room"]
        action.enter = action.capture = lambda: None
        action.room = lambda: True
        action.menu = lambda: phase[0] == "menu"
        action.player = lambda: (499, 570)
        action.find = lambda pattern, roi: (NS(box=NS(x=269,w=65)) if "女仆丽塔" in pattern else
            NS(box=NS(x=300,y=200,w=70,h=30)) if "点单" in pattern and phase[0] == "choices" else None)
        action.match = lambda template, roi: (773,590,36,38)
        action.click = lambda *args: phase.__setitem__(0,"choices")
        action.click_row = lambda *args: phase.__setitem__(0,"menu")
        action.walk = lambda *args: self.fail("The counter prevents walking closer; use the visible interaction")
        action.open_cafe()
        self.assertEqual(phase[0], "menu")

    def run_cafe(self, model):
        with patch("agent.maid_cafe_actions.time.monotonic", lambda: model.clock):
            return model.execute()

    def test_weekly_counter_requires_an_explicit_valid_limit(self):
        for text, expected in (("每周 0 / 5",0),("每周5／5",5),("每周6/5",None),
                               ("每日1/5",None),("1/5",None),("每周1/6",None)):
            self.assertEqual(weekly_count(text), expected)

    def test_all_switches_off_does_not_navigate(self):
        model = CafeReplay()
        self.assertTrue(self.run_cafe(model))
        self.assertEqual((model.visits, model.commits), (0, []))

    def test_enabled_food_only_tops_up_its_remaining_quota(self):
        model = CafeReplay(("coffee",))
        model.counts["coffee"] = 3
        self.assertTrue(self.run_cafe(model))
        self.assertEqual(model.commits, ["coffee"]*2)
        self.assertEqual(model.counts["cookies"], 0)

    def test_all_four_full_orders_are_bounded_to_4750000_gold(self):
        model = CafeReplay(f[0] for f in FOODS)
        self.assertTrue(self.run_cafe(model))
        self.assertEqual(len(model.commits), 20)
        self.assertEqual(sum(r["gold"] for r in model.records if r["status"] == "confirmed"), 4750000)
        self.assertTrue(all(value == 5 for value in model.counts.values()))

    def test_full_week_is_skipped_without_any_purchase(self):
        model = CafeReplay(f[0] for f in FOODS)
        model.counts = dict.fromkeys(model.counts, 5)
        self.assertTrue(self.run_cafe(model))
        self.assertEqual(model.commits, [])

    def test_missing_receipt_is_never_submitted_a_second_time(self):
        model = CafeReplay(("coffee",), receipt=False)
        with self.assertRaisesRegex(RuntimeError, "结果未确认"):
            self.run_cafe(model)
        self.assertEqual(model.commits, ["coffee"])
        with self.assertRaisesRegex(RuntimeError, "上次女仆店点单结果未核对"):
            self.run_cafe(model)
        self.assertEqual(model.commits, ["coffee"])

    def test_recovery_requires_the_exact_single_count_increment(self):
        model = CafeReplay(("coffee",))
        model.records = [{"status":"submitted","attempt":"pending","week":game_week(),
                          "username":"Player","food":"coffee","before":0}]
        model.counts["coffee"] = 1
        self.assertTrue(self.run_cafe(model))
        self.assertEqual(model.commits, ["coffee"]*4)
        self.assertTrue(any(r.get("recovered") for r in model.records))

    def test_unexpected_counter_jump_stops_further_orders(self):
        model = CafeReplay(("coffee", "cookies"), jump=2)
        with self.assertRaisesRegex(RuntimeError, "次数变化异常"):
            self.run_cafe(model)
        self.assertEqual(model.commits, ["coffee"])

    def test_unconfirmed_currency_cannot_pass_the_price_gate(self):
        action = MaidCafe()
        action.number = lambda roi: 50000
        action.match = lambda *args: None
        with self.assertRaisesRegex(RuntimeError, "固定金币价格"):
            action.price(FOODS[0])

    def test_four_ui_switches_override_only_their_own_food(self):
        root = Path(__file__).resolve().parents[1]
        data = json.loads((root / "assets/resource/tasks/daily/maid_cafe_task.json").read_text("utf-8"))
        expected = {"LocalMaidCafe_"+f[0] for f in FOODS}
        actual = set()
        for option in data["option"].values():
            self.assertEqual(option["default_case"], "关闭")
            for case in option["cases"]:
                override = case["pipeline_override"]
                self.assertEqual(len(override), 1)
                key = next(iter(override))
                actual.add(key)
                self.assertEqual(override[key]["action"]["param"]["custom_action_param"]["enabled"], case["name"] == "开启")
        self.assertEqual(actual, expected)


if __name__ == "__main__":
    unittest.main()
