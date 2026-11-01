import copy
import itertools
import json
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.local_actions import DUNGEON_CATEGORIES, sweep_categories

TASK = json.loads((ROOT / 'assets/resource/tasks/daily/instance_task.json').read_text('utf-8'))
NODES = json.loads((ROOT / 'assets/resource/pipeline/副本.json').read_text('utf-8'))


class DungeonOptionsTests(unittest.TestCase):
    def test_all_sixteen_switch_combinations_remain_independent(self):
        for choices in itertools.product((False, True), repeat=4):
            with self.subTest(choices=choices):
                nodes = copy.deepcopy(NODES)
                targets = set()
                for category, enabled in zip(DUNGEON_CATEGORIES, choices):
                    option = TASK['option']['Local_Dungeon_' + category]
                    case = next(c for c in option['cases'] if c['name'] == ('开启' if enabled else '关闭'))
                    for name, override in case['pipeline_override'].items():
                        self.assertNotIn(name, targets)
                        targets.add(name)
                        nodes[name].update(override)
                context = NS(get_node_data=nodes.get)
                argv = NS(node_name='Local_DungeonSweep', custom_action_param='{}')
                self.assertEqual(sweep_categories(context, argv), dict(zip(DUNGEON_CATEGORIES, choices)))

    def test_stale_merged_options_cannot_silently_skip_three_categories(self):
        context = NS(get_node_data=NODES.get)
        argv = NS(node_name='Local_DungeonSweep', custom_action_param='{"categories":{"event":true}}')
        with self.assertRaisesRegex(RuntimeError, '旧界面配置'):
            sweep_categories(context, argv)

    def test_standalone_event_still_selects_only_event_free_sweeps(self):
        categories = {'gold': False, 'exp': False, 'stone': False, 'event': True}
        argv = NS(node_name='Local_EventSweep', custom_action_param=json.dumps({'categories': categories}))
        self.assertEqual(sweep_categories(NS(), argv), categories)

    def test_missing_or_unreadable_policy_stops_before_any_sweep(self):
        argv = NS(node_name='Local_DungeonSweep', custom_action_param='{}')
        for value in (None, {}, {'enabled': 'false'}):
            context = NS(get_node_data=lambda name: value)
            with self.assertRaises(RuntimeError):
                sweep_categories(context, argv)


if __name__ == '__main__':
    unittest.main(verbosity=2)
