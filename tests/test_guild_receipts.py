import json
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from agent.local_actions import GuildDonation


class SimulatedDonation(GuildDonation):
    def __init__(self, used=0, total=3, limit=3, outcomes=()):
        super().__init__()
        self.used, self.total, self.limit = used, total, limit
        self.outcomes = iter(outcomes)
        self.clock = 0
        self.reward = False
        self.unknown = False
        self.clicks = 0
        self.disabled = False
        self.context = NS(get_node_data=lambda name: {
            'action': {'param': {'custom_action_param': {'token': limit} if name == 'policy' else {}}}},
            get_task_job=lambda: NS(job_id=19),
            override_pipeline=self.disable_node,
            override_next=lambda *args: True,
            tasker=NS(stopping=False))
        self.argv = NS(node_name='公会-捐献-信物', custom_action_param=json.dumps({'policy': 'policy', 'scope': 'token'}))

    def disable_node(self, value):
        self.disabled = True
        return True

    def capture(self): pass
    def pause(self, seconds=.6): self.clock += seconds
    def quota(self, scope):
        return None if self.unknown or self.reward else (self.used, self.total)

    def find(self, pattern, roi):
        if pattern == r'^捐献$':
            return NS(box=NS(x=888, y=600, w=43, h=24))
        if pattern == r'已获得道具|领取成功' and self.reward:
            return NS()
        return None

    def click_text(self, row):
        self.clicks += 1
        outcome = next(self.outcomes, 'ok')
        if outcome == 'unknown':
            self.unknown = True
        elif outcome == 'double':
            self.used += 2
            self.reward = True
        elif outcome == 'ok':
            self.used += 1
            self.reward = True
        self.clock += .6

    def click(self, x, y):
        assert (x, y) == (640, 680)
        self.reward = False
        self.clock += .6

    def invoke(self):
        with patch('agent.local_actions.time.monotonic', lambda: self.clock):
            return self.run(self.context, self.argv)


class GuildReceiptTests(unittest.TestCase):
    def test_ignored_click_does_not_spend_success_budget(self):
        action = SimulatedDonation(used=1, total=3, limit=2, outcomes=['lost', 'ok', 'ok'])
        self.assertTrue(action.invoke())
        self.assertEqual(action.used, 2)
        self.assertTrue(action.invoke())
        self.assertEqual(action.used, 3)
        self.assertTrue(action.invoke())
        self.assertEqual(action.clicks, 3)
        self.assertTrue(action.disabled)

    def test_game_daily_limit_stops_before_another_click(self):
        action = SimulatedDonation(total=1, limit=3)
        self.assertTrue(action.invoke())
        self.assertTrue(action.invoke())
        self.assertEqual(action.used, 1)
        self.assertEqual(action.clicks, 1)

    def test_user_success_budget_stops_before_daily_cap(self):
        action = SimulatedDonation(limit=1)
        self.assertTrue(action.invoke())
        self.assertTrue(action.invoke())
        self.assertEqual(action.used, 1)
        self.assertEqual(action.clicks, 1)

    def test_unknown_post_click_state_is_not_retried(self):
        action = SimulatedDonation(outcomes=['unknown'])
        self.assertFalse(action.invoke())
        self.assertEqual(action.clicks, 1)

    def test_two_ignored_clicks_fail_without_a_third(self):
        action = SimulatedDonation(outcomes=['lost', 'lost'])
        self.assertFalse(action.invoke())
        self.assertEqual(action.clicks, 2)
        self.assertEqual(action.used, 0)

    def test_unexpected_counter_jump_is_not_success(self):
        action = SimulatedDonation(limit=1, outcomes=['double'])
        self.assertFalse(action.invoke())
        self.assertEqual(action.clicks, 1)

    def test_zero_budget_never_clicks(self):
        action = SimulatedDonation(limit=0)
        self.assertTrue(action.invoke())
        self.assertEqual(action.clicks, 0)


if __name__ == '__main__':
    unittest.main()
