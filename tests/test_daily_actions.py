import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from maa.define import Rect
from agent.daily_actions import (ArenaDaily, FavorTalk, GemCombine, SquadDaily,
                                GuildClaimReward, StonehengeGate, gem_grade, squad_free_status,
                                arena_cost, daily_talk_count)
from agent import crash_recovery


def row(text, y=0, tag=None):
    return NS(text=text, score=1, box=Rect(225, y, 150, 25), tag=tag)


class ArenaModel(ArenaDaily):
    def __init__(self, limit=15, tickets=2, free=3, unknown=False):
        super().__init__()
        self.limit, self.tickets, self.free = limit, tickets, free
        self.unknown = unknown
        self.state = 'opponents'
        self.results = 0
        self.events = []

    def capture(self):
        pass

    def policy(self, name):
        return {'attempts': self.limit}

    def ocr(self, *args, **kwargs):
        if self.state == 'quote':
            return [row('消耗?个钻石' if self.unknown else
                        ('消耗0个钻石' if self.free else '消耗50个钻石'))]
        return []

    def find(self, pattern, roi=None):
        visible = {
            'opponents': [('对战对手', 'label'), ('挑战', 'challenge')],
            'ready': [('进入', 'enter')],
            'quote': [('取消', 'cancel'), ('确认', 'confirm')],
            'battle': [('Skip', 'skip')],
            'result': [('请点击屏幕', 'result')],
        }[self.state]
        import re
        return next((row(text, tag=tag) for text, tag in visible if re.search(pattern, text)), None)

    def click_row(self, item, delay=.5):
        self.events.append(item.tag)
        if item.tag == 'challenge':
            self.state = 'ready'
        elif item.tag == 'enter':
            if self.tickets:
                self.tickets -= 1
                self.state = 'battle'
            else:
                self.state = 'quote'
        elif item.tag == 'confirm':
            if not self.free:
                raise AssertionError('paid challenge was confirmed')
            self.free -= 1
            self.state = 'battle'
        elif item.tag == 'skip':
            self.state = 'result'
        elif item.tag == 'cancel':
            self.state = 'opponents'

    def click(self, x, y, delay=.5):
        assert self.state == 'result'
        self.events.append('result')
        self.results += 1
        self.state = 'opponents'

    def pause(self, seconds=.4):
        pass

    def log(self, message):
        pass


class DailyTests(unittest.TestCase):
    def test_ticket_then_three_free_and_larger_limit_ends_normally(self):
        model = ArenaModel(limit=15, tickets=2, free=3)
        self.assertTrue(model.execute())
        self.assertEqual(model.results, 5)
        self.assertEqual(model.events.count('confirm'), 3)
        self.assertEqual(model.events[-1], 'cancel')

    def test_arena_limit_is_ceiling(self):
        model = ArenaModel(limit=1, tickets=2, free=3)
        self.assertTrue(model.execute())
        self.assertEqual(model.results, 1)
        self.assertNotIn('confirm', model.events)

    def test_persistent_result_screen_counts_the_battle_only_once(self):
        model = ArenaModel(limit=1)
        normal_click = model.click
        taps, messages = [], []
        def sticky_result(x, y, delay=.5):
            taps.append((x, y))
            if len(taps) >= 2:
                normal_click(x, y, delay)
        model.click = sticky_result
        model.log = messages.append
        self.assertTrue(model.execute())
        self.assertEqual(model.results, 1)
        self.assertEqual(model.events.count('challenge'), 1)
        self.assertTrue(any('已结算1次' in m for m in messages))
        self.assertFalse(any('已结算2次' in m for m in messages))

    def test_zero_arena_limit_does_not_click(self):
        model = ArenaModel(limit=0)
        self.assertTrue(model.execute())
        self.assertEqual(model.events, [])

    def test_already_exhausted_arena_is_success(self):
        model = ArenaModel(tickets=0, free=0)
        self.assertTrue(model.execute())
        self.assertEqual(model.results, 0)
        self.assertEqual(model.events[-1], 'cancel')

    def test_unknown_cost_cannot_be_confirmed(self):
        model = ArenaModel(tickets=0, free=3, unknown=True)
        with self.assertRaises(RuntimeError):
            model.execute()
        self.assertNotIn('confirm', model.events)

    def test_actual_ocr_counter_variants(self):
        for text, expected in [('7./7', 7), ('2./7', 2), ('1/7', 1), ('0 / 7', 0)]:
            self.assertEqual(daily_talk_count(text), expected)
        for text in ['117', '?/7', '8/7', '1/1']:
            self.assertIsNone(daily_talk_count(text))

    def test_character_description_is_not_a_second_person(self):
        action = FavorTalk()
        action.ocr = lambda *args, **kwargs: [row('莉莉亚', 178), row('有点在意', 208),
                                            row('女仆丽塔', 278), row('心生好感', 309)]
        self.assertEqual([r.text for r in action.list_candidates()], ['莉莉亚', '女仆丽塔'])

    def test_free_cost_does_not_depend_on_3_of_15_label(self):
        self.assertEqual(arena_cost('消耗 0 个钻石 (0/15)'), 0)
        self.assertEqual(arena_cost('消耗50个钻石 (3/15)'), 50)
        self.assertIsNone(arena_cost('(3/15)'))

    def test_three_wins_refresh_before_next_battle(self):
        model = ArenaModel(limit=1)
        model.state = 'all-won'
        normal_find, normal_ocr, normal_click = model.find, model.ocr, model.click_row
        import re
        def find(pattern, roi=None):
            if model.state == 'all-won':
                return row('对战对手', tag='label') if re.search(pattern, '对战对手') else (
                    row('刷新列表', tag='refresh') if re.search(pattern, '刷新列表') else None)
            return normal_find(pattern, roi)
        def ocr(pattern, *args, **kwargs):
            return [row('WIN')] * 3 if model.state == 'all-won' and pattern == '^WIN$' else normal_ocr(pattern, *args, **kwargs)
        def click(item, delay=.5):
            if item.tag == 'refresh':
                model.events.append('refresh')
                model.state = 'opponents'
            else:
                normal_click(item, delay)
        model.find, model.ocr, model.click_row = find, ocr, click
        self.assertTrue(model.execute())
        self.assertEqual(model.events.count('refresh'), 1)
        self.assertEqual(model.results, 1)

    def test_recovery_option_selects_active_instance(self):
        config = {'lastActiveInstanceId': 'one', 'instances': [
            {'id': 'one', 'tasks': [{'taskName': '启动游戏', 'optionValues': {
                'Local_AutoRecovery': {'caseName': '关闭'}}}]},
            {'id': 'two', 'tasks': []}]}
        self.assertFalse(crash_recovery.preference_from_config(config))
        self.assertTrue(crash_recovery.preference_from_config(config, 'two'))

    def test_disabled_recovery_never_queries_or_launches(self):
        with patch.dict(crash_recovery.RECOVERY_SETTINGS, {'enabled': False}):
            self.assertIsNone(crash_recovery.GameMissing().analyze(None, None))
            self.assertFalse(crash_recovery.CrashRecovery().run(None, None))


class GemModel(GemCombine):
    def __init__(self, grades, limit=1, result=True):
        super().__init__()
        self.param = {'limit': limit}
        self.grades, self.result = list(grades), result
        self.current = None
        self.selected = False
        self.events = []
        self.reward = False

    def capture(self): pass
    def pause(self, *args): pass
    def log(self, *args): pass

    def find(self, pattern, roi=None):
        import re
        visible = ['宝石', '自动登录', '合成'] + (['重置'] if self.selected else [])
        return next((row(t) for t in visible if re.search(pattern, t)), None)

    def ocr(self, pattern, roi, only_rec=False):
        assert roi == (355, 528, 200, 45), 'grade must be read from selected materials'
        return [row(self.current + ' 级别 T1 宝石')] if self.current else []

    def click(self, x, y, delay=.5):
        self.events.append((x, y))
        if x == 1100:
            self.current = self.grades.pop(0)
            self.selected = self.current is not None
        if x == 580:
            self.reward = self.result

    def close_reward(self):
        if self.reward:
            self.reward = False
            self.selected = False
            return True
        return False


class SquadModel(SquadDaily):
    def __init__(self, free=True):
        super().__init__()
        self.param = {'limit': 1}
        self.free, self.state = free, 'start'
        self.events = []

    def capture(self): pass
    def pause(self, *args): pass
    def log(self, *args): pass

    def ocr(self, *args, **kwargs):
        return [row('开始匹配 1/1' if self.free else '0 开始匹配')]

    def find(self, pattern, roi=None):
        import re
        visible = {'start': ['开始匹配'], 'confirm': ['是否前往小队副本房间?', '确认'],
                   'result': ['CLEAR', '返回']}[self.state]
        return next((row(t, tag=t) for t in visible if re.search(pattern, t)), None)

    def click(self, x, y, delay=.5):
        self.events.append('match')
        self.state = 'confirm'

    def click_row(self, item, delay=.5):
        self.events.append(item.tag)
        self.state = 'result'


class NewDailyTests(unittest.TestCase):
    def test_stonehenge_gate_waits_only_when_enabled(self):
        for enabled, expected in [(True, ['副本_点击巨石阵']), (False, [])]:
            context = NS(get_node_data=lambda name: {'enabled': enabled},
                         override_next=unittest.mock.Mock(return_value=True))
            action = StonehengeGate()
            action.context, action.argv = context, NS(node_name='Local_DungeonAfter')
            action.capture, action.log = lambda: None, lambda *args: None
            action.find = lambda pattern, roi=None: row('巨石阵')
            self.assertTrue(action.execute())
            context.override_next.assert_called_once_with('Local_DungeonAfter', expected)

    def test_unknown_stonehenge_option_is_not_assumed_enabled(self):
        context = NS(get_node_data=lambda name: {}, override_next=unittest.mock.Mock())
        action = StonehengeGate()
        action.context, action.argv = context, NS(node_name='Local_DungeonAfter')
        with self.assertRaises(RuntimeError): action.execute()
        context.override_next.assert_not_called()

    def test_stonehenge_leaves_sweep_preparation_before_waiting_for_entry(self):
        action = StonehengeGate()
        action.context = NS(get_node_data=lambda name: {'enabled': True},
                            override_next=unittest.mock.Mock(return_value=True))
        action.argv, action.state = NS(node_name='Local_DungeonAfter'), 'preparation'
        action.capture, action.log = lambda: None, lambda *args: None
        import re
        def find(pattern, roi=None):
            text = '一键扫荡' if action.state == 'preparation' else '巨石阵'
            return row(text) if re.search(pattern, text) else None
        def click(x, y, delay=.5):
            self.assertEqual((x, y), (1235, 35))
            action.state = 'dungeons'
        action.find, action.click = find, click
        self.assertTrue(action.execute())
        self.assertEqual(action.state, 'dungeons')

    def test_favor_opens_talk_from_ordinary_character_grid(self):
        model = FavorTalk()
        model.param = {'limit': 7}
        model.state, model.events = 'grid', []
        model.capture = lambda: None
        model.pause = lambda *args: None
        model.log = lambda *args: None
        model.detail_name = lambda: '莉莉亚' if model.state == 'detail' else None
        model.remaining = lambda detail=False: 0
        model.list_candidates = lambda: [row('莉莉亚', 170)]
        import re
        def find(pattern, roi=None):
            visible = {'grid': ['角色', '对话'], 'list': ['对话次数'], 'detail': []}[model.state]
            return next((row(t) for t in visible if re.search(pattern, t)), None)
        def click(item, delay=.5):
            model.events.append(item.text)
            model.state = 'list' if item.text == '对话' else 'detail'
        model.find, model.click_row = find, click
        self.assertTrue(model.execute())
        self.assertEqual(model.events, ['对话', '莉莉亚'])

    def test_gem_default_one_batch(self):
        model = GemModel(['高级', '稀有'])
        self.assertTrue(model.execute())
        self.assertEqual(model.events.count((1100, 667)), 1)
        self.assertEqual(model.events.count((580, 667)), 1)

    def test_epic_and_legendary_are_never_combined(self):
        for grade in ['英雄', '传说']:
            model = GemModel([grade])
            self.assertTrue(model.execute())
            self.assertNotIn((580, 667), model.events)

    def test_second_batch_stops_at_epic(self):
        model = GemModel(['稀有', '英雄'], limit=2)
        self.assertTrue(model.execute())
        self.assertEqual(model.events.count((580, 667)), 1)

    def test_unknown_gem_grade_is_not_consumed(self):
        model = GemModel(['无法识别'])
        with self.assertRaises(RuntimeError): model.execute()
        self.assertNotIn((580, 667), model.events)

    def test_unconfirmed_gem_result_is_never_retried(self):
        model = GemModel(['高级'], result=False)
        with self.assertRaises(RuntimeError): model.execute()
        self.assertEqual(model.events.count((580, 667)), 1)

    def test_no_eligible_gem_material_is_normal(self):
        model = GemModel([None])
        self.assertTrue(model.execute())
        self.assertNotIn((580, 667), model.events)

    def test_multiple_grade_labels_are_not_guessed(self):
        self.assertIsNone(gem_grade('高级 稀有 英雄'))

    def test_used_free_squad_run_does_not_consume_tickets(self):
        model = SquadModel(free=False)
        self.assertTrue(model.execute())
        self.assertEqual(model.events, [])

    def test_unknown_squad_counter_is_not_assumed_exhausted(self):
        self.assertIsNone(squad_free_status('开始匹配'))
        self.assertIsNone(squad_free_status('开始匹配?/1'))
        self.assertFalse(squad_free_status('0 开始匹配'))
        self.assertTrue(squad_free_status('开始匹配 1./1'))

    def test_ticket_icon_confirms_ticket_mode_when_ocr_misses_zero(self):
        model = SquadModel()
        model.ocr = lambda *args, **kwargs: [row('国'), row('开始匹配')]
        model.node = lambda name: name == 'LocalSquad_TicketMode'
        self.assertTrue(model.execute())
        self.assertEqual(model.events, [])

    def test_squad_timeout_leaves_only_a_recognized_room(self):
        model = SquadModel()
        normal_find = model.find
        import re
        def find(pattern, roi=None):
            if model.state == 'waiting':
                return None
            if model.state == 'exit-confirm':
                return next((row(t, tag=t) for t in ['是否退出小队副本房间?', '确认']
                             if re.search(pattern, t)), None)
            return normal_find(pattern, roi)
        def click(x, y, delay=.5):
            if x == 1235:
                model.events.append('exit')
                model.state = 'exit-confirm'
            else:
                model.events.append('match')
                model.state = 'confirm'
        def click_row(item, delay=.5):
            model.events.append(item.tag)
            model.state = 'waiting'
        model.find, model.click, model.click_row = find, click, click_row
        model.node = lambda name: name == 'LocalSquad_RoomExit'
        with patch('agent.daily_actions.time.monotonic', side_effect=[0, 161]):
            with self.assertRaises(RuntimeError): model.execute()
        self.assertEqual(model.events, ['match', '确认', 'exit', '确认'])

    def test_squad_free_confirmation_then_result(self):
        model = SquadModel()
        self.assertTrue(model.execute())
        self.assertEqual(model.events, ['match', '确认', '返回'])

    def test_guild_reward_returns_to_parent_after_popup(self):
        action = GuildClaimReward()
        action.argv = row('领取奖励')
        action.context = NS(override_pipeline=unittest.mock.Mock(return_value=True))
        action.click_row = lambda *args: None
        action.close_reward = unittest.mock.Mock(side_effect=[True, False])
        action.find = lambda pattern, roi: row('简介') if pattern == '简介' else None
        action.log = lambda *args: None
        self.assertTrue(action.execute())
        action.context.override_pipeline.assert_called_once_with({'公会-领取投资奖励': {'enabled': False}})


if __name__ == '__main__':
    unittest.main(verbosity=2)
