"""Recover a missing game during a running queue without replaying purchases."""
import ctypes
import json
import time
from pathlib import Path

from maa.custom_action import CustomAction
from maa.custom_recognition import CustomRecognition
from maa.define import MaaBool, MaaControllerHandle, MaaCtrlId, MaaStringBufferHandle
from maa.library import Library
from maa.pipeline import JOCR


PACKAGE = "com.wemadeconnect.aos.lostdgl"
CHECK_COMMAND = (
    "if pidof " + PACKAGE + " >/dev/null 2>&1; "
    "then echo LOSTSWORD_RUNNING; else echo LOSTSWORD_MISSING; fi"
)
RECOVERY_SETTINGS = {"enabled": True}


def preference_from_config(config, instance_id=None):
    instance_id = instance_id or config.get("lastActiveInstanceId")
    instances = config.get("instances", [])
    instance = next((item for item in instances if item.get("id") == instance_id),
                    instances[0] if len(instances) == 1 else {})
    startup = next((item for item in instance.get("tasks", [])
                    if item.get("taskName") == "启动游戏"), {})
    option = startup.get("optionValues", {}).get("Local_AutoRecovery")
    if option is None:
        return True
    return option.get("caseName") == "开启"


def initialize_preferences(root):
    try:
        config = json.loads((Path(root) / "config/mxu-maa-lostsword.json").read_text(
            encoding="utf-8-sig"))
        RECOVERY_SETTINGS["enabled"] = preference_from_config(config)
    except Exception as exc:
        RECOVERY_SETTINGS["enabled"] = False
        print(f"[自动拉起] 无法读取设置，已关闭: {exc}", flush=True)


class SetRecoveryPolicy(CustomAction):
    def run(self, context, argv):
        param = json.loads(argv.custom_action_param or "{}")
        enabled = param.get("enabled", True)
        if not isinstance(enabled, bool):
            return False
        RECOVERY_SETTINGS["enabled"] = enabled
        ACTIONS["LocalCrashRecovery"].restart_count = 0
        print(f"[自动拉起] 本轮{'开启' if enabled else '关闭'}", flush=True)
        return True


def configure_shell_api():
    # Bundled maafw 5.10.5 exposes post_shell but omits its ctypes signatures.
    # Without these, a 64-bit controller handle is truncated before the call.
    # Signatures match v5.10.5 include/MaaFramework/Instance/MaaController.h.
    framework = Library.framework()
    framework.MaaControllerPostShell.restype = MaaCtrlId
    framework.MaaControllerPostShell.argtypes = [
        MaaControllerHandle, ctypes.c_char_p, ctypes.c_int64]
    framework.MaaControllerGetShellOutput.restype = MaaBool
    framework.MaaControllerGetShellOutput.argtypes = [
        MaaControllerHandle, MaaStringBufferHandle]


def game_missing(context):
    """None means ADB state is unknown; an unknown state must not start apps."""
    if context.tasker.stopping:
        return None
    try:
        job = context.tasker.controller.post_shell(CHECK_COMMAND, timeout=3000).wait()
        if not job.succeeded:
            return None
        output = job.get().strip()
        if output == "LOSTSWORD_MISSING":
            return True
        if output == "LOSTSWORD_RUNNING":
            return False
    except Exception as exc:
        print(f"[闪退恢复] 无法确认游戏进程: {exc}", flush=True)
    return None


class GameMissing(CustomRecognition):
    def analyze(self, context, argv):
        if not RECOVERY_SETTINGS["enabled"]:
            return None
        if game_missing(context) is True:
            return CustomRecognition.AnalyzeResult(
                box=(0, 0, 1, 1), detail={"game_process": "missing"})
        return None


class CrashRecovery(CustomAction):
    # One Agent is started for a queue. Share the budget across all its tasks,
    # so a repeatedly crashing client cannot restart once for every queued task.
    def __init__(self, max_restarts=2, login_timeout=180):
        super().__init__()
        self.max_restarts = max_restarts
        self.login_timeout = login_timeout
        self.restart_count = 0

    def run(self, context, argv):
        if not RECOVERY_SETTINGS["enabled"]:
            return False
        try:
            success = self.recover(context)
        except Exception as exc:
            print(f"[闪退恢复] 恢复失败，停止当前任务: {exc}", flush=True)
            success = False
        return success

    def recover(self, context):
        if context.tasker.stopping:
            return False
        # Recheck immediately before starting; the user may have reopened it.
        missing = game_missing(context)
        if missing is None:
            return False
        if missing is False:
            return self.wait_for_home(context)
        while self.restart_count < self.max_restarts:
            if context.tasker.stopping:
                return False
            self.restart_count += 1
            print(f"[闪退恢复] 游戏进程已退出，自动拉起 "
                  f"({self.restart_count}/{self.max_restarts})", flush=True)
            if not context.tasker.controller.post_start_app(PACKAGE).wait().succeeded:
                continue
            if self.wait_for_home(context):
                print("[闪退恢复] 已回到大厅；中断项保留失败状态，继续后续队列", flush=True)
                return True
            if context.tasker.stopping:
                return False
            # A live client stuck at login is not another crash. Do not relaunch
            # it repeatedly or click through network/account/payment prompts.
            if game_missing(context) is not True:
                print("[闪退恢复] 游戏已启动但未到大厅，当前任务结束，请检查登录画面", flush=True)
                return False
        print(f"[闪退恢复] 本轮已到自动拉起上限 {self.max_restarts}，停止重试", flush=True)
        return False

    def wait_for_home(self, context):
        deadline = time.monotonic() + self.login_timeout
        next_process_check = time.monotonic() + 8
        # These are the existing startup/login and close-reward actions only.
        # run_action deliberately ignores their business-task next lists.
        safe_nodes = (
            "LinkStart", "Startup_CloseMaidPopup", "CardReward", "CloseX",
            "Startup_CloseTopRight", "Global_ItemObtained",
            "全局-关闭宝藏探索弹框", "全局-关闭菜单",
        )
        last_click = {}
        while time.monotonic() < deadline:
            if context.tasker.stopping:
                return False
            controller = context.tasker.controller
            if not controller.post_screencap().wait().succeeded:
                return False
            image = controller.cached_image
            home = context.run_recognition("HomeFlagCloseReturnMain", image)
            if home and home.hit:
                return True
            error = context.run_recognition_direct("OCR", JOCR(
                expected=[r"PRESTO.*FAIL|INITIALIZE.*FAIL|服务器维护|正在维护|请更新游戏|版本.*过低"],
                roi=[280, 160, 720, 380]), image)
            if error and error.hit:
                message = " / ".join(row.text for row in error.filtered_results)
                raise RuntimeError(f"游戏启动报错 {message}，请处理后重新开始任务")
            now = time.monotonic()
            if now >= next_process_check:
                missing = game_missing(context)
                if missing is not False:
                    return False
                next_process_check = now + 5
            for name in safe_nodes:
                if context.tasker.stopping:
                    return False
                if now - last_click.get(name, -10) < 3:
                    continue
                match = context.run_recognition(name, image)
                if match and match.hit:
                    if context.tasker.stopping:
                        return False
                    result = context.run_action(name, match.box)
                    if not result or not result.success:
                        return False
                    last_click[name] = time.monotonic()
                    break
            # Small waits keep manual Stop responsive while the client loads.
            for _ in range(5):
                if context.tasker.stopping:
                    return False
                time.sleep(.2)
        return False


class TaskFailed(CustomAction):
    def run(self, context, argv):
        # An interrupted task was not completed. Never report recovery as a
        # successful purchase/battle or silently replay its entry point.
        return False


RECOGNITIONS = {"LocalGameMissing": GameMissing()}
ACTIONS = {"LocalCrashRecovery": CrashRecovery(), "LocalTaskFailed": TaskFailed(),
           "LocalSetRecoveryPolicy": SetRecoveryPolicy()}
