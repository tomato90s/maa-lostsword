"""Local fixes for the Korean Chinese client, 2026-10-17."""
import json
import re
import time
from collections import defaultdict

from maa.custom_action import CustomAction
from maa.define import Rect
from maa.pipeline import JOCR


def action_param(node):
    action = (node or {}).get("action", {})
    if isinstance(action, dict):
        return action.get("param", {}).get("custom_action_param", {})
    return (node or {}).get("custom_action_param", {})


def checkbox_on(image, x, y):
    """The check mark is bright; the unselected checkbox interior is dark."""
    patch = image[y - 6:y + 7, x - 6:x + 7]
    if patch.shape[:2] != (13, 13):
        raise ValueError("checkbox outside screenshot")
    return int(((patch[:, :, 2] > 175) & (patch[:, :, 1] > 155)
                & (patch[:, :, 0] > 95)).sum()) >= 18


def validate_ratios(labels, ratios):
    selected = 0
    for ratio in ratios:
        value = re.fullmatch(r"(\d+)\s*/\s*(\d+)", ratio.text.replace(" ", ""))
        if not value or int(value[1]) > int(value[2]):
            raise RuntimeError("无法读取扫荡次数，停止扫荡")
        ry = ratio.box.y + ratio.box.h // 2
        near = [r for r in labels if 435 <= r.box.x < 590
                and abs(r.box.y + r.box.h // 2 - ry) < 32]
        free = any("每日免费" in r.text for r in near)
        amount = int(value[1])
        if amount and not free:
            raise RuntimeError("检测到额外票券次数，停止扫荡")
        selected += amount if free else 0
    return selected


DUNGEON_CATEGORIES = ("gold", "exp", "stone", "event")


def sweep_categories(context, argv):
    param = json.loads(argv.custom_action_param or "{}")
    if getattr(argv, "node_name", "") == "Local_DungeonSweep":
        if "categories" in param:
            raise RuntimeError("副本选项仍使用旧界面配置，请关闭并重新打开助手；本次未执行扫荡")
        selected = {}
        for category in DUNGEON_CATEGORIES:
            node = context.get_node_data(f"Local_Dungeon_{category}_Policy") or {}
            enabled = node.get("enabled")
            if not isinstance(enabled, bool):
                raise RuntimeError(f"无法确认{category}副本开关，停止扫荡")
            selected[category] = enabled
        return selected
    return param.get("categories", dict.fromkeys(DUNGEON_CATEGORIES, True))


class DailySweep(CustomAction):
    """Use the game's unified daily-free sweep, with no retained ticket selection."""
    def run(self, context, argv):
        try:
            self.context = context
            self.deadline = time.monotonic() + 150
            self.categories = sweep_categories(context, argv)
            if not any(self.categories.values()):
                print("[副本] 未选择副本，跳过", flush=True)
                return True
            self.open_dialog()
            self.check_controls()
            # Partial old selections do not set the master checkbox. Select all,
            # then clear all; never confirm during these two configuration clicks.
            if not checkbox_on(self.image, 132, 580):
                self.click(132, 580)
                if not checkbox_on(self.image, 132, 580):
                    raise RuntimeError("无法确认全选状态，停止扫荡")
            self.click(132, 580)
            if checkbox_on(self.image, 132, 580):
                raise RuntimeError("未能清空旧的票券选择，停止扫荡")
            all_free = all(self.categories.get(k, False)
                           for k in ("gold", "exp", "stone", "event"))
            if all_free:
                self.click(360, 580)
                if not checkbox_on(self.image, 360, 580):
                    raise RuntimeError("无法确认每日免费选择，停止扫荡")
            self.scroll(top=True)
            self.scroll(top=True)
            selected = 0
            last_signature = None
            finished = False
            for _ in range(8):
                labels, ratios = self.read_rows()
                if not all_free:
                    for free in [r for r in labels if "每日免费" in r.text]:
                        fy = free.box.y + free.box.h // 2
                        titles = [r for r in labels if r.box.x < 370
                                  and abs(r.box.y + r.box.h // 2 - fy) < 65]
                        names = " ".join(r.text for r in titles)
                        category = ("gold" if re.search(r"金币", names) else
                                    "exp" if re.search(r"经验书", names) else
                                    "stone" if re.search(r"属性", names) else
                                    "event" if re.search(r"少女的过去|活动", names) else None)
                        if self.categories.get(category, False) and not checkbox_on(self.image, 406, fy):
                            self.click(406, fy)
                    labels, ratios = self.read_rows()
                selected += validate_ratios(labels, ratios)
                signature = tuple((r.text, r.box.y // 5) for r in labels + ratios)
                if signature == last_signature:
                    finished = True
                    break
                last_signature = signature
                self.scroll()
            if not finished:
                raise RuntimeError("无法确认已检查完整扫荡列表，停止扫荡")
            if not selected:
                print("[副本] 所选副本的每日免费次数已用完，跳过", flush=True)
                self.leave_dialog()
                return True
            self.check_controls()
            print("[副本] 已清空额外票券并核对完整列表，执行每日免费一键扫荡", flush=True)
            self.click(640, 644)
            # Never press confirm twice: a missing result is an error, not a retry.
            for _ in range(24):
                if self.find(r"已获得道具|扫荡奖励|扫荡完成", [180, 80, 920, 500]):
                    print("[副本] 免费一键扫荡已完成", flush=True)
                    self.click(640, 680)
                    self.leave_dialog()
                    return True
                if self.find(r"资源不足|次数不足|没有可扫荡|未选择", [250, 230, 800, 310]):
                    print("[副本] 当前没有可用的免费扫荡次数", flush=True)
                    self.click(640, 470)
                    self.leave_dialog()
                    return True
                self.pause(.5)
                self.capture()
            raise RuntimeError("已点击一次扫荡，未能确认结果；停止以免重复执行")
        except Exception as exc:
            print(f"[副本] {exc}", flush=True)
            return False

    def check(self):
        if self.context.tasker.stopping or time.monotonic() > self.deadline:
            raise RuntimeError("任务已停止或超时")

    def pause(self, seconds=.6):
        self.check()
        time.sleep(seconds)
        self.check()

    def capture(self):
        self.check()
        job = self.context.tasker.controller.post_screencap().wait()
        if not job.succeeded:
            raise RuntimeError("截图失败")
        self.image = self.context.tasker.controller.cached_image
        if self.image.shape[:2] != (720, 1280):
            raise RuntimeError("截图须缩放为1280x720")

    def ocr(self, expected, roi):
        result = self.context.run_recognition_direct(
            "OCR", JOCR(expected=[expected], roi=roi), self.image)
        rows = result.filtered_results if result and result.hit else []
        for row in rows:
            if not isinstance(row.box, Rect):
                row.box = Rect(*row.box)
        return rows

    def find(self, expected, roi):
        rows = self.ocr(expected, roi)
        return max(rows, key=lambda r: r.score) if rows else None

    def click(self, x, y):
        self.check()
        if not self.context.tasker.controller.post_click(int(x), int(y)).wait().succeeded:
            raise RuntimeError("点击失败")
        self.pause()
        self.capture()

    def click_text(self, row):
        self.click(row.box.x + row.box.w // 2, row.box.y + row.box.h // 2)

    def scroll(self, top=False):
        self.check()
        y1, y2 = (220, 510) if top else (510, 220)
        if not self.context.tasker.controller.post_swipe(288, y1, 288, y2, 450).wait().succeeded:
            raise RuntimeError("滑动失败")
        self.pause()
        self.capture()

    def dialog(self):
        return self.find(r"副本.*一键扫荡", [460, 40, 360, 65])

    def check_controls(self):
        self.capture()
        if not (self.dialog() and self.find(r"每日免费.*选择", [380, 558, 370, 43])
                and self.find(r"一键扫荡", [500, 618, 280, 55])):
            raise RuntimeError("统一扫荡面板布局不匹配，停止操作")

    def open_dialog(self):
        self.capture()
        for _ in range(5):
            if self.dialog():
                return
            button = self.find(r"一键扫荡", [550, 620, 400, 75])
            if button:
                self.click_text(button)
                continue
            entrance = self.find(r"经验书|黄金猎犬|属性石", [40, 520, 1220, 130])
            if entrance:
                self.click_text(entrance)
                continue
            raise RuntimeError("未找到副本或一键扫荡入口")
        raise RuntimeError("打开统一扫荡面板失败")

    def read_rows(self):
        self.capture()
        labels = self.ocr(r".+", [135, 170, 460, 390])
        ratios = self.ocr(r"^\d+\s*/\s*\d+$", [660, 170, 220, 390])
        if not ratios or not labels:
            raise RuntimeError("无法检查扫荡种类和次数")
        return sorted(labels, key=lambda r: (r.box.y, r.box.x)), sorted(ratios, key=lambda r: r.box.y)

    def leave_dialog(self):
        self.capture()
        if self.dialog():
            self.click(1151, 71)
        if self.find(r"冒险区域", [170, 18, 180, 70]):
            self.click(1235, 36)


class GuildDonation(DailySweep):
    """Count confirmed donations; an acknowledged input is not a game receipt."""
    def __init__(self):
        super().__init__()
        self.starts = {}

    def run(self, context, argv):
        try:
            self.context, self.argv = context, argv
            self.deadline = time.monotonic() + 30
            return self.execute()
        except Exception as exc:
            print(f"[公会捐献] {exc}", flush=True)
            return False

    def quota(self, scope):
        if not self.find(r"^公会捐献$", [480, 50, 330, 80]):
            return None
        roi = [360, 190, 150, 65] if scope == "coin" else [800, 190, 160, 65]
        rows = self.ocr(r"^\d+\s*[/／]\s*\d+$", roi)
        if len(rows) != 1:
            return None
        match = re.fullmatch(r"(\d+)\s*[/／]\s*(\d+)", rows[0].text)
        if not match:
            return None
        used, total = int(match[1]), int(match[2])
        if not 0 <= used <= total <= 100:
            return None
        return used, total

    def disable(self):
        if not self.context.override_pipeline({self.argv.node_name: {"enabled": False}}):
            raise RuntimeError("无法停用已完成的捐献分支")
        if not self.context.override_next(self.argv.node_name, []):
            raise RuntimeError("无法结束已完成的捐献分支")
        return True

    def execute(self):
        param = json.loads(self.argv.custom_action_param or "{}")
        scope = param["scope"]
        if scope not in ("coin", "token"):
            raise RuntimeError("未知捐献种类")
        limit = max(0, min(99, int(action_param(self.context.get_node_data(param["policy"])).get(scope, 0))))
        if not limit:
            legacy = action_param(self.context.get_node_data("Local_GuildPolicy"))
            if any(int(legacy.get(key, 0)) > 0 for key in ("coin", "token")):
                raise RuntimeError("公会捐献仍使用旧界面配置，请关闭并重新打开助手；本次未执行捐献")
            return self.disable()
        self.capture()
        before = self.quota(scope)
        if before is None:
            raise RuntimeError("无法确认捐献次数，不发送点击")
        key = self.context.get_task_job().job_id, scope
        if len(self.starts) > 128:
            self.starts = {item: value for item, value in self.starts.items() if item[0] == key[0]}
        initial = self.starts.setdefault(key, before[0])
        used = before[0] - initial
        if used < 0:
            raise RuntimeError("捐献次数倒退，停止")
        if before[0] >= before[1] or used >= limit:
            print(f"[公会捐献] {scope} 已完成 {before[0]}/{before[1]}，本轮确认 {used}/{limit}，停止该分支", flush=True)
            return self.disable()
        allowed = min(limit - used, before[1] - before[0])
        button_roi = [420, 575, 110, 75] if scope == "coin" else [860, 575, 120, 75]
        for attempt in range(2):
            self.capture()
            if self.quota(scope) != before:
                raise RuntimeError("发送点击前捐献次数发生变化，停止核对")
            button = self.find(r"^捐献$", button_roi)
            if button is None:
                raise RuntimeError("未确认捐献按钮，不发送点击")
            self.click_text(button)
            until = time.monotonic() + 6
            current = None
            while time.monotonic() < until:
                self.capture()
                if self.find(r"已获得道具|领取成功", [350, 80, 650, 320]):
                    self.click(640, 680)
                    continue
                if self.find(r"资源不足|材料不足|货币不足", [350, 230, 650, 280]):
                    raise RuntimeError("捐献资源不足，停止")
                current = self.quota(scope)
                if current is not None and current != before:
                    if current[1] != before[1] or not 1 <= current[0] - before[0] <= allowed:
                        raise RuntimeError(f"捐献次数变化异常：{before} -> {current}")
                    print(f"[公会捐献] {scope} 已确认 {before[0]}/{before[1]} -> {current[0]}/{current[1]}", flush=True)
                    return True
                self.pause(.4)
            if current != before:
                raise RuntimeError("点击后的捐献结果不明，不重复发送")
            if attempt == 0:
                print(f"[公会捐献] {scope} 次数仍为 {before[0]}/{before[1]}，在捐献页重试一次", flush=True)
        raise RuntimeError("捐献点击两次均未确认结果，停止")


class BudgetClick(CustomAction):
    def __init__(self):
        super().__init__()
        self.counts = defaultdict(int)

    def run(self, context, argv):
        try:
            return self.run_checked(context, argv)
        except Exception as exc:
            print(f"[限额] 参数或点击失败，已停止: {exc}", flush=True)
            return False

    def run_checked(self, context, argv):
        param = json.loads(argv.custom_action_param or "{}")
        policy = action_param(context.get_node_data(param["policy"]))
        limit = max(0, min(100, int(policy.get(param["scope"], 0))))
        if param["policy"] in ("Local_GuildCoinPolicy", "Local_GuildTokenPolicy") and not limit:
            legacy = action_param(context.get_node_data("Local_GuildPolicy"))
            if any(int(legacy.get(scope, 0)) > 0 for scope in ("coin", "token")):
                raise RuntimeError("公会捐献仍使用旧界面配置，请关闭并重新打开助手；本次未执行捐献")
        task_id = context.get_task_job().job_id
        key = (task_id, param["scope"])
        # Bound agent memory across many scheduled runs.
        if len(self.counts) > 128:
            self.counts = defaultdict(int, {k: v for k, v in self.counts.items()
                                         if k[0] == task_id})
        if self.counts[key] >= limit:
            disabled = param.get("disable_nodes", [argv.node_name])
            if not context.override_pipeline({n: {"enabled": False} for n in disabled}):
                return False
            context.override_next(argv.node_name, param.get("on_limit", []))
            print(f"[限额] {param['scope']} 已达本轮上限 {limit}，跳过", flush=True)
            return True
        if context.tasker.stopping:
            return False
        x, y, w, h = argv.box
        success = context.tasker.controller.post_click(x + w // 2, y + h // 2).wait().succeeded
        if success:
            self.counts[key] += 1
        return success


ACTIONS = {"LocalDailySweep": DailySweep(), "LocalBudgetClick": BudgetClick(),
           "LocalGuildDonation": GuildDonation()}
