"""Bounded daily flows for the current Chinese Lost Sword UI."""
import json
import re
import time
from datetime import datetime
from pathlib import Path

from maa.custom_action import CustomAction
from maa.define import Rect
from maa.pipeline import JOCR

from agent.local_actions import action_param


class ScreenAction(CustomAction):
    label = "日常"
    timeout = 120

    def run(self, context, argv):
        try:
            self.context = context
            self.argv = argv
            self.param = json.loads(argv.custom_action_param or "{}")
            if self.param is None:
                self.param = {}
            if not isinstance(self.param, dict):
                raise RuntimeError("任务参数必须为对象")
            self.deadline = time.monotonic() + self.timeout
            self.capture()
            return self.execute()
        except Exception as exc:
            self.log(str(exc))
            return False

    def check(self):
        if self.context.tasker.stopping:
            raise RuntimeError("任务已停止")
        if time.monotonic() >= self.deadline:
            raise RuntimeError("达到等待上限，停止当前任务")

    def pause(self, seconds=.4):
        until = time.monotonic() + seconds
        while time.monotonic() < until:
            self.check()
            time.sleep(min(.1, max(0, until - time.monotonic())))

    def capture(self):
        self.check()
        controller = self.context.tasker.controller
        if not controller.post_screencap().wait().succeeded:
            raise RuntimeError("截图失败")
        self.image = controller.cached_image
        if self.image.shape[:2] != (720, 1280):
            raise RuntimeError("游戏截图须为1280x720")
        return self.image

    def ocr(self, pattern=r".+", roi=(0, 0, 1280, 720), only_rec=False):
        self.check()
        result = self.context.run_recognition_direct(
            "OCR", JOCR(expected=[pattern], roi=list(roi), only_rec=only_rec), self.image)
        rows = result.filtered_results if result and result.hit else []
        for row in rows:
            if not isinstance(row.box, Rect):
                row.box = Rect(*row.box)
        return rows

    def find(self, pattern, roi=(0, 0, 1280, 720)):
        rows = self.ocr(pattern, roi)
        return max(rows, key=lambda row: row.score) if rows else None

    def node(self, name):
        self.check()
        result = self.context.run_recognition(name, self.image)
        return result if result and result.hit else None

    def click(self, x, y, delay=.5):
        self.check()
        if not (0 <= x < 1280 and 0 <= y < 720):
            raise RuntimeError("点击坐标超出游戏画面")
        if not self.context.tasker.controller.post_click(int(x), int(y)).wait().succeeded:
            raise RuntimeError("点击失败")
        self.pause(delay)
        self.capture()

    def click_row(self, row, delay=.5):
        box = row.box
        if not isinstance(box, Rect):
            box = Rect(*box)
        self.click(box.x + box.w // 2, box.y + box.h // 2, delay)

    def wait_for(self, predicate, attempts=12, stable=1):
        """Wait for observed UI state without repeating any input."""
        hits = 0
        for _ in range(attempts):
            self.capture()
            hits = hits + 1 if predicate() else 0
            if hits >= stable:
                return True
            self.pause(.4)
        return False

    def swipe(self, x1, y1, x2, y2):
        self.check()
        if not self.context.tasker.controller.post_swipe(x1, y1, x2, y2, 400).wait().succeeded:
            raise RuntimeError("滑动失败")
        self.pause()
        self.capture()

    def policy(self, name):
        return action_param(self.context.get_node_data(name))

    def log(self, message):
        print(f"[{self.label}] {message}", flush=True)

    def close_reward(self):
        if self.find(r"已获得道具|扫荡奖励|合成结果|制作结果|领取成功", (350, 65, 650, 335)):
            self.click(640, 680)
            return True
        return False


class VillageReturnLobby(ScreenAction):
    label = "村庄返回大厅"
    timeout = 40

    def destination(self):
        return self.find(r"^前往大厅$", (820, 650, 350, 60))

    def execute(self):
        # Probe a fresh controller frame. The pipeline's first village frame
        # can miss the HUD even while direct recognition sees it clearly.
        if not (self.destination() or self.node("LocalVillageOpenMenu")):
            return True  # Other pages continue through the ordinary ReturnMain.
        for _ in range(2):
            if self.destination():
                break
            if not self.node("LocalVillageOpenMenu"):
                raise RuntimeError("村庄退出时画面变化，停止导航")
            self.click(1236, 36, .8)
            if self.wait_for(self.destination, attempts=12):
                break
        destination = self.destination()
        if not destination:
            raise RuntimeError("未确认村庄菜单的前往大厅按钮")
        self.click_row(destination, 1)
        if not self.wait_for(lambda: self.node("HomeFlagCloseReturnMain"), attempts=30, stable=2):
            raise RuntimeError("已点击前往大厅，尚未确认到达")
        self.log("已识别前往大厅并确认返回")
        return True


class GuildClaimReward(ScreenAction):
    label = "公会领奖"
    timeout = 25

    def execute(self):
        self.click_row(self.argv)
        seen_reward = False
        for _ in range(22):
            if self.close_reward():
                seen_reward = True
                continue
            main = self.find(r"简介", (330, 220, 90, 65))
            claim = self.find(r"领取奖励", (1010, 520, 220, 110))
            if main and (seen_reward or not claim):
                self.context.override_pipeline({"公会-领取投资奖励": {"enabled": False}})
                self.log("奖励弹窗已处理，继续公会主流程和后续捐献")
                return True
            self.pause(.4)
            self.capture()
        raise RuntimeError("领奖结果尚未确认，停止重复点击")


class GuildDonationLimit(ScreenAction):
    label = "公会捐献"
    timeout = 15

    def execute(self):
        if not self.find(r"今日捐献已达上限", (470, 326, 360, 68)):
            raise RuntimeError("未确认公会捐献已满")
        confirm = self.find(r"^确认$", (450, 430, 400, 90))
        if not confirm:
            raise RuntimeError("未确认捐献上限提示的关闭按钮")
        self.click_row(confirm, .8)
        for _ in range(10):
            if (self.find(r"^公会$", (60, 8, 110, 55))
                    and not self.find(r"今日捐献已达上限", (470, 326, 360, 68))):
                self.context.override_pipeline({"公会-捐献": {"enabled": False}})
                self.log("今日捐献已满，关闭提示并正常跳过")
                return True
            self.pause(.4)
            self.capture()
        raise RuntimeError("捐献上限提示尚未关闭")


class GuildInvest(ScreenAction):
    label = "公会投资"
    timeout = 90

    def state(self, scope):
        if not self.find(r"^公会$", (60, 8, 110, 55)):
            return None
        y = 472 if scope == "coin" else 566
        rows = self.ocr(r"^[01]\s*[/／]\s*1$", (1195, y, 57, 42))
        if len(rows) != 1:
            return None
        return int(re.sub(r"\s", "", rows[0].text)[0])

    def offer(self, scope):
        y = 470 if scope == "coin" else 564
        label, price = ("金币", 50000) if scope == "coin" else ("精灵王的信物", 10)
        if not self.find("^" + label + "$", (960, y, 220, 45)):
            return None
        values = [r.text.strip() for r in self.ocr(r"^\d+$", (1040, y + 48, 90, 45))]
        if values != [str(price)]:
            return None
        return self.find(r"^投资$", (1125, y + 42, 85, 55))

    def finish(self, scope):
        node = "公会-投资金币" if scope == "coin" else "公会-投资信物"
        self.context.override_pipeline({node: {"enabled": False}})
        self.log(("金币" if scope == "coin" else "信物") + "投资次数已确认1/1")
        return True

    def execute(self):
        scope = self.param.get("scope")
        if scope not in ("coin", "token"):
            raise RuntimeError("未知公会投资种类")
        if self.state(scope) == 1:
            return self.finish(scope)
        # Daily game quota is one. Retry only if the same zero counter and
        # the exact priced offer remain visible on multiple fresh captures.
        for attempt in range(2):
            if not self.wait_for(lambda: self.state(scope) == 0 and bool(self.offer(scope)), attempts=8, stable=2):
                raise RuntimeError("公会投资次数或价格无法确认，不投资")
            button = self.offer(scope)
            if self.state(scope) != 0 or not button:
                raise RuntimeError("投资前页面发生变化，不投资")
            self.click_row(button, .8)
            unchanged = 0
            for _ in range(20):
                self.capture()
                if self.close_reward():
                    unchanged = 0
                    continue
                state = self.state(scope)
                if state == 1:
                    return self.finish(scope)
                if self.find(r"今日已进行过投资|资源不足|材料不足|货币不足", (340, 230, 650, 280)):
                    raise RuntimeError("投资出现提示，保留页面停止核对")
                unchanged = unchanged + 1 if state == 0 else 0
                self.pause(.4)
            if unchanged < 3 or not self.offer(scope):
                raise RuntimeError("投资结果不明，不重复点击")
            if attempt == 0:
                self.log("投资次数连续保持0/1且价格未变，重试一次")
        raise RuntimeError("投资点击后仍为0/1，停止该项")


class TreasureQuickFree(ScreenAction):
    label = "免费快速探查"
    timeout = 45

    def remaining(self):
        if not self.find(r"^快速探查$", (540, 85, 220, 55)):
            return None
        rows = self.ocr(r".+", (490, 495, 350, 55))
        text = re.sub(r"\s", "", " ".join(row.text for row in rows))
        match = re.search(r"今日剩余免费次数([01])$", text)
        return int(match[1]) if match else None

    def execute(self):
        if self.remaining() == 0:
            self.log("今日免费次数已用完，跳过")
            return True
        for attempt in range(2):
            if not self.wait_for(lambda: self.remaining() == 1, attempts=8, stable=2):
                raise RuntimeError("未确认剩余1次免费探查，不点击")
            button = self.find(r"^开始探查$", (490, 568, 310, 70))
            if not button or self.remaining() != 1:
                raise RuntimeError("未确认免费探查按钮")
            self.click_row(button, .8)
            unchanged, reward = 0, False
            for _ in range(20):
                self.capture()
                if self.close_reward():
                    reward = True
                    unchanged = 0
                    self.log("已确认并关闭免费探查奖励")
                    continue
                if reward and self.find(r"^宝藏探索$", (530, 105, 250, 60)):
                    self.log("免费探查奖励已确认并返回宝藏页面")
                    return True
                state = self.remaining()
                if state == 0:
                    self.log("免费探查次数1->0" + ("，奖励已确认" if reward else "，不再点击"))
                    return True
                unchanged = unchanged + 1 if state == 1 else 0
                self.pause(.4)
            if reward or unchanged < 3:
                raise RuntimeError("探查结果不明，不重复点击")
            if attempt == 0:
                self.log("免费次数连续保持1，重试一次免费探查")
        raise RuntimeError("免费探查点击后次数未变化，停止该项")


class DungeonOpenMenu(ScreenAction):
    label = "副本导航"
    timeout = 15

    def execute(self):
        until = time.monotonic() + 12
        clicks = 0
        home_since = None
        retry_after = 0
        while time.monotonic() < until:
            self.capture()
            if self.find(r"载入|加载|连接中|更新中|重试|网络|维护|断开连接|是否|确认|确定|取消",
                         (240, 160, 800, 440)) or self.node("Global_ItemObtained"):
                raise RuntimeError("检测到加载、网络提示或弹窗，停止打开菜单")
            if self.find(r"^战斗$", (985, 409, 60, 29)):
                self.log(f"已确认战斗菜单展开（打开{clicks}次）")
                return True
            now = time.monotonic()
            if self.node("HomeFlagCloseReturnMain"):
                if home_since is None:
                    home_since = now
                # A click receipt or frozen pixels do not confirm navigation.
                # Retry only after fresh captures still show the known home.
                if now - home_since >= 1 and now >= retry_after:
                    if clicks >= 2:
                        raise RuntimeError("两次打开后仍在大厅，停止导航")
                    clicks += 1
                    self.log(f"确认仍在大厅，打开右上菜单（{clicks}/2）")
                    self.click(1236, 36)
                    retry_after = time.monotonic() + 2
                    home_since = None
            else:
                home_since = None
            self.pause(.4)
        raise RuntimeError("未能确认战斗菜单，停止导航")


def character_key(text):
    return re.sub(r"[\s♡♥❤⭐☆▶>]", "", text)


def daily_talk_count(text):
    # The bundled OCR reads the live counter as e.g. "7./7".
    clean = re.sub(r"[\s.。·,，]", "", text).replace("／", "/")
    match = re.fullmatch(r"([0-7])/7", clean)
    return int(match[1]) if match else None


class FavorTalk(ScreenAction):
    label = "好感"
    timeout = 420

    def run(self, context, argv):
        self.trace_path = (Path(__file__).resolve().parents[1] / "debug"
                           / f"local-favor-{datetime.now():%Y-%m-%d}.jsonl")
        return super().run(context, argv)

    def log(self, message):
        super().log(message)
        path = getattr(self, "trace_path", None)
        if path is not None:
            try:
                path.parent.mkdir(parents=True, exist_ok=True)
                record = {"time": datetime.now().astimezone().isoformat(),
                          "node": getattr(self.argv, "node_name", ""), "message": message}
                with path.open("a", encoding="utf-8") as stream:
                    stream.write(json.dumps(record, ensure_ascii=False) + "\n")
            except OSError as exc:
                print(f"[好感] 无法保存过程记录：{exc}", flush=True)

    def remaining(self, detail=False):
        roi = (1020, 12, 110, 45) if detail else (24, 73, 210, 45)
        if detail:
            # At 1/7 the detector can split the counter into "1" and "17".
            # Recognize the known numeric crop as a single line first.
            for row in self.ocr(r".+", (1045, 20, 65, 32), only_rec=True):
                value = daily_talk_count(row.text)
                if value is not None:
                    return value
        for row in self.ocr(r".+", roi):
            value = daily_talk_count(row.text)
            if value is not None:
                return value
        raise RuntimeError("无法确认今日剩余对话次数")

    def detail_name(self):
        def read_name(roi):
            rows = [r for r in self.ocr(r".+", roi)
                    if r.score >= .7 and re.search(r"[\u4e00-\u9fffA-Za-z]", r.text)
                    and not re.search(r"\d|对话|角色|羁绊", r.text)]
            if not rows:
                return None
            # The help icon after the top title can have a higher OCR score
            # than the name. It is not a character identity.
            title = min(rows, key=lambda r: (r.box.x, -r.score)).text
            return character_key(re.sub(r"[?？]\s*$", "", title))

        # The top title is white on a light background for some characters
        # (e.g. 雪泉). Prefer the duplicate name on the dark detail card, but
        # only after recognizing the talk controls on that same fresh frame.
        if self.find(r"^对话\s*[>›]?$|对话完成|^[01]\s*[/／]\s*1$", (735, 575, 235, 90)):
            name = read_name((866, 140, 335, 36))
            if name:
                return name
        return read_name((174, 10, 245, 45))

    def list_candidates(self):
        rows = self.ocr(r".+", (218, 151, 285, 510))
        # Each card has a name followed by a relationship description. Group
        # nearby lines and use only the first, instead of guessing every label.
        titles = []
        last_y = None
        for row in sorted(rows, key=lambda r: r.box.y):
            if row.score < .7 or not re.search(r"[\u4e00-\u9fffA-Za-z]", row.text):
                continue
            if last_y is None or row.box.y - last_y > 48:
                titles.append(row)
            last_y = row.box.y
        return titles

    def wait_detail_controls(self, name):
        """An affection-level animation can temporarily cover the talk card."""
        until = time.monotonic() + 12
        dismissed = False
        while time.monotonic() < until:
            self.capture()
            current = self.detail_name()
            if current and current != name:
                raise RuntimeError("等待对话按钮时角色发生变化，停止")
            if self.find(r"对话完成|已完成|1\s*/\s*1", (735, 575, 235, 90)):
                return None
            button = self.find(r"^对话\s*[>›]?$", (738, 625, 220, 42))
            if button:
                return button
            if not dismissed and self.find(r"好感度上升", (450, 285, 400, 75)):
                self.log(f"{name}页面正在播放好感度上升，关闭提示后等待对话按钮")
                self.click(640, 680, .8)
                dismissed = True
            else:
                self.pause(.4)
        raise RuntimeError(f"{name}的对话状态无法确认，停止")

    def execute(self):
        limit = max(0, min(7, int(self.param.get("limit", 7))))
        if not limit:
            self.log("本轮上限为0，跳过")
            return True
        self.seen = set()
        self.seen_aliases = set()
        pending_candidate = None
        completed = 0
        attempted = 0
        unconfirmed = []
        last_bottom = None
        scrolls = 0
        talk_list_opened = False
        for _ in range(24):
            if self.detail_name() or self.find(r"对话次数", (22, 73, 245, 45)):
                break
            # The legacy navigation can hand off on the ordinary character
            # grid. Open its heart-shaped talk button before reading counters.
            talk = self.find(r"^对话$", (850, 15, 215, 55))
            if (not talk_list_opened and talk
                    and self.find(r"^角色$", (160, 10, 110, 55))):
                self.click_row(talk, .8)
                talk_list_opened = True
                continue
            self.pause(.4)
            self.capture()
        else:
            raise RuntimeError("等待好感列表超时")
        max_attempts = min(21, limit * 3)
        while completed < limit and attempted < max_attempts:
            self.capture()
            name = self.detail_name()
            if name:
                if pending_candidate:
                    self.seen_aliases.add(pending_candidate)
                    pending_candidate = None
                if not self.remaining(detail=True):
                    return self.finish_run(completed, attempted, unconfirmed, "今日次数已用完")
                already_done = self.find(r"对话完成|已完成|1\s*/\s*1", (735, 575, 235, 90))
                if name in self.seen or already_done:
                    self.seen.add(name)
                    self.click(1235, 37)
                    continue
                button = self.find(r"^对话\s*[>›]?$", (738, 625, 220, 42))
                if not button:
                    button = self.wait_detail_controls(name)
                    if button is None:
                        continue
                before = self.remaining(detail=True)
                # Remember before pressing: never retry the same person on an
                # ambiguous result, even when their affection level stays low.
                self.seen.add(name)
                attempted += 1
                self.log(f"检查第{attempted}位：{name}，已完成{completed}/{limit}，剩余{before}/7")
                self.click_row(button)
                if self.finish_conversation(name, before):
                    completed += 1
                    self.log(f"已确认完成{completed}人：{name}")
                else:
                    unconfirmed.append(name)
                    self.log(f"{name}剧情返回后次数未变化，跳过该角色，继续寻找可完成每日对话的角色")
                self.click(1235, 37)
                continue
            if not self.find(r"对话次数", (22, 73, 245, 45)):
                raise RuntimeError("没有进入好感对话列表")
            # The list's counter can stay stale after returning. The detail
            # page and each person's 1/1 state are the authoritative checks.
            candidates = self.list_candidates()
            available = [r for r in candidates
                         if character_key(r.text) not in self.seen
                         and character_key(r.text) not in self.seen_aliases]
            if available:
                pending_candidate = character_key(available[0].text)
                self.click_row(available[0])
                continue
            signature = tuple(character_key(r.text) for r in candidates)
            if signature == last_bottom or scrolls >= 18:
                return self.finish_run(completed, attempted, unconfirmed, "没有其他可对话角色")
            last_bottom = signature
            self.swipe(405, 618, 405, 195)
            scrolls += 1
        reason = f"已完成本轮{limit}次对话" if completed >= limit else "达到角色检查上限"
        return self.finish_run(completed, attempted, unconfirmed, reason)

    def finish_run(self, completed, attempted, unconfirmed, reason):
        self.log(f"{reason}；处理{attempted}人，确认完成{completed}人")
        if unconfirmed and reason != "今日次数已用完" and not reason.startswith("已完成本轮"):
            self.log("以下角色仍待确认，本项未全部完成：" + "、".join(unconfirmed))
            return False
        return True

    def finish_conversation(self, name, before):
        until = time.monotonic() + 55
        unchanged_since = None
        unchanged_frames = 0
        last_state = None
        saw_story = False
        other_name = None
        other_frames = 0
        while time.monotonic() < until:
            self.capture()
            current_name = self.detail_name()
            if current_name:
                if current_name != name:
                    other_frames = other_frames + 1 if current_name == other_name else 1
                    other_name = current_name
                    unchanged_since = None
                    unchanged_frames = 0
                    if other_frames >= 3:
                        raise RuntimeError(f"对话角色从{name}变为{current_name}，停止核对")
                    self.pause(.4)
                    continue
                other_name = None
                other_frames = 0
                after = self.remaining(detail=True)
                done = self.find(r"对话完成|已完成|1\s*/\s*1", (735, 575, 235, 90))
                state = ("detail", after, bool(done))
                if state != last_state:
                    self.log(f"{name}返回角色页：剩余{after}/7，完成标记={bool(done)}，已进入剧情={saw_story}")
                    last_state = state
                if done and after == before - 1:
                    return True
                if after > before or after < before - 1:
                    raise RuntimeError(f"{name}对话次数异常：{before}/7 -> {after}/7，停止")
                not_done = self.find(r"^0\s*[/／]\s*1$", (735, 575, 235, 90))
                available = self.find(r"^对话\s*[>›]?$", (738, 625, 220, 42))
                # This is an explicit unchanged result, not a successful talk.
                # Leave this person pending and inspect another distinct person;
                # never replay their story or spend another attempt on them.
                if not done and not_done and available and after == before:
                    if unchanged_since is None:
                        unchanged_since = time.monotonic()
                    unchanged_frames += 1
                    if unchanged_frames >= 3 and time.monotonic() - unchanged_since >= 6:
                        return False
                else:
                    unchanged_since = None
                    unchanged_frames = 0
                self.pause(.4)
                continue
            unchanged_since = None
            unchanged_frames = 0
            other_name = None
            other_frames = 0
            if self.find(r"Log|LOG", (24, 4, 115, 65)):
                if not saw_story:
                    self.log(f"{name}已进入剧情")
                saw_story = True
                self.click(264, 273, .7)
                continue
            if self.close_reward():
                continue
            self.pause(.4)
        raise RuntimeError(f"{name}的对话结果未确认，不重复对话")


def arena_cost(text):
    compact = re.sub(r"\s", "", text)
    match = re.search(r"(?:消耗|耗费|花费|需要|耗)(\d+)(?:个|颗|枚|钻石)", compact)
    return int(match[1]) if match else None


class ArenaDaily(ScreenAction):
    label = "竞技场"
    timeout = 900

    def execute(self):
        limit = max(0, min(999, int(self.policy("Local_ArenaPolicy").get("attempts", 99))))
        if not limit:
            self.log("本轮上限为0，跳过")
            return True
        started = 0
        free_used = 0
        pending_battle = False
        entered = False
        free_submitted = False
        refresh_at = None
        last_state = None
        progress_at = time.monotonic()
        while True:
            self.capture()
            quote_rows = self.ocr(r".+", (380, 285, 530, 145))
            quote = arena_cost(" ".join(row.text for row in quote_rows))
            cancel = self.find(r"取消", (380, 450, 260, 100))
            if quote is not None and cancel:
                state = "cost-dialog"
                if quote > 0 or free_used >= 3:
                    self.click_row(cancel)
                    self.log(f"票券及可用免费机会已用完，本轮已挑战{started}次，正常结束")
                    return True
                if not free_submitted:
                    confirm = self.find(r"确认|确定", (680, 450, 245, 100))
                    if not confirm:
                        raise RuntimeError("费用为0，但未识别到免费确认按钮")
                    self.click_row(confirm)
                    free_submitted = True
                    free_used += 1
                    self.log(f"确认0钻石免费机会（本轮第{free_used}次）")
            elif self.find(r"门票不足|票券不足|次数不足|今日.*已用完|免费.*已用完|挑战次数.*上限",
                           (330, 240, 640, 330)):
                if cancel:
                    self.click_row(cancel)
                self.log(f"没有剩余票券或免费机会，本轮已挑战{started}次，正常结束")
                return True
            elif cancel and self.find(r"确认|确定", (680, 450, 245, 100)):
                raise RuntimeError("挑战确认框的费用无法读取，不确认也不购买")
            elif self.find(r"请点击屏幕", (950, 490, 320, 100)):
                state = "result"
                if not pending_battle:
                    started += 1
                    pending_battle = True
                self.click(1120, 540, .8)
                entered = False
                free_submitted = False
                if last_state != "result":
                    self.log(f"已结算{started}次挑战")
            elif (skip := self.find(r"Skip|SKIP", (1080, 0, 150, 75))):
                state = "battle"
                if not pending_battle:
                    started += 1
                    pending_battle = True
                self.click_row(skip, .8)
            elif self.find(r"对战对手", (310, 70, 200, 65)):
                state = "opponents"
                pending_battle = False
                entered = False
                free_submitted = False
                if started >= limit:
                    self.log(f"达到本轮最多{limit}次，正常结束")
                    return True
                challenge = self.find(r"^挑战$", (1110, 140, 170, 550))
                if challenge:
                    refresh_at = None
                    self.click_row(challenge)
                elif self.find(r"赛季.*结束|无法挑战|暂无对手", (300, 170, 930, 450)):
                    self.log("当前没有可挑战对手，正常结束")
                    return True
                elif len(self.ocr(r"^WIN$", (1120, 140, 160, 550))) >= 3:
                    refresh = self.find(r"刷新列表", (1050, 80, 225, 50))
                    if refresh and refresh_at is None:
                        refresh_at = time.monotonic()
                        self.click_row(refresh, 1.2)
                        self.log("本批三名对手已完成，刷新下一批对手")
                    elif refresh_at is not None and time.monotonic() - refresh_at > 15:
                        self.log("刷新后没有新的可挑战对手，本轮正常结束")
                        return True
            elif (ready := self.find(r"^进入$", (1030, 620, 220, 85))):
                state = "ready"
                if started >= limit:
                    self.log(f"达到本轮最多{limit}次，正常结束")
                    return True
                if not entered:
                    self.click_row(ready)
                    entered = True
            else:
                state = "loading"
                self.pause(.4)
            if state != last_state:
                progress_at = time.monotonic()
                last_state = state
            elif time.monotonic() - progress_at > 55:
                raise RuntimeError(f"等待竞技场{state}状态超时；不会额外购买挑战")


def gem_grade(text):
    """Read the selected-material grade, never the inventory tab or gem hue."""
    grades = [name for name in ("普通", "高级", "稀有", "英雄", "传说") if name in text]
    return grades[0] if len(grades) == 1 else None


class StonehengeGate(ScreenAction):
    label = "巨石阵"
    timeout = 45

    def execute(self):
        node = self.context.get_node_data("副本_点击巨石阵")
        enabled = node.get("enabled") if isinstance(node, dict) else None
        if not isinstance(enabled, bool):
            raise RuntimeError("无法确认独立开关，停止")
        if not enabled:
            self.log("独立开关关闭，跳过")
            return bool(self.context.override_next(self.argv.node_name, []))
        for _ in range(10):
            self.capture()
            if self.find(r"^巨石阵$", (125, 535, 130, 70)):
                self.log("已返回副本列表，继续已开启的巨石阵")
                return bool(self.context.override_next(self.argv.node_name, ["副本_点击巨石阵"]))
            if (self.find(r"一键扫荡", (550, 620, 400, 75))
                    or self.find(r"冒险区域", (170, 18, 180, 70))):
                self.click(1235, 35, .9)
                continue
            if (self.find(r"^战斗$", (70, 8, 110, 60))
                    and (tab := self.find(r"^副本$", (345, 70, 150, 60)))):
                self.click_row(tab, .9)
                continue
            self.pause(.5)
        raise RuntimeError("无法从扫荡页面返回巨石阵入口，停止")


class GemCombine(ScreenAction):
    label = "宝石合成"
    timeout = 180

    def execute(self):
        limit = max(0, min(99, int(self.param.get("limit", 1))))
        if not limit:
            self.log("本轮上限为0，跳过合成")
            return True
        if not self.find(r"宝石", (55, 10, 100, 55)):
            raise RuntimeError("没有进入宝石页面")
        self.click(450, 110)
        for index in range(12):
            if self.find(r"自动登录", (955, 640, 300, 65)):
                break
            if index == 4:
                tab = self.find(r"^宝石合成$", (300, 65, 235, 65))
                if tab and self.find(r"宝石", (55, 10, 100, 55)):
                    self.log("仍在宝石页，重新打开合成分类一次")
                    self.click_row(tab, .8)
            self.pause(.4)
            self.capture()
        else:
            raise RuntimeError("未确认宝石合成页面")
        for completed in range(limit):
            self.click(1100, 667)
            grade = None
            for _ in range(12):
                rows = self.ocr(r".+", (355, 528, 200, 45))
                grade = gem_grade(" ".join(r.text for r in rows))
                if grade:
                    break
                self.pause(.4)
                self.capture()
            if grade in ("英雄", "传说"):
                self.log(f"自动登录选中{grade}品质（紫色或更高），停止，不合成")
                return True
            if grade not in ("普通", "高级", "稀有"):
                if (not self.find(r"重置", (205, 642, 240, 55))
                        and self.find(r"合成", (335, 642, 235, 55))):
                    self.log("自动登录没有选到可合成材料，正常结束")
                    return True
                raise RuntimeError("选中材料品质无法确认，不执行合成")
            if not (self.find(r"重置", (205, 642, 240, 55))
                    and self.find(r"^合成$", (465, 642, 235, 55))):
                raise RuntimeError("材料已选中，但合成按钮状态不匹配")
            self.log(f"执行第{completed + 1}/{limit}轮{grade}品质合成（游戏将处理本次自动选中的整批材料）")
            self.click(580, 667)
            # The game commits immediately; no second click on an unknown result.
            for _ in range(45):
                if self.close_reward():
                    break
                if self.find(r"金币不足|材料不足|资源不足", (350, 250, 600, 200)):
                    self.log("合成资源不足，结束本轮")
                    return True
                self.pause(.5)
                self.capture()
            else:
                raise RuntimeError("已点击一次合成，结果未确认；不会再次点击")
        self.log(f"完成{limit}轮合成，正常结束")
        return True


def squad_free_status(text):
    compact = re.sub(r"[\s.。·]", "", text).replace("／", "/")
    if re.search(r"1/1", compact):
        return True
    if re.search(r"0/1", compact) or re.fullmatch(r"\d+开始匹配|开始匹配\d+", compact):
        return False
    return None


class SquadDaily(ScreenAction):
    label = "小队副本"
    timeout = 240

    def execute(self):
        if int(self.param.get("limit", 1)) <= 0:
            self.log("本轮上限为0，跳过")
            return True
        # A free entry has an explicit 1/1 suffix. After it is used, this
        # becomes a ticket icon and amount; do not treat that as another free run.
        button = self.find(r"开始匹配", (940, 638, 270, 58))
        if not button:
            raise RuntimeError("未确认小队副本匹配页面")
        rows = self.ocr(r".+", (950, 640, 250, 50))
        status = squad_free_status("".join(r.text for r in rows))
        if status is None and self.node("LocalSquad_TicketMode"):
            status = False
        if status is False:
            self.log("每日免费匹配已用完；不消耗额外小队门票，正常结束")
            return True
        if status is None:
            raise RuntimeError("无法确认小队副本的免费次数，不开始匹配")
        self.click(1070, 665)
        for _ in range(15):
            if self.find(r"是否前往小队副本房间", (470, 320, 360, 70)):
                confirm = self.find(r"确认", (500, 445, 280, 55))
                if not confirm:
                    raise RuntimeError("未找到进入小队房间的确认按钮")
                self.click_row(confirm)
                break
            self.pause(.4)
            self.capture()
        else:
            raise RuntimeError("未确认免费匹配结果，不重复开始匹配")
        battle_until = time.monotonic() + 160
        while time.monotonic() < battle_until:
            self.capture()
            result = self.find(r"CLEAR|FAIL|DEFEAT|胜利|失败", (360, 75, 580, 180))
            back = self.find(r"^返回$", (865, 620, 180, 80))
            if result and back:
                self.log(f"小队副本已结算：{result.text}")
                self.click_row(back, 1)
                return True
            if self.find(r"门票不足|次数不足|今日.*已用完", (350, 250, 600, 200)):
                self.log("当前没有可用的免费次数，正常结束")
                return True
            self.pause(.6)
        if self.node("LocalSquad_RoomExit"):
            self.click(1235, 35)
            for _ in range(8):
                if self.find(r"(?:退出|离开|放弃).*(?:房间|小队|副本)|是否.*(?:退出|离开)",
                             (350, 275, 600, 150)):
                    confirm = self.find(r"确认|确定", (380, 430, 550, 100))
                    if confirm:
                        self.click_row(confirm)
                        self.log("等待过久，已退出当前小队房间")
                    break
                if self.find(r"开始匹配", (940, 638, 270, 58)):
                    break
                self.pause(.4)
                self.capture()
        raise RuntimeError("等待小队匹配或战斗结算超时；不会重复匹配或购买门票")


SHOP_EXCHANGE_CATEGORIES = (
    "商品-交易所-消耗品", "商品-交易所-突袭", "商品-交易所-公会",
    "商品-交易所-竞技场", "商品-交易所-夏日币", "商品-交易所-南瓜币",
)


class ShopCategoryClick(CustomAction):
    def run(self, context, argv):
        try:
            if argv.node_name not in SHOP_EXCHANGE_CATEGORIES or context.tasker.stopping:
                return False
            node = context.get_node_data(argv.node_name)
            if not isinstance(node, dict) or node.get("enabled") is not True:
                return False
            x, y, w, h = argv.box
            job = context.tasker.controller.post_click(x + w // 2, y + h // 2).wait()
            if not job.succeeded:
                return False
            # Each selected category runs once. Completing one never consumes
            # another category's purchase allowance or changes its switch.
            return bool(context.override_pipeline({argv.node_name: {"enabled": False}}))
        except Exception as exc:
            print(f"[交易所] 分类入口失败: {exc}", flush=True)
            return False


class ShopExchangeFinish(CustomAction):
    def run(self, context, argv):
        try:
            if context.tasker.stopping:
                return False
            pending = []
            for name in SHOP_EXCHANGE_CATEGORIES:
                node = context.get_node_data(name)
                enabled = node.get("enabled") if isinstance(node, dict) else None
                if not isinstance(enabled, bool):
                    raise RuntimeError("无法确认交易所分类开关")
                if enabled:
                    pending.append(name)
            # Summer currency is an optional event tab and can disappear.
            missing = [name for name in pending if name not in ("商品-交易所-夏日币", "商品-交易所-南瓜币")]
            if missing:
                raise RuntimeError("已开启分类尚未处理: " + "、".join(missing))
            if pending:
                print("[交易所] 当前没有已选的活动货币分类，跳过：" + "、".join(pending), flush=True)
            if not context.override_pipeline({"商店-交易所": {"enabled": False}}):
                return False
            print("[交易所] 各分类已分别处理，返回大厅", flush=True)
            return True
        except Exception as exc:
            print(f"[交易所] {exc}", flush=True)
            return False


class ShopFreeGift(ScreenAction):
    label = "每日及每周免费礼包"
    timeout = 150

    def finish(self, message):
        # Return to the parent JumpBack chain so enabled exchange tasks can run.
        self.context.override_pipeline({"商店-商品": {"enabled": False}})
        self.log(message)
        return True

    def execute(self):
        periods = getattr(self, "param", {}).get("periods", ["每日", "每周"])
        if (not isinstance(periods, list) or not periods or len(set(periods)) != len(periods)
                or any(period not in ("每日", "每周") for period in periods)):
            raise RuntimeError("免费礼包周期须为每日、每周")
        for period in periods:
            self.claim(period)
        return self.finish("每日及每周免费礼包已检查，继续后续任务")

    def claim(self, period):
        title = period + "免费礼包"
        submitted = False
        reward_seen = False
        popup_opened = False
        products_clicked = False
        period_attempts = 0
        catalogue_steps = 0
        next_navigation = 0
        open_attempts = 0
        next_open = 0
        for _ in range(65):
            self.capture()
            if self.close_reward():
                reward_seen = True
                continue
            popup = self.find(r"购买商品", (540, 75, 210, 60))
            if popup:
                if not self.find(title, (270, 480, 260, 65)):
                    raise RuntimeError(f"当前弹窗不是{title}，不购买")
                popup_opened = True
                bought = self.find(r"已购买|已领取|售罄|购买完成|售完", (250, 150, 730, 480))
                ratios = self.ocr(r".+", (305, 155, 240, 40))
                bought = bought or any(re.search(r"1\s*[/／]\s*1", r.text) for r in ratios)
                if bought or reward_seen:
                    self.click(1018, 103)
                    self.log(f"{title}已领取")
                    return
                free = self.find(r"^免费$", (500, 580, 280, 65))
                if free and not submitted:
                    submitted = True
                    self.click_row(free, .8)
                    continue
                if not free and not submitted:
                    raise RuntimeError("没有确认礼包为免费，不购买")
            elif self.find(r"已购买过该商品|今日已购买|购买次数.*上限", (340, 240, 600, 200)):
                # Close only this known message; never send it back to the buy loop.
                confirm = self.find(r"确认|确定", (450, 420, 400, 105))
                self.click_row(confirm) if confirm else self.click(921, 243)
                reward_seen = True
            elif self.find(r"商店", (65, 12, 100, 55)):
                if reward_seen:
                    self.log(f"{title}领取完成")
                    return
                gift = self.find("^" + title + "$", (305, 140, 970, 565))
                if gift and not popup_opened and not submitted:
                    # Weekly free gifts can be the last card on the second row.
                    # Bind the status and price crops to this exact title.
                    center = gift.box.x + gift.box.w // 2
                    left = max(305, min(1010, center - 135))
                    top = gift.box.y
                    # The card can already be marked sold out without a popup.
                    card_rows = self.ocr(r".+", (left, top + 23, 270, 40))
                    if (self.find(r"已购买|已领取|售罄|售完", (left, top + 45, 270, 180))
                            or any(re.search(r"1\s*[/／]\s*1", r.text) for r in card_rows)):
                        self.log(f"{title}已领取，跳过购买")
                        return
                    free_card = self.find(r"^免费$", (left, top + 200, 270, 65))
                    if free_card and time.monotonic() >= next_open:
                        if open_attempts >= 2:
                            raise RuntimeError("免费礼包弹窗未打开，停止当前任务")
                        # Only the actual popup confirms that opening worked.
                        # Clicking the card title can leave the product page unchanged.
                        self.click_row(free_card, .8)
                        open_attempts += 1
                        next_open = time.monotonic() + 2
                        continue
                if (not gift and not products_clicked and not popup_opened
                        and time.monotonic() >= next_navigation):
                    product = self.find(r"^商品$", (350, 75, 135, 55))
                    if product:
                        self.click_row(product)
                        products_clicked = True
                        next_navigation = time.monotonic() + 2
                        continue
                if (not gift and products_clicked and not popup_opened
                        and time.monotonic() >= next_navigation):
                    period_page = self.find(r"^" + period + r".*礼包", (305, 140, 970, 565))
                    if period_page:
                        if catalogue_steps >= 6:
                            raise RuntimeError(f"翻页后仍未找到{title}，停止当前任务")
                        self.swipe(1115, 420, 390, 420)
                        catalogue_steps += 1
                        next_navigation = time.monotonic() + 1
                        continue
                    tab = self.find(r"^" + period + r"$", (75, 155, 180, 230))
                    if tab and period_attempts < 2:
                        self.click_row(tab, .8)
                        period_attempts += 1
                        next_navigation = time.monotonic() + 3
                        continue
                    if period_attempts >= 2:
                        raise RuntimeError(f"未确认{period}免费礼包页面，停止当前任务")
            self.pause(.4)
        raise RuntimeError("免费礼包结果未确认，不重复购买")


ACTIONS = {"LocalGuildClaimReward": GuildClaimReward(), "LocalFavorTalk": FavorTalk(),
           "LocalVillageReturnLobby": VillageReturnLobby(),
           "LocalGuildDonationLimit": GuildDonationLimit(),
           "LocalGuildInvest": GuildInvest(), "LocalTreasureQuickFree": TreasureQuickFree(),
           "LocalDungeonOpenMenu": DungeonOpenMenu(),
           "LocalArenaDaily": ArenaDaily(), "LocalGemCombine": GemCombine(),
           "LocalSquadDaily": SquadDaily(), "LocalShopFreeGift": ShopFreeGift(),
           "LocalStonehengeGate": StonehengeGate(),
           "LocalShopCategoryClick": ShopCategoryClick(),
           "LocalShopExchangeFinish": ShopExchangeFinish()}
