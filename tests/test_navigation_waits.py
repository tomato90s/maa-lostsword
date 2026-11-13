"""Delayed screenshots and dropped navigation must not repeat resource commits."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from agent.local_actions import DailySweep
from agent.seasonal_actions import DailyFreeSummon
from test_free_gift import GiftReplay


class NavigationWaitTests(unittest.TestCase):
    def checkbox_model(self, delay=3, dropped=0):
        action = DailySweep()
        action.image = False
        action.frames, action.clicks = 0, 0
        action.pause = lambda *args: None
        action.dialog = lambda: True
        action.check_controls = lambda: None
        def click(x, y):
            action.clicks += 1
            action.frames = 0
        def capture():
            action.frames += 1
            if action.clicks > dropped and action.frames >= delay:
                action.image = True
        action.click, action.capture = click, capture
        return action

    def test_delayed_checkbox_is_clicked_only_once(self):
        action = self.checkbox_model()
        with patch("agent.local_actions.checkbox_on", lambda image, x, y: image):
            action.set_checkbox(132, 580, True)
        self.assertEqual(action.clicks, 1)

    def test_dropped_selection_is_retried_only_after_fresh_unchanged_frames(self):
        action = self.checkbox_model(dropped=1)
        with patch("agent.local_actions.checkbox_on", lambda image, x, y: image):
            action.set_checkbox(132, 580, True)
        self.assertEqual(action.clicks, 2)

    def test_missing_checkbox_response_stops_after_two_configuration_clicks(self):
        action = self.checkbox_model(dropped=2)
        with patch("agent.local_actions.checkbox_on", lambda image, x, y: image):
            with self.assertRaisesRegex(RuntimeError, "勾选状态未确认"):
                action.set_checkbox(132, 580, True)
        self.assertEqual(action.clicks, 2)

    def test_menu_animation_finishes_before_diamonds_are_read(self):
        action = DailyFreeSummon()
        action.home = lambda: None
        action.visible, action.target, action.frames = False, False, 0
        action.clicks = []
        action.pause = lambda *args: None
        action.find = lambda *args: NS() if action.visible else None
        action.node = lambda *args: not action.visible
        def capture():
            action.frames += 1
            if action.frames >= 4:
                action.visible = action.target
        def click(x, y, delay=.5):
            action.clicks.append((x, y))
            action.target, action.frames = not action.visible, 0
        def number(roi):
            self.assertTrue(action.visible)
            self.assertGreaterEqual(action.frames, 5)
            return 123456
        action.capture, action.click, action.number = capture, click, number
        self.assertEqual(action.diamond_balance(), 123456)
        self.assertEqual(len(action.clicks), 2)
        self.assertFalse(action.visible)

    def test_dropped_weekly_tab_does_not_skip_weekly_or_repeat_daily_purchase(self):
        action = GiftReplay(periods=["每日", "每周"])
        action.weekly_clicks = 0
        original = action.click_row
        def click(row, delay=.5):
            if row.text == "每周":
                action.weekly_clicks += 1
                if action.weekly_clicks == 1:
                    action.pause(delay)
                    return
            original(row, delay)
        action.click_row = click
        with patch("agent.daily_actions.time.monotonic", lambda: action.clock):
            self.assertTrue(action.execute())
        self.assertEqual(action.weekly_clicks, 2)
        self.assertEqual(action.commits, 2)
        self.assertEqual(action.sold_periods, {"每日": True, "每周": True})


if __name__ == "__main__": unittest.main()
