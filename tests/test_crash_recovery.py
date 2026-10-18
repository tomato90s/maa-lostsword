import re
import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
from agent.crash_recovery import (
    CrashRecovery, GameMissing, TaskFailed, configure_shell_api, game_missing)


class Context:
    def __init__(self, outputs=("LOSTSWORD_MISSING",), shell_ok=True, stopping=False):
        self.outputs = iter(outputs)
        self.starts = []
        self.commands = []
        self.stops = []
        self.tasker = NS(stopping=stopping, controller=NS(
            post_shell=self.shell, post_start_app=self.start),
            post_stop=lambda: self.stops.append(True))
        self.shell_ok = shell_ok

    def shell(self, cmd, timeout):
        self.commands.append((cmd, timeout))
        output = next(self.outputs)
        return NS(wait=lambda: NS(succeeded=self.shell_ok, get=lambda: output))

    def start(self, package):
        self.starts.append(package)
        return NS(wait=lambda: NS(succeeded=True))


class RecoveryTests(unittest.TestCase):
    def test_bundled_shell_api_uses_pointer_width_handles(self):
        from maa.define import MaaControllerHandle, MaaCtrlId
        framework = NS(MaaControllerPostShell=NS(), MaaControllerGetShellOutput=NS())
        with patch('agent.crash_recovery.Library.framework', return_value=framework):
            configure_shell_api()
        self.assertEqual(framework.MaaControllerPostShell.restype, MaaCtrlId)
        self.assertEqual(framework.MaaControllerPostShell.argtypes[0], MaaControllerHandle)

    def test_only_missing_process_matches(self):
        reco = GameMissing()
        self.assertIsNotNone(reco.analyze(Context(), None))
        self.assertIsNone(reco.analyze(Context(("LOSTSWORD_RUNNING",)), None))
        self.assertIsNone(reco.analyze(Context(("unexpected",)), None))
        self.assertIsNone(reco.analyze(Context(shell_ok=False), None))

    def test_stop_never_reads_or_restarts(self):
        context = Context(stopping=True)
        self.assertIsNone(game_missing(context))
        self.assertFalse(CrashRecovery().run(context, None))
        self.assertEqual(context.commands, [])
        self.assertEqual(context.starts, [])

    def test_unknown_adb_state_never_restarts(self):
        context = Context(shell_ok=False)
        self.assertFalse(CrashRecovery().run(context, None))
        self.assertEqual(context.starts, [])

    def test_recovery_waits_for_home(self):
        context = Context()
        recovery = CrashRecovery()
        with patch.object(recovery, "wait_for_home", return_value=True) as wait:
            self.assertTrue(recovery.run(context, None))
        self.assertEqual(len(context.starts), 1)
        wait.assert_called_once_with(context)

    def test_restart_budget_shared_across_tasks(self):
        recovery = CrashRecovery()
        context = Context(("LOSTSWORD_MISSING",) * 3)
        with patch.object(recovery, "wait_for_home", return_value=True):
            self.assertTrue(recovery.run(context, None))
            self.assertTrue(recovery.run(context, None))
            self.assertFalse(recovery.run(context, None))
        self.assertEqual(len(context.starts), 2)

    def test_live_login_timeout_does_not_repeat_launch(self):
        context = Context(("LOSTSWORD_MISSING", "LOSTSWORD_RUNNING"))
        recovery = CrashRecovery()
        with patch.object(recovery, "wait_for_home", return_value=False):
            self.assertFalse(recovery.run(context, None))
        self.assertEqual(len(context.starts), 1)

    def test_recovered_task_is_not_reported_complete(self):
        self.assertFalse(TaskFailed().run(Context(), None))

    def test_startup_error_never_clicks_or_restarts(self):
        # The real bundled OCR turns underscores into spaces on this dialog.
        for text in ("PRESTO_INITIALIZE_FAILED", "PRESTO INITIALIZE FAILED"):
            with self.subTest(text=text):
                context = Context()
                context.tasker.controller.post_screencap = lambda: NS(wait=lambda: NS(succeeded=True))
                context.tasker.controller.cached_image = object()
                context.run_recognition = lambda *args: NS(hit=False)
                def recognize(kind, param, image):
                    self.assertTrue(re.search(param.expected[0], text))
                    return NS(hit=True, filtered_results=[NS(text=text)])
                context.run_recognition_direct = recognize
                with patch('agent.crash_recovery.game_missing', return_value=False):
                    self.assertFalse(CrashRecovery().run(context, None))
                self.assertEqual(context.starts, [])
                self.assertEqual(context.stops, [])


if __name__ == '__main__':
    unittest.main(verbosity=2)
