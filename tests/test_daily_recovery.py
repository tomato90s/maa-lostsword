"""Replay the October 21 failures without a controller or game inputs."""
import json
import re
import sys
import tempfile
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maa.define import Rect
from agent.daily_actions import DungeonOpenMenu, FavorTalk


def row(text):
    return NS(text=text, score=1, box=Rect(225, 170, 150, 25))


class ReplayClock:
    def init_clock(self):
        self.clock = 0
        self.deadline = 1000
        self.context = NS(tasker=NS(stopping=False))
        self.events = []
        self.messages = []

    def pause(self, seconds=.4):
        self.check()
        self.clock += seconds

    def log(self, message):
        self.messages.append(message)


class MenuReplay(ReplayClock, DungeonOpenMenu):
    def __init__(self, state='home', opens_after=1, delay=0):
        super().__init__()
        self.init_clock()
        self.state = state
        self.opens_after = opens_after
        self.delay = delay
        self.menu_at = None

    def capture(self):
        self.check()
        if self.menu_at is not None and self.clock >= self.menu_at:
            self.state = 'menu'

    def find(self, pattern, roi=None):
        visible = {'home': [], 'menu': ['战斗'], 'unknown': [],
                   'popup': ['网络连接失败，请重试'], 'loading': ['加载中']}[self.state]
        return next((row(text) for text in visible if re.search(pattern, text)), None)

    def node(self, name):
        return name == 'HomeFlagCloseReturnMain' and self.state in ('home', 'popup', 'loading')

    def click(self, x, y, delay=.5):
        self.check()
        self.events.append((x, y))
        if len(self.events) >= self.opens_after:
            self.menu_at = self.clock + self.delay
        self.pause(delay)
        self.capture()


class FavorReplay(ReplayClock, FavorTalk):
    def __init__(self, outcomes, limit=7):
        super().__init__()
        self.init_clock()
        self.param = {'limit': limit}
        self.outcomes = outcomes
        self.names = [f'角色{chr(65 + i)}' for i in range(len(outcomes))]
        self.state = 'list'
        self.selected = None
        self.total = 7
        self.done = False
        self.steps = 0
        self.receipt_at = None

    def capture(self):
        self.check()
        if self.receipt_at is not None and self.clock >= self.receipt_at:
            self.done = True

    def detail_name(self):
        if self.state != 'detail':
            return None
        if self.selected is not None and self.outcomes[self.selected] == 'changed-name' and self.steps:
            return '另一个角色'
        return self.names[self.selected]

    def remaining(self, detail=False):
        return self.total

    def list_candidates(self):
        return [row(name) for name in self.names]

    def swipe(self, *args):
        self.check()
        self.pause()

    def find(self, pattern, roi=None):
        visible = {'list': ['对话次数'], 'detail': [
            '对话完成', '1/1'] if self.done else ['对话>', '0/1'],
            'story': ['Log'], 'unknown': []}[self.state]
        if (self.state == 'detail' and self.steps
                and self.outcomes[self.selected] == 'missing-status'):
            visible = ['对话>']
        return next((row(text) for text in visible if re.search(pattern, text)), None)

    def click_row(self, item, delay=.5):
        self.check()
        if self.state == 'list':
            self.selected = self.names.index(item.text)
            self.state, self.done, self.steps = 'detail', False, 0
            self.receipt_at = None
        elif self.state == 'detail':
            assert item.text == '对话>', 'must never replay a completed conversation'
            self.events.append(self.names[self.selected])
            self.state = 'detail' if self.outcomes[self.selected] == 'unstarted' else 'story'
        else:
            raise AssertionError('unexpected row click')
        self.pause(delay)

    def click(self, x, y, delay=.5):
        self.check()
        if self.state == 'story':
            self.assert_story_click(x, y)
            self.steps += 1
            if self.steps == 3:
                outcome = self.outcomes[self.selected]
                self.state = 'unknown' if outcome == 'unknown' else 'detail'
                if outcome in ('success', 'delayed', 'counter-only'):
                    self.total -= 1
                    self.done = outcome == 'success'
                if outcome == 'delayed':
                    self.receipt_at = self.clock + 2
                if outcome == 'wrong-count':
                    self.total -= 2
                if outcome == 'unstarted':
                    raise AssertionError('unstarted dialogue cannot reach story')
        elif self.state == 'detail':
            assert (x, y) == (1235, 37), 'pending person may only be left, never replayed'
            self.state = 'list'
        else:
            raise AssertionError('unexpected coordinate click')
        self.pause(delay)

    @staticmethod
    def assert_story_click(x, y):
        assert (x, y) == (264, 273)

    def close_reward(self):
        return False


class AffectionOverlayReplay(FavorReplay):
    def __init__(self):
        super().__init__(["success", "success"], limit=2)
        self.overlay = False
        self.dismissals = 0

    def find(self, pattern, roi=None):
        if self.overlay:
            return row("好感度上升。") if re.search(pattern, "好感度上升。") else None
        return super().find(pattern, roi)

    def click_row(self, item, delay=.5):
        opening = self.state == "list"
        super().click_row(item, delay)
        if opening:
            self.overlay = True

    def click(self, x, y, delay=.5):
        if self.overlay:
            assert (x, y) == (640, 680)
            self.overlay = False
            self.dismissals += 1
            self.pause(delay)
        else:
            super().click(x, y, delay)


class RecoveryTests(unittest.TestCase):
    def run_replay(self, model):
        with patch('agent.daily_actions.time.monotonic', lambda: model.clock):
            return model.execute()

    def test_menu_already_open_is_not_toggled_closed(self):
        model = MenuReplay(state='menu')
        self.assertTrue(self.run_replay(model))
        self.assertEqual(model.events, [])

    def test_home_opens_once_and_requires_menu_receipt(self):
        model = MenuReplay()
        self.assertTrue(self.run_replay(model))
        self.assertEqual(model.events, [(1236, 36)])

    def test_oct21_home_unchanged_after_first_click_gets_one_recovery(self):
        model = MenuReplay(opens_after=2)
        self.assertTrue(self.run_replay(model))
        self.assertEqual(len(model.events), 2)

    def test_delayed_open_is_not_closed_by_a_second_click(self):
        model = MenuReplay(delay=1.8)
        self.assertTrue(self.run_replay(model))
        self.assertEqual(len(model.events), 1)

    def test_two_ignored_clicks_stop(self):
        model = MenuReplay(opens_after=99)
        with self.assertRaisesRegex(RuntimeError, '两次打开'):
            self.run_replay(model)
        self.assertEqual(len(model.events), 2)

    def test_unknown_loading_and_popup_never_receive_menu_clicks(self):
        for state in ('unknown', 'loading', 'popup'):
            with self.subTest(state=state):
                model = MenuReplay(state=state)
                with self.assertRaises(RuntimeError):
                    self.run_replay(model)
                self.assertEqual(model.events, [])

    def test_stop_prevents_navigation_inputs(self):
        model = MenuReplay()
        model.context.tasker.stopping = True
        with self.assertRaisesRegex(RuntimeError, '已停止'):
            self.run_replay(model)
        self.assertEqual(model.events, [])

    def test_event_and_dungeon_share_verified_navigation(self):
        nodes = json.loads((ROOT / 'assets/resource/pipeline/副本.json').read_text('utf-8'))
        entry = nodes['副本_从首页']
        self.assertEqual(entry['action']['param']['custom_action'], 'LocalDungeonOpenMenu')
        self.assertEqual(entry['next'], ['副本_点击战斗菜单'])

    def test_all_seven_successful_talks(self):
        model = FavorReplay(['success'] * 8)
        self.assertTrue(self.run_replay(model))
        self.assertEqual(model.events, model.names[:7])
        self.assertEqual(model.total, 0)

    def test_affection_level_overlay_does_not_abort_or_repeat_talks(self):
        model = AffectionOverlayReplay()
        self.assertTrue(self.run_replay(model))
        self.assertEqual(model.events, model.names)
        self.assertEqual(model.dismissals, 2)
        self.assertEqual(model.total, 5)

    def test_oct21_second_story_returns_zero_of_one_and_keeps_six_of_seven(self):
        model = FavorReplay(['success', 'unchanged', 'success'])
        self.assertFalse(self.run_replay(model))
        self.assertEqual(model.events, model.names)
        self.assertEqual(model.total, 5)
        self.assertTrue(any('角色B' in text and '待确认' in text for text in model.messages))
        self.assertTrue(any('角色C' in text and '已确认完成' in text for text in model.messages))

    def test_unconfirmed_people_count_towards_the_seven_person_cap(self):
        model = FavorReplay(['unchanged'] * 8)
        self.assertFalse(self.run_replay(model))
        self.assertEqual(model.events, model.names[:7])
        self.assertEqual(len(set(model.events)), 7)
        self.assertEqual(model.total, 7)

    def test_lower_limit_includes_unconfirmed_people(self):
        model = FavorReplay(['unchanged', 'success'], limit=1)
        self.assertFalse(self.run_replay(model))
        self.assertEqual(model.events, model.names[:1])

    def test_talk_that_never_enters_story_is_not_clicked_twice(self):
        model = FavorReplay(['unstarted', 'success'])
        self.assertFalse(self.run_replay(model))
        self.assertEqual(model.events, model.names)
        self.assertTrue(any('已进入剧情=False' in text for text in model.messages))

    def test_zero_limit_does_not_select_a_character(self):
        model = FavorReplay(['success'], limit=0)
        self.assertTrue(self.run_replay(model))
        self.assertEqual(model.events, [])

    def test_diagnostic_log_appends_without_erasing_pending_results(self):
        with tempfile.TemporaryDirectory() as folder:
            action = FavorTalk()
            action.argv = NS(node_name='LocalFavor_Run')
            action.trace_path = Path(folder) / 'favor.jsonl'
            action.log('角色A待确认')
            action.log('角色B已完成')
            records = [json.loads(line) for line in action.trace_path.read_text('utf-8').splitlines()]
            self.assertEqual([record['message'] for record in records], ['角色A待确认', '角色B已完成'])
            self.assertTrue(all(record['time'] and record['node'] == 'LocalFavor_Run' for record in records))

    def test_question_mark_is_not_a_character_name(self):
        action = FavorTalk()
        action.find = lambda *args: None
        question = row('?')
        question.score = .99
        name = row('雪泉')
        name.score = .85
        action.ocr = lambda *args: [question, name]
        self.assertEqual(action.detail_name(), '雪泉')
        action.ocr = lambda *args: [question]
        self.assertIsNone(action.detail_name())

    def test_dark_detail_card_avoids_partial_white_title(self):
        action = FavorTalk()
        action.find = lambda *args: row('对话完成')
        action.ocr = lambda pattern, roi: [row('雪泉')] if roi == (866, 140, 335, 36) else [row('泉'), row('?')]
        self.assertEqual(action.detail_name(), '雪泉')

    def test_unrecognized_card_is_not_used_outside_a_talk_detail_page(self):
        action = FavorTalk()
        action.find = lambda *args: None
        action.ocr = lambda pattern, roi: [row('雪泉')] if roi == (866, 140, 335, 36) else [row('角色')]
        self.assertIsNone(action.detail_name())

    def test_one_bad_name_frame_is_rechecked_without_replaying_dialogue(self):
        model = FavorReplay(['success'])
        normal_name = model.detail_name
        seen_bad_frame = []
        def flaky_name():
            if model.state == 'detail' and model.steps >= 3 and not seen_bad_frame:
                seen_bad_frame.append(True)
                return '错误识别'
            return normal_name()
        model.detail_name = flaky_name
        self.assertTrue(self.run_replay(model))
        self.assertEqual(model.events, model.names)

    def test_delayed_completion_marker_is_allowed(self):
        model = FavorReplay(['delayed'])
        self.assertTrue(self.run_replay(model))
        self.assertEqual(model.events, model.names)

    def test_changed_character_unknown_frame_missing_marker_or_inconsistent_count_stop(self):
        for outcome in ('changed-name', 'unknown', 'counter-only', 'wrong-count', 'missing-status'):
            with self.subTest(outcome=outcome):
                model = FavorReplay([outcome, 'success'])
                with self.assertRaises(RuntimeError):
                    self.run_replay(model)
                self.assertEqual(model.events, model.names[:1])

    def test_stop_while_talking_cannot_advance_or_open_another_person(self):
        model = FavorReplay(['success', 'success'])
        normal_click = model.click_row
        def stop_after_talk(item, delay=.5):
            normal_click(item, delay)
            if item.text == '对话>':
                model.context.tasker.stopping = True
        model.click_row = stop_after_talk
        with self.assertRaisesRegex(RuntimeError, '已停止'):
            self.run_replay(model)
        self.assertEqual(model.events, model.names[:1])


if __name__ == '__main__':
    unittest.main(verbosity=2)
