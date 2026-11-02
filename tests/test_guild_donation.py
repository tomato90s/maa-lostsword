import copy
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from agent.local_actions import BudgetClick, action_param

TASK = json.loads((ROOT / 'assets/resource/tasks/daily/guild_task.json').read_text('utf-8'))
PIPELINE = json.loads((ROOT / 'assets/resource/pipeline/公会.json').read_text('utf-8'))


class DonationContext:
    def __init__(self, coin, token):
        self.nodes = copy.deepcopy(PIPELINE)
        for scope, limit in [('Coin', coin), ('Token', token)]:
            option = TASK['option']['Local_Guild' + scope + 'Limit']
            name, override = next(iter(option['pipeline_override'].items()))
            self.nodes[name] = copy.deepcopy(override)
            self.nodes[name]['action']['param']['custom_action_param'][scope.lower()] = limit
        self.clicks = []
        self.tasker = NS(stopping=False, controller=NS(post_click=self.click))

    def click(self, x, y):
        self.clicks.append((x, y))
        return NS(wait=lambda: NS(succeeded=True))

    def get_node_data(self, name): return self.nodes[name]
    def get_task_job(self): return NS(job_id=123)
    def override_pipeline(self, data): return True
    def override_next(self, node, data): return True


def args(scope):
    name = '公会-捐献-' + ('金币' if scope == 'coin' else '信物')
    return NS(node_name=name, box=[10 if scope == 'coin' else 100, 20, 30, 40],
              custom_action_param=json.dumps(PIPELINE[name]['action']['param']['custom_action_param']))


class GuildDonationTests(unittest.TestCase):
    def test_each_option_overrides_a_different_policy_node(self):
        coin = TASK['option']['Local_GuildCoinLimit']['pipeline_override']
        token = TASK['option']['Local_GuildTokenLimit']['pipeline_override']
        self.assertTrue(set(coin).isdisjoint(token))
        self.assertEqual(set(coin), {'Local_GuildCoinPolicy'})
        self.assertEqual(set(token), {'Local_GuildTokenPolicy'})

    def test_each_donation_uses_its_own_budget(self):
        for coin, token in [(0, 3), (3, 0), (1, 3), (3, 1), (3, 3)]:
            with self.subTest(coin=coin, token=token):
                context, action = DonationContext(coin, token), BudgetClick()
                for _ in range(max(coin, token) + 1):
                    self.assertTrue(action.run(context, args('coin')))
                    self.assertTrue(action.run(context, args('token')))
                self.assertEqual(context.clicks.count((25, 40)), coin)
                self.assertEqual(context.clicks.count((115, 40)), token)

    def test_default_resource_budgets_remain_zero(self):
        self.assertEqual(action_param(PIPELINE['Local_GuildCoinPolicy']), {'coin': 0})
        self.assertEqual(action_param(PIPELINE['Local_GuildTokenPolicy']), {'token': 0})

    def test_investment_switches_are_separate_from_donation_budgets(self):
        for option in ('Local_GuildInvestCoin', 'Local_GuildInvestToken'):
            for case in TASK['option'][option]['cases']:
                self.assertTrue(set(case['pipeline_override']).isdisjoint(
                    {'Local_GuildCoinPolicy', 'Local_GuildTokenPolicy'}))

    def test_stale_running_interface_cannot_silently_skip_donations(self):
        context, action = DonationContext(0, 0), BudgetClick()
        context.nodes['Local_GuildPolicy']['action']['param']['custom_action_param'] = {'token': 3}
        self.assertFalse(action.run(context, args('coin')))
        self.assertFalse(action.run(context, args('token')))
        self.assertEqual(context.clicks, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
