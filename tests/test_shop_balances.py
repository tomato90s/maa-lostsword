import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from agent.shop_actions import ShopBatch


class BalanceReplay(ShopBatch):
    def __init__(self, text="18万", title="领主突袭币"):
        self.category, self.text, self.title = "突袭", text, title
        self.clicks, self.closed = [], False
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


if __name__ == "__main__": unittest.main()
