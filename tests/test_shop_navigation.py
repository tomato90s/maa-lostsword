"""Regressions for a sent guild-tab tap that did not change the shop page."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock

from maa.define import Rect
from agent.shop_actions import ShopBatch


class ShopNavigationTests(unittest.TestCase):
    def action(self, states):
        action = ShopBatch()
        action.category = "公会"
        action.param = {"category": "公会"}
        action.clock, action.index = 0., -1
        action.capture = Mock(side_effect=lambda: setattr(action, "index", min(action.index + 1, len(states) - 1)))
        action.pause = lambda seconds=.4: setattr(action, "clock", action.clock + seconds)
        action.log = Mock()
        action.category_ready = lambda: states[action.index] == "公会"
        action.exchange_page = lambda: True
        action.selected_category = lambda: states[action.index]
        action.find = lambda *args: NS(text="公会", box=Rect(147, 351, 47, 31))
        action.click_row = Mock()
        return action

    def test_two_fresh_confirmations_are_separated_by_two_seconds(self):
        action = self.action(["公会", "公会"])
        self.assertTrue(action.wait_category())
        self.assertEqual(action.capture.call_count, 2)
        self.assertEqual(action.clock, 2)
        action.click_row.assert_not_called()

    def test_reconnected_old_page_resets_the_confirmation_count(self):
        action = self.action(["公会", "消耗品", "公会", "公会"])
        self.assertTrue(action.wait_category())
        self.assertEqual(action.capture.call_count, 4)
        action.click_row.assert_not_called()

    def test_missed_category_tap_is_retried_only_after_observing_the_old_page(self):
        action = self.action(["消耗品"])
        action.selected_category = lambda: "公会" if action.click_row.call_count >= 2 else "消耗品"
        action.category_ready = lambda: action.selected_category() == "公会"
        action.select_category()
        self.assertEqual(action.click_row.call_count, 2)

    def test_unknown_page_does_not_receive_category_taps(self):
        action = self.action([None])
        with self.assertRaisesRegex(RuntimeError, "未确认.*公会"):
            action.select_category()
        action.click_row.assert_not_called()

    def test_matching_text_with_wrong_currency_is_not_a_ready_category(self):
        action = ShopBatch()
        action.category = "公会"
        action.exchange_page = lambda: True
        action.selected_category = lambda: "公会"
        action.template = Mock(return_value=None)
        self.assertFalse(action.category_ready())

    def test_currency_alone_cannot_pass_an_unselected_category(self):
        action = ShopBatch()
        action.category = "公会"
        action.exchange_page = lambda: True
        action.selected_category = lambda: "消耗品"
        action.template = Mock(return_value=True)
        self.assertFalse(action.category_ready())


if __name__ == "__main__": unittest.main()
