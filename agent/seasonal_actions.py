"""Seasonal daily tasks, verified against the game's counters and rewards."""
import json
import re
import time
from datetime import datetime, timedelta, timezone
from pathlib import Path

from agent.daily_actions import ScreenAction


def unsigned_number(text):
    clean = re.sub(r"[\s,，]", "", text)
    return int(clean) if re.fullmatch(r"\d+", clean) else None


def material_ratio(text):
    clean = re.sub(r"[\s,，]", "", text).replace("／", "/")
    match = re.fullmatch(r"(\d+)/(\d+)", clean)
    return tuple(map(int, match.groups())) if match else None


def friend_points(text):
    """Return (sent, received) from the friend page's daily counters."""
    clean = re.sub(r"\s", "", text).replace("／", "/")
    sent = re.search(r"赠送友情点数(\d+)/30", clean)
    received = re.search(r"领取友情点数(\d+)/30", clean)
    if not sent or not received:
        return None
    values = int(sent[1]), int(received[1])
    return values if all(0 <= value <= 30 for value in values) else None


def cow_free_state(text):
    """Free entries are spent only when the button explicitly says so.

    After the weekly free entries, the button shows a bell icon and a bare
    cost such as ``1 进入``. Anything that is not an explicit free marker is
    treated as paid, so the action never spends a New Year's Eve Bell.
    """
    clean = re.sub(r"\s", "", text).replace("／", "/")
    if re.search(r"免费", clean):
        match = re.search(r"([0-3])/3", clean)
        return int(match[1]) if match else -1
    match = re.search(r"([0-3])/3", clean)
    if match:
        return int(match[1])
    return 0


def game_week(now=None):
    # Weekly content resets on the game's UTC+9 schedule.
    now = (now or datetime.now(timezone.utc)).astimezone(timezone(timedelta(hours=9)))
    year, week, _ = now.isocalendar()
    return f"{year}-W{week:02d}"


class SeasonalScreen(ScreenAction):
    timeout = 180

    def log(self, message):
        super().log(message)
        path = Path(__file__).resolve().parents[1] / "debug" / f"local-seasonal-{datetime.now():%Y-%m-%d}.jsonl"
        try:
            path.parent.mkdir(parents=True, exist_ok=True)
            record = {"time": datetime.now().astimezone().isoformat(),
                      "task": self.label, "node": getattr(getattr(self, "argv", None), "node_name", ""),
                      "message": message}
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps(record, ensure_ascii=False) + "\n")
        except OSError:
            pass

    def number(self, roi):
        # Recognition-only OCR reads the recipe's zero as Chinese punctuation.
        # Detect text inside the known numeric crop before a strict fallback.
        for only_rec in (False, True):
            rows = self.ocr(r".+", roi, only_rec=only_rec)
            values = [unsigned_number(row.text) for row in rows]
            if len(values) == 1 and values[0] is not None:
                return values[0]
        raise RuntimeError("无法确认页面数量，停止当前操作")

    def home(self):
        result = self.context.run_task("ReturnMain", {
            "HomeFlagCloseReturnMain": {"next": []},
            "LocalCrashRecovery": {"enabled": False}})
        if not result or not result.status.succeeded:
            raise RuntimeError("未能回到大厅")
        self.pause(.8)
        self.capture()
        if not self.node("HomeFlagCloseReturnMain"):
            raise RuntimeError("大厅尚未稳定，停止打开活动入口")

    def open_menu(self, label):
        self.home()
        self.click(1236, 36, .7)
        for _ in range(12):
            button = self.find("^" + re.escape(label) + "$", (755, 160, 420, 480))
            if button:
                # The caption can sit below the menu button's hit area.
                self.click(button.box.x + button.box.w // 2, button.box.y - 22, .8)
                for _ in range(8):
                    if not self.find(r"游戏专属编号", (850, 55, 350, 50)):
                        return
                    self.pause(.3)
                    self.capture()
                raise RuntimeError("菜单入口点击后没有打开：" + label)
            self.pause(.4)
            self.capture()
        raise RuntimeError("未找到菜单入口：" + label)

    def open_activity(self, label):
        self.open_menu("活动")
        for _ in range(12):
            entry = self.find(re.escape(label), (0, 175, 225, 500))
            if entry:
                self.click_row(entry, 1)
                return
            self.pause(.4)
            self.capture()
        raise RuntimeError("未找到活动入口：" + label)


class BingoCraft(SeasonalScreen):
    label = "宾果票券"

    def recipe(self):
        return (self.find(r"^宾果票券$", (570, 135, 210, 65))
                and self.find(r"^南瓜币$", (960, 190, 220, 55)))

    def material(self):
        for row in self.ocr(r".+", (970, 225, 230, 45), only_rec=True):
            ratio = material_ratio(row.text)
            if ratio:
                return ratio
        raise RuntimeError("南瓜币用量无法确认，不制作")

    def daily_counter(self):
        text = " ".join(row.text for row in self.ocr(r".+", (125, 185, 230, 40)))
        match = re.search(r"([0-5])\s*[/／]\s*5", text)
        if match:
            return int(match[1])
        raise RuntimeError("宾果每日制作次数无法确认，不制作")

    def selected_quantity(self):
        # The small yellow digit is misread (a visible 5 can be read as 2).
        # The recipe's independently displayed material cost is unambiguous.
        _, cost = self.material()
        if cost % 20 or not 0 <= cost <= 100:
            raise RuntimeError("宾果材料单价或数量异常，不制作")
        return cost // 20

    def execute(self):
        limit = int(self.param.get("limit", 5))
        if not 0 <= limit <= 5:
            raise RuntimeError("宾果票券数量须为0至5")
        if not limit:
            self.log("数量为0，跳过")
            return True
        self.open_menu("制作")
        activity = self.find(r"^活动$", (1030, 60, 195, 75))
        if not activity:
            raise RuntimeError("没有确认制作页面的活动分类")
        self.click_row(activity)
        ticket = self.find(r"^宾果票券$", (115, 135, 240, 500))
        if not ticket:
            self.log("本期没有宾果票券配方，跳过")
            return True
        self.click_row(ticket)
        if not self.recipe():
            raise RuntimeError("配方名称或南瓜币材料不匹配，不制作")
        used = self.daily_counter()
        if used == 5:
            self.log("今日宾果票券已制作5张，跳过")
            return True
        owned, required = self.material()
        if owned < 20:
            self.log(f"南瓜币不足（{owned}/20），本次未制作")
            return True
        before_tickets = self.number((1000, 15, 70, 40))
        before_coins = self.number((1120, 15, 90, 40))
        if owned != before_coins:
            raise RuntimeError("南瓜币余额与材料栏不一致，不制作")
        quantity = self.selected_quantity()
        if quantity not in (0, 1):
            raise RuntimeError("配方初始数量不是0或默认1，不沿用未知选择")
        desired = min(limit, 5 - used, owned // 20)
        for _ in range(max(0, desired - quantity)):
            self.click(973, 678, .4)
            after = self.selected_quantity()
            if after == quantity:
                break
            if after < quantity or after > desired:
                raise RuntimeError("制作数量变化异常，不制作")
            quantity = after
            if quantity == desired:
                break
        if quantity == 0:
            self.log("游戏未提供可制作数量，今日次数已用完，本次未制作")
            return True
        owned, required = self.material()
        if not self.recipe() or owned != before_coins or required != 20 * quantity or owned < required:
            raise RuntimeError("制作前配方、数量或材料用量不匹配，不制作")
        button = self.find(r"^制作$", (1090, 645, 175, 65))
        if not button:
            raise RuntimeError("未确认制作按钮")
        self.log(f"制作{quantity}张宾果票券，使用{required}南瓜币")
        self.click_row(button, .8)
        # One commit only: an uncertain response must never trigger another craft.
        until = time.monotonic() + 35
        while time.monotonic() < until:
            self.capture()
            if self.close_reward():
                continue
            if self.recipe():
                tickets = self.number((1000, 15, 70, 40))
                coins = self.number((1120, 15, 90, 40))
                if (tickets == before_tickets + quantity and coins == before_coins - required
                        and self.daily_counter() == used + quantity):
                    self.log(f"已确认票券{before_tickets}->{tickets}，南瓜币{before_coins}->{coins}")
                    return True
                if tickets not in (before_tickets, before_tickets + quantity):
                    raise RuntimeError("制作后票券余额异常，不再次制作")
            self.pause(.5)
        raise RuntimeError("已提交一次制作，结果尚未确认，不再次制作")


class RaidSweep(SeasonalScreen):
    label = "个人突袭扫荡"
    timeout = 65

    def dialog(self):
        return (self.find(r"(?:一)?键扫荡", (560, 85, 180, 60))
                and self.find(r"Boss\s*Raid\s*Ticket", (500, 285, 290, 65)))

    def free_remaining(self):
        for row in self.ocr(r".+", (900, 635, 140, 65)):
            match = re.search(r"扫荡\s*([0-3])\s*[/／]\s*3", row.text)
            if match:
                return int(match[1])
        return None

    def ledger(self, record=None):
        path = Path(__file__).resolve().parents[1] / "debug" / f"raid-sweeps-{datetime.now():%Y-%m-%d}.jsonl"
        if record is None:
            rows = [json.loads(line) for line in path.read_text("utf-8").splitlines()] if path.exists() else []
            return rows[-1] if rows else None
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": datetime.now().astimezone().isoformat(), **record}, ensure_ascii=False) + "\n")

    def execute(self):
        previous = self.ledger()
        if previous:
            if previous["status"] == "confirmed":
                self.log("今日1次个人突袭已有到账回执，跳过重复扫荡")
                return True
            raise RuntimeError("今日突袭已经提交过，结果需要核对，不重复扫荡")
        popup = bool(self.dialog())
        if not popup and not self.find(r"队伍编排", (65, 635, 160, 55)):
            raise RuntimeError("未确认个人突袭扫荡页")
        before = self.number((1140, 14, 65, 40))
        before_free = None if popup else self.free_remaining()
        if before < 1 and not before_free:
            self.log("没有突袭门票，跳过")
            return True
        submitted = False
        if not popup:
            button = self.find(r"^扫荡(?:\s*[0-3]\s*[/／]\s*3)?$", (900, 640, 130, 55))
            if not button:
                raise RuntimeError("未找到个人突袭扫荡入口")
            # With the game's confirmation disabled, this button commits at once.
            self.ledger({"status": "unknown", "before_tickets": before, "before_free": before_free})
            self.log(f"已记录门票{before}、免费次数{before_free}，仅点击一次扫荡入口")
            self.click_row(button, .8)
        reward = False
        until = time.monotonic() + 30
        while time.monotonic() < until:
            self.capture()
            if self.close_reward():
                reward = True
                continue
            if self.dialog() and not submitted:
                if before_free:
                    raise RuntimeError("免费次数与门票确认弹窗不一致，不消耗门票")
                if self.number((620, 373, 45, 36)) != 1:
                    raise RuntimeError("扫荡数量不是默认1次，不消耗额外门票")
                confirm = self.find(r"^扫荡$", (500, 565, 290, 65))
                if not confirm:
                    raise RuntimeError("未确认弹窗内扫荡按钮")
                if popup:
                    self.ledger({"status": "unknown", "before_tickets": before})
                submitted = True
                self.log(f"已确认默认1次及门票{before}，提交一次扫荡")
                self.click_row(confirm, .8)
                continue
            if not self.dialog() and self.find(r"队伍编排", (65, 635, 160, 55)):
                after = self.number((1140, 14, 65, 40))
                after_free = self.free_remaining()
                free_receipt = bool(before_free and after_free == before_free - 1 and after == before)
                paid_receipt = not before_free and after == before - 1
                if reward and (free_receipt or paid_receipt):
                    self.ledger({"status": "confirmed", "before_tickets": before, "after_tickets": after,
                                 "before_free": before_free, "after_free": after_free})
                    self.log(f"已确认1次扫荡及奖励，免费次数{before_free}->{after_free}，门票{before}->{after}")
                    return True
                if after not in (before, before - 1):
                    raise RuntimeError("门票变化异常，不重复扫荡")
            self.pause(.4)
        raise RuntimeError("已提交一次扫荡，结果未确认，不再次消耗门票")


class RouletteFree(SeasonalScreen):
    label = "每日免费轮盘"
    timeout = 120

    def page(self):
        return self.find(r"贝迪兔女郎轮盘", (235, 80, 400, 100))

    def free_remaining(self):
        rows = self.ocr(r".+", (780, 260, 145, 50))
        for row in rows:
            match = re.fullmatch(r"免费\s*([01])\s*[/／]\s*1", row.text)
            if match:
                return int(match[1])
        return None

    def paid_only(self):
        if (not self.find(r"^PUSH$", (780, 315, 145, 75))
                or not self.find(r"10连抽", (850, 640, 125, 55))):
            return False
        try:
            return self.number((850, 355, 45, 40)) == 1
        except RuntimeError:
            return False

    def execute(self):
        self.open_activity("贝迪兔女郎轮盘")
        if not self.page():
            raise RuntimeError("未确认贝迪兔女郎轮盘页面")
        remaining = self.free_remaining()
        if remaining == 0 or (remaining is None and self.paid_only()):
            self.log("今日免费轮盘已用完，跳过")
            return True
        if remaining != 1:
            raise RuntimeError("未确认免费1/1，不使用抽奖券")
        before = self.number((1140, 14, 65, 40))
        push = self.find(r"^PUSH$", (780, 315, 145, 75))
        if not push:
            raise RuntimeError("未确认轮盘按钮")
        self.capture()
        if not self.page() or self.free_remaining() != 1:
            raise RuntimeError("提交前免费次数发生变化，不抽奖")
        self.log(f"已确认免费1/1及持有抽奖券{before}，仅提交一次免费抽奖")
        self.click_row(push, .8)
        reward = False
        until = time.monotonic() + 40
        while time.monotonic() < until:
            self.capture()
            if self.close_reward():
                reward = True
                self.log("已识别并关闭轮盘奖励弹窗")
                continue
            if self.page():
                after = self.number((1140, 14, 65, 40))
                if after != before:
                    raise RuntimeError("抽奖券余额发生变化，停止核对，不再次抽奖")
                if reward and (self.free_remaining() == 0 or self.paid_only()):
                    self.log(f"免费抽奖奖励已确认，抽奖券保持{after}张")
                    return True
            self.pause(.5)
        raise RuntimeError("已提交一次免费抽奖，结果尚未完全确认，不再次抽奖")


ACTIONS = {"LocalBingoCraft": BingoCraft(), "LocalRaidSweep": RaidSweep(),
           "LocalRouletteFree": RouletteFree()}


class FriendGift(SeasonalScreen):
    label = "好友收礼"
    timeout = 90

    def page(self):
        return (self.find(r"每日友情点数进度", (170, 190, 220, 50))
                and self.find(r"一?键收发", (620, 625, 200, 70)))

    def points(self):
        return friend_points(" ".join(row.text for row in self.ocr(r".+", (150, 625, 280, 70))))

    def execute(self):
        self.open_menu("好友")
        for _ in range(12):
            if self.page():
                break
            self.pause(.4)
            self.capture()
        else:
            raise RuntimeError("未确认好友页面")
        before = self.points()
        if not before:
            raise RuntimeError("好友赠送和领取数量无法读取，不点击一键收发")
        if before == (30, 30):
            self.log("今日友情点数已赠送和领取满30，跳过")
            return True
        button = self.find(r"一?键收发", (620, 625, 200, 70))
        self.log(f"已赠送{before[0]}/30、已领取{before[1]}/30，点击一次一键收发")
        self.click_row(button, 1)
        reward = False
        clicked_at = time.monotonic()
        until = time.monotonic() + 15
        while time.monotonic() < until:
            self.capture()
            if self.close_reward():
                reward = True
                continue
            if self.page():
                after = self.points()
                # A late reward popup must not be mistaken for "nothing to collect".
                settled = after != before or time.monotonic() - clicked_at > 2.5
                if after and settled:
                    if after[0] < before[0] or after[1] < before[1]:
                        raise RuntimeError("友情点数减少，停止核对")
                    if after == before:
                        self.log("当前没有可领取或可赠送的友情点数")
                    else:
                        self.log(f"已确认赠送{before[0]}->{after[0]}，领取{before[1]}->{after[1]}")
                    return True
            self.pause(.5)
        raise RuntimeError("已点击一次一键收发，结果未确认，不重复点击")


class SecretCow(SeasonalScreen):
    label = "秘密奶牛副本"
    timeout = 900

    def ledger(self, record=None):
        path = Path(__file__).resolve().parents[1] / "debug" / "secret-cow-weekly.jsonl"
        week = game_week()
        if record is None:
            if not path.exists():
                return []
            rows = [json.loads(line) for line in path.read_text("utf-8").splitlines() if line.strip()]
            return [row for row in rows if row.get("week") == week]
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": datetime.now().astimezone().isoformat(), "week": week, **record},
                                    ensure_ascii=False) + "\n")

    def title(self):
        return self.find(r"秘密奶牛副本.*第\d+层", (900, 110, 300, 50))

    def bells(self):
        return self.number((1105, 15, 100, 40))

    def open_dungeon(self):
        self.open_menu("战斗")
        for _ in range(10):
            if self.find(r"战斗", (20, 5, 170, 60)) and (tab := self.find(r"^副本$", (345, 70, 150, 60))):
                self.click_row(tab, .9)
                break
            self.pause(.4)
            self.capture()
        else:
            raise RuntimeError("未确认战斗页面的副本分类")
        for _ in range(6):
            card = self.find(r"秘密奶牛副本", (0, 540, 1280, 45))
            if card:
                self.click(card.box.x + card.box.w // 2, 400, 1)
                break
            self.swipe(1100, 400, 200, 400)
        else:
            raise RuntimeError("副本页面没有找到秘密奶牛副本")
        for _ in range(12):
            if self.title():
                return
            self.pause(.4)
            self.capture()
        raise RuntimeError("未确认秘密奶牛副本页面")

    def to_team(self):
        for _ in range(12):
            if self.title() and self.find(r"进入", (1000, 635, 200, 60)):
                return True
            choose = self.find(r"^选择$", (890, 630, 310, 50))
            if choose and self.title():
                self.click_row(choose, .8)
                continue
            self.pause(.4)
            self.capture()
        return False

    def execute(self):
        limit = int(self.param.get("limit", 3))
        if not 0 <= limit <= 5:
            raise RuntimeError("秘密奶牛副本次数须为0至5")
        records = self.ledger()
        used = sum(1 for row in records if row.get("status") in ("submitted", "confirmed"))
        if used >= limit:
            self.log(f"本周已由脚本进入{used}次，达到设置{limit}次，跳过")
            return True
        self.open_dungeon()
        while used < limit:
            if not self.to_team():
                raise RuntimeError("未确认奶牛副本的进入按钮")
            floor = self.title().text
            state = cow_free_state(" ".join(row.text for row in self.ocr(r".+", (890, 635, 310, 55))))
            if state == 0:
                self.log("本周免费次数已用完（进入需要消耗铃铛），不使用铃铛，正常结束")
                return True
            before = self.bells()
            enter = self.find(r"进入", (1000, 635, 200, 60))
            self.ledger({"status": "submitted", "floor": floor, "bells": before})
            self.log(f"确认免费进入，挑战{floor}（本周脚本第{used + 1}/{limit}次），铃铛{before}")
            self.click_row(enter, 1)
            used += 1
            if not self.battle(before):
                return True
            self.ledger({"status": "confirmed", "floor": floor, "bells": before})
        self.log(f"已完成设置的{limit}次，正常结束")
        return True

    def battle(self, bells):
        last = time.monotonic()
        seen_battle = False
        while time.monotonic() - last < 90:
            self.capture()
            dialog = self.find(r"取消", (360, 430, 300, 110))
            if dialog:
                if not self.find(r"免费", (330, 220, 640, 220)):
                    self.click_row(dialog)
                    self.log("进入时弹出了非免费确认框，已取消，不消耗铃铛")
                    return False
                confirm = self.find(r"确认|确定", (640, 430, 300, 110))
                if not confirm:
                    raise RuntimeError("免费确认框没有确认按钮")
                self.click_row(confirm, .8)
                last = time.monotonic()
                continue
            if self.close_reward():
                last = time.monotonic()
                continue
            if (skip := self.find(r"^(?:Skip|SKIP)$", (1080, 0, 200, 75))):
                seen_battle = True
                self.click_row(skip, .8)
                last = time.monotonic()
                continue
            if self.find(r"请点击屏幕|点击继续|点击屏幕", (300, 450, 980, 270)):
                seen_battle = True
                self.click(1120, 540, .8)
                last = time.monotonic()
                continue
            back = self.find(r"^(?:返回|离开|退出|确认)$", (850, 600, 430, 120))
            if back and self.find(r"CLEAR|FAIL|DEFEAT|胜利|失败|通关|结算", (200, 40, 880, 260)):
                seen_battle = True
                self.click_row(back, 1)
                last = time.monotonic()
                continue
            if self.title() and (self.find(r"进入", (1000, 635, 200, 60))
                                 or self.find(r"^选择$", (890, 630, 310, 50))):
                if not seen_battle:
                    self.pause(1)
                    continue
                after = self.bells()
                if after != bells:
                    raise RuntimeError(f"铃铛数量变化{bells}->{after}，立即停止")
                self.log("本次挑战已结束，铃铛未消耗")
                return True
            if self.find(r"Lv\.?\d+|HP|自动|AUTO|x[12]", (0, 0, 1280, 120)) and not self.title():
                seen_battle = True
            self.pause(.8)
        raise RuntimeError("奶牛副本战斗结果等待超时，不再次进入")


ACTIONS.update({"LocalFriendGift": FriendGift(), "LocalSecretCow": SecretCow()})
