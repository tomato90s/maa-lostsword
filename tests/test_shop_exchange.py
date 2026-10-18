import copy
import itertools
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.daily_actions import SHOP_EXCHANGE_CATEGORIES, ShopCategoryClick, ShopExchangeFinish
from agent.my_action import CenterClick


TASK = json.loads((ROOT / "assets/resource/tasks/daily/shop_task.json").read_text(encoding="utf-8"))
PIPELINE = json.loads((ROOT / "assets/resource/pipeline/商店.json").read_text(encoding="utf-8"))
CONFIRMS = (
    "商店-交易所-批量购买", "商店-突袭-交易所-批量购买", "商店-公会-交易所-批量购买",
    "商店-竞技场-交易所-批量购买", "商店-夏日币-交易所-批量购买",
)


def configured(choices):
    nodes = copy.deepcopy(PIPELINE)
    for option, enabled in zip(TASK["task"][0]["option"], choices):
        case = next(case for case in TASK["option"][option]["cases"]
                    if case["name"] == ("开启" if enabled else "关闭"))
        for name, override in case["pipeline_override"].items():
            nodes[name].update(override)
    return nodes


class Context:
    def __init__(self, choices=(True,) * 5, stopping=False, click_ok=True):
        self.nodes = configured(choices)
        self.clicks = []
        self.click_ok = click_ok
        self.tasker = NS(stopping=stopping, controller=NS(post_click=self.click))

    def click(self, x, y):
        self.clicks.append((x, y))
        return NS(wait=lambda: NS(succeeded=self.click_ok))

    def get_node_data(self, name):
        return self.nodes[name]

    def override_pipeline(self, data):
        for name, override in data.items():
            self.nodes[name].update(override)
        return True


class ShopExchangeTests(unittest.TestCase):
    def test_all_switch_combinations_are_independent(self):
        self.assertEqual(len(TASK["task"][0]["option"]), 5)
        for choices in itertools.product((False, True), repeat=5):
            with self.subTest(choices=choices):
                nodes = configured(choices)
                self.assertEqual(nodes["商店-交易所"]["enabled"], any(choices))
                self.assertEqual(tuple(nodes[name]["enabled"] for name in SHOP_EXCHANGE_CATEGORIES), choices)

    def test_default_configuration_only_handles_free_gift(self):
        self.assertTrue(all(option["default_case"] == "关闭" for option in TASK["option"].values()))
        self.assertFalse(configured((False,) * 5)["商店-交易所"]["enabled"])
        self.assertNotIn("Local_ShopPolicy", PIPELINE)
        self.assertNotIn("Local_ShopBatchLimit", TASK["option"])
        self.assertNotIn("Local_ShopExchange", TASK["option"])

    def test_five_categories_can_each_confirm_without_a_shared_budget(self):
        context = Context()
        for category, confirmation in zip(SHOP_EXCHANGE_CATEGORIES, CONFIRMS):
            self.assertTrue(ShopCategoryClick().run(context, NS(node_name=category, box=[0, 0, 20, 20])))
            action = PIPELINE[confirmation]["action"]["param"]["custom_action"]
            self.assertEqual(action, "CenterClick")
            self.assertEqual(PIPELINE[confirmation]["max_hit"], 1)
            self.assertTrue(CenterClick().run(context, NS(box=[100, 100, 20, 20])).success)
        self.assertEqual(len(context.clicks), 10)
        self.assertTrue(ShopExchangeFinish().run(context, None))
        self.assertFalse(context.nodes["商店-交易所"]["enabled"])

    def test_one_category_does_not_disable_the_remaining_categories(self):
        context = Context()
        first = SHOP_EXCHANGE_CATEGORIES[0]
        self.assertTrue(ShopCategoryClick().run(context, NS(node_name=first, box=[0, 0, 20, 20])))
        self.assertFalse(context.nodes[first]["enabled"])
        self.assertTrue(all(context.nodes[name]["enabled"] for name in SHOP_EXCHANGE_CATEGORIES[1:]))
        self.assertFalse(ShopExchangeFinish().run(context, None))

    def test_stopped_disabled_or_failed_click_never_clears_pending_category(self):
        first = SHOP_EXCHANGE_CATEGORIES[0]
        for context in (Context(stopping=True), Context(click_ok=False), Context((False,) * 5)):
            with self.subTest(stopping=context.tasker.stopping, click_ok=context.click_ok):
                before = context.nodes[first]["enabled"]
                self.assertFalse(ShopCategoryClick().run(context, NS(node_name=first, box=[0, 0, 20, 20])))
                self.assertEqual(context.nodes[first]["enabled"], before)

    def test_unknown_category_state_cannot_be_reported_finished(self):
        context = Context((False,) * 5)
        context.nodes[SHOP_EXCHANGE_CATEGORIES[0]].pop("enabled")
        self.assertFalse(ShopExchangeFinish().run(context, None))

    def test_absent_optional_summer_tab_does_not_block_other_categories(self):
        context = Context((False, False, False, False, True))
        self.assertTrue(ShopExchangeFinish().run(context, None))

    def test_known_purchase_popup_is_closed_before_entering_another_category(self):
        next_nodes = PIPELINE["商店-交易所"]["next"]
        close = next_nodes.index("[JumpBack]商店-交易所-关闭购买")
        self.assertTrue(all(close < next_nodes.index("[JumpBack]" + name)
                            for name in SHOP_EXCHANGE_CATEGORIES))
        self.assertEqual(PIPELINE["商店_商店页面"]["next"][-1], "Local_ShopFinish")
        self.assertEqual(PIPELINE["Local_ShopFinish"]["next"], ["ReturnMain"])


if __name__ == "__main__":
    unittest.main(verbosity=2)
