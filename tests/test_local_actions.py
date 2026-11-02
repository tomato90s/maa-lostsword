import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maa.define import Rect
from agent.local_actions import BudgetClick, validate_ratios


class FakeContext:
    task_id = 1

    def __init__(self, limit, stopping=False):
        self.limit = limit
        self.clicks = []
        self.disabled = {}
        self.next = None
        self.tasker = NS(stopping=stopping, controller=NS(post_click=self.click))

    def click(self, x, y):
        self.clicks.append((x, y))
        return NS(wait=lambda: NS(succeeded=True))

    def get_task_job(self):
        return NS(job_id=self.task_id)

    def get_node_data(self, name):
        return {'action': {'type': 'Custom', 'param': {'custom_action_param': {'coin': self.limit}}}}

    def override_pipeline(self, data):
        self.disabled.update(data)
        return True

    def override_next(self, node, data):
        self.next = data
        return True


class FixTests(unittest.TestCase):
    def args(self):
        return NS(custom_action_param=json.dumps({'policy': 'policy', 'scope': 'coin'}),
                  box=[10, 20, 30, 40], node_name='donate')

    def test_zero_budget_never_clicks(self):
        c = FakeContext(0)
        self.assertTrue(BudgetClick().run(c, self.args()))
        self.assertEqual(c.clicks, [])
        self.assertEqual(c.disabled, {'donate': {'enabled': False}})
        self.assertEqual(c.next, [])

    def test_cap_is_shared_and_resets_for_new_task(self):
        c, a = FakeContext(1), BudgetClick()
        self.assertTrue(a.run(c, self.args()))
        self.assertTrue(a.run(c, self.args()))
        self.assertEqual(len(c.clicks), 1)
        c.task_id = 2
        self.assertTrue(a.run(c, self.args()))
        self.assertEqual(len(c.clicks), 2)

    def test_stop_and_bad_budget_prevent_clicks(self):
        for c in [FakeContext(1, True), FakeContext('invalid')]:
            self.assertFalse(BudgetClick().run(c, self.args()))
            self.assertEqual(c.clicks, [])

    def row(self, text, x, y):
        return NS(text=text, box=Rect(x, y, 80, 24))

    def test_free_with_zero_ticket_is_accepted(self):
        labels = [self.row('每日免费', 486, 210), self.row('紫色门票', 486, 266)]
        counts = [self.row('3/3', 740, 210), self.row('0/100', 730, 266)]
        self.assertEqual(validate_ratios(labels, counts), 3)

    def test_ticket_or_unreadable_currency_is_rejected(self):
        for labels, counts in [
            ([self.row('紫色门票', 486, 210)], [self.row('1/100', 740, 210)]),
            ([], [self.row('3/3', 740, 210)]),
            ([self.row('每日免费', 486, 210)], [self.row('4/3', 740, 210)])]:
            with self.assertRaises(RuntimeError):
                validate_ratios(labels, counts)

if __name__ == '__main__':
    unittest.main(verbosity=2)
