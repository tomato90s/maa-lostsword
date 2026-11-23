import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.shop_actions import ShopBatch


class BalanceReplay(ShopBatch):
    def __init__(self, text="18万", title="领主突袭币"):
        self.category, self.text, self.title = "突袭", text, title
        self.clicks, self.closed = [], False
    def capture(self): pass
    def pause(self, *args): pass
    def log(self, *args): pass
    def wait_category(self): return True
    def category_ready(self): return True
    def ocr(self, *args, **kwargs): return [NS(text=self.text)]
    def click(self, x, y, delay=.5): self.clicks.append((x, y))
    def number(self, roi):
        assert roi == (825, 195, 95, 45)
        return 181500
    def find(self, pattern, roi=None):
        return next((NS(text=text) for text in (self.title, "说明", "确认") if re.search(pattern, text)), None)
    def click_row(self, row, delay=.5):
        assert row.text == "确认"
        self.closed = True


class ShopBalanceTests(unittest.TestCase):
    def test_abbreviated_balance_uses_exact_item_details(self):
        action = BalanceReplay()
        self.assertEqual(action.category_balance(), 181500)
        self.assertEqual(action.clicks, [(1090, 34)])
        self.assertTrue(action.closed)

    def test_exact_balance_needs_no_popup(self):
        action = BalanceReplay("181,500")
        self.assertEqual(action.category_balance(), 181500)
        self.assertEqual(action.clicks, [])

    def test_wrong_currency_popup_cannot_supply_a_balance(self):
        action = BalanceReplay(title="钻石")
        with self.assertRaisesRegex(RuntimeError, "未确认分类代币详情"):
            action.category_balance()

    def test_plus_suffix_does_not_get_stripped_or_abort_before_details(self):
        action = BalanceReplay("1,637+")
        self.assertEqual(action.category_balance(), 181500)
        self.assertEqual(action.clicks, [(1090, 34)])
        self.assertTrue(action.closed)

    def test_changed_detail_balance_stops_before_closing_or_purchasing(self):
        action = BalanceReplay("1,637+")
        action.number = Mock(side_effect=[181500, 181501])
        with self.assertRaisesRegex(RuntimeError, "两次余额不一致"):
            action.category_balance()
        self.assertFalse(action.closed)

    def test_wrong_page_stops_before_reading_or_opening_any_currency(self):
        action = BalanceReplay("1,637+")
        action.wait_category = lambda: False
        action.ocr = Mock(side_effect=AssertionError("Wrong page cannot supply a balance"))
        with self.assertRaisesRegex(RuntimeError, "分类及币种"):
            action.category_balance()
        self.assertEqual(action.clicks, [])


if __name__ == "__main__": unittest.main()
