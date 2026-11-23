"""Controller outages wait for fresh frames without replaying input."""
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

import numpy as np

from agent.daily_actions import ScreenAction


class ControllerRecoveryTests(unittest.TestCase):
    def action(self, results):
        action = ScreenAction()
        action.clock, action.deadline, action.connection_wait_used = 0., 120., 0.
        action.image = np.zeros((720, 1280, 3), dtype=np.uint8)
        action.log = Mock()
        frames = iter(results)
        controller = NS(cached_image=np.ones((720, 1280, 3), dtype=np.uint8),
                        post_click=Mock(), post_connection=Mock())
        controller.post_screencap = Mock(side_effect=lambda: NS(wait=lambda: NS(succeeded=next(frames))))
        action.context = NS(tasker=NS(controller=controller, stopping=False))
        return action, controller

    def clocked(self, action):
        def sleep(seconds):
            action.clock += seconds
        return patch.multiple("agent.daily_actions.time", monotonic=lambda: action.clock, sleep=sleep)

    def test_two_minutes_without_connection_then_resume_with_a_new_frame(self):
        action, controller = self.action([False] * 24 + [True])
        with self.clocked(action):
            image = action.capture()
        self.assertIs(image, controller.cached_image)
        self.assertAlmostEqual(action.clock, 120)
        self.assertAlmostEqual(action.deadline, 240)
        self.assertAlmostEqual(action.connection_wait_used, 120)
        controller.post_click.assert_not_called()
        controller.post_connection.assert_not_called()

    def test_three_minute_budget_is_shared_across_capture_failures(self):
        action, controller = self.action([False] * 24 + [True] + [False] * 30)
        with self.clocked(action):
            action.capture()
            with self.assertRaisesRegex(RuntimeError, "连接.*180.*截图"):
                action.capture()
        self.assertAlmostEqual(action.clock, 180)
        self.assertIsNone(action.image)
        controller.post_click.assert_not_called()

    def test_user_stop_interrupts_the_connection_wait(self):
        action, controller = self.action([False] * 40)
        def stop(seconds):
            action.clock += seconds
            action.context.tasker.stopping = True
        with patch.multiple("agent.daily_actions.time", monotonic=lambda: action.clock, sleep=stop):
            with self.assertRaisesRegex(RuntimeError, "任务已停止"):
                action.capture()
        self.assertLess(action.clock, 1)
        self.assertEqual(controller.post_screencap.call_count, 1)

    def test_invalid_resolution_is_not_retried_as_a_disconnect(self):
        action, controller = self.action([True])
        controller.cached_image = np.zeros((100, 100, 3), dtype=np.uint8)
        with self.clocked(action):
            with self.assertRaisesRegex(RuntimeError, "1280x720"):
                action.capture()
        self.assertEqual(controller.post_screencap.call_count, 1)
        self.assertEqual(action.clock, 0)


if __name__ == "__main__": unittest.main()
