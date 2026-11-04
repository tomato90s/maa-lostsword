"""Seasonal daily tasks, verified against the game's counters and rewards."""
import json
import re
import time
from uuid import uuid4
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
    """Read free attempts; a separate icon/price check gates paid entry."""
    clean = re.sub(r"\s", "", text).replace("／", "/")
    if re.search(r"免费", clean):
        match = re.search(r"([0-3])/3", clean)
        return int(match[1]) if match else -1
    match = re.fullmatch(r"进入([0-3])/3", clean)
    if match:
        return int(match[1])
    return 0 if re.fullmatch(r"(?:\d+)?进入", clean) else None


def cow_attempts(records):
    """Submission and result are two receipts for the same entry, not two runs."""
    attempts = {row["attempt"] for row in records if row.get("attempt")
                and row.get("status") in ("submitted", "confirmed")}
    cancelled = {row["attempt"] for row in records if row.get("attempt")
                 and row.get("status") == "cancelled"}
    legacy = [row for row in records if not row.get("attempt")]
    return len(attempts - cancelled) + max(
        sum(row.get("status") == "submitted" for row in legacy),
        sum(row.get("status") == "confirmed" for row in legacy))


def cow_paid_attempts(records):
    """Only explicitly priced bell entries consume the custom weekly quota."""
    priced = [row for row in records if row.get("entry_cost") == 1]
    used = cow_attempts(priced)
    for attempt in {row["attempt"] for row in priced if row.get("attempt")}:
        receipts = [row for row in priced if row.get("attempt") == attempt]
        observed = max((row.get("paid_spent", 0) for row in receipts
                        if type(row.get("paid_spent", 0)) is int and row.get("paid_spent", 0) >= 0), default=0)
        if observed:
            used += max(observed, cow_attempts(receipts)) - cow_attempts(receipts)
    return used


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
        if self.find(r"VICTORY", (50, 25, 450, 110)):
            self.click(640, 360, 1)
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
        clicks = 0
        for _ in range(12):
            menu_open = self.find(r"游戏专属编号", (850, 55, 350, 50))
            if not menu_open:
                if self.node("HomeFlagCloseReturnMain") and clicks < 2:
                    clicks += 1
                    self.click(1236, 36, 1)
                    continue
                self.pause(.4)
                self.capture()
                continue
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
        text = " ".join(row.text for row in self.ocr(r".+", (125, 175, 230, 50)))
        match = re.search(r"([0-5])\s*[/／]\s*5", text)
        if match:
            return int(match[1])
        # After the fifth craft the row is dimmed and a lock covers the label.
        # Read the digits alone, away from that overlay.
        for roi in ((248, 175, 48, 27), (248, 192, 48, 27)):
            for only_rec in (True, False):
                rows = self.ocr(r".+", roi, only_rec=only_rec)
                match = re.fullmatch(r"([0-5])/5", re.sub(r"\s", "", "".join(row.text for row in rows)).replace("／", "/"))
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
        if self.find(r"^宾果", (115, 135, 240, 55)) and self.daily_counter() == 5:
            self.log("今日宾果票券已制作5张，跳过锁定配方")
            return True
        ticket = self.find(r"^宾果票(?:券)?$", (115, 135, 240, 500))
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
                        ):
                    # Both inventory balances independently prove the craft;
                    # the locked recipe counter can be unreadable after 5/5.
                    self.log(f"已确认票券{before_tickets}->{tickets}，南瓜币{before_coins}->{coins}")
                    return True
                if tickets not in (before_tickets, before_tickets + quantity):
                    raise RuntimeError("制作后票券余额异常，不再次制作")
            self.pause(.5)
        raise RuntimeError("已提交一次制作，结果尚未确认，不再次制作")


class RaidSweep(SeasonalScreen):
    label = "个人突袭扫荡"
    timeout = 180

    def dialog(self):
        return (self.find(r"(?:一)?键扫荡", (560, 85, 180, 60))
                and self.find(r"Boss\s*Raid\s*Ticket", (500, 285, 290, 65)))

    def free_remaining(self):
        rows = self.ocr(r".+", (880, 635, 160, 65))
        text = re.sub(r"\s", "", "".join(row.text for row in sorted(rows, key=lambda row: row.box.x))).replace("／", "/")
        match = re.fullmatch(r"扫荡([0-3])/3", text)
        if match:
            return int(match[1])
        # After the third free sweep the counter is replaced by the ticket
        # balance and a plain Sweep caption. This is a paid button, never hit.
        if re.fullmatch(r"\d+扫荡", text):
            return 0
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
        limit = int(self.param.get("limit", 3))
        if not 0 <= limit <= 3:
            raise RuntimeError("个人突袭每日免费次数须为0至3")
        if not limit:
            self.log("次数为0，跳过")
            return True
        previous = self.ledger()
        if previous and previous["status"] not in ("confirmed", "counter_confirmed", "cancelled"):
            remaining = self.free_remaining()
            same_tickets = ("before_tickets" in previous
                            and self.number((1140, 14, 65, 40)) == previous["before_tickets"])
            decreased = (previous.get("before_free") in (1, 2, 3)
                         and remaining == previous["before_free"] - 1)
            if same_tickets and decreased and (previous["status"] == "reward_observed" or remaining == 0):
                self.ledger({**previous, "status": "counter_confirmed", "after_free": remaining,
                             "after_tickets": previous["before_tickets"],
                             "reward_verified": previous["status"] == "reward_observed"})
                self.log("已核对上次免费次数减少且门票未变；不会补点已用掉的次数")
            else:
                raise RuntimeError("今日突袭已经提交过，结果需要核对，不重复扫荡")
        completed = 0
        while completed < 3:
            if self.dialog():
                cancel = self.find(r"^取消$", (300, 550, 650, 110))
                if not cancel:
                    raise RuntimeError("当前是门票扫荡确认框，不消耗门票")
                self.click_row(cancel, .8)
                self.log("已取消门票扫荡，只执行每日免费次数")
                return True
            if not self.find(r"队伍编排", (65, 635, 160, 55)):
                raise RuntimeError("未确认个人突袭扫荡页")
            before_free = self.free_remaining()
            if before_free is None:
                raise RuntimeError("无法确认个人突袭免费次数，不扫荡")
            if before_free == 0 or 3 - before_free >= limit:
                self.log(f"今日已用{3 - before_free}/3次免费扫荡，达到设置上限{limit}次")
                return True
            before = self.number((1140, 14, 65, 40))
            button = self.find(r"^扫荡(?:\s*[0-3]\s*[/／]\s*3)?$", (900, 640, 130, 55))
            if not button:
                raise RuntimeError("未找到个人突袭扫荡入口")
            self.ledger({"status": "unknown", "before_tickets": before, "before_free": before_free})
            self.log(f"免费次数剩余{before_free}/3、门票{before}，提交一次免费扫荡")
            self.click_row(button, .8)
            reward = False
            until = time.monotonic() + 30
            while time.monotonic() < until:
                self.capture()
                if self.close_reward():
                    reward = True
                    self.ledger({"status": "reward_observed", "before_tickets": before, "before_free": before_free})
                    continue
                if self.dialog():
                    cancel = self.find(r"^取消$", (300, 550, 650, 110))
                    if cancel:
                        self.click_row(cancel, .8)
                    raise RuntimeError("免费扫荡出现门票确认框，停止且不确认扣票")
                if self.find(r"队伍编排", (65, 635, 160, 55)):
                    after = self.number((1140, 14, 65, 40))
                    after_free = self.free_remaining()
                    if after != before:
                        raise RuntimeError("免费扫荡后门票变化，停止后续操作")
                    if reward and after_free == before_free - 1:
                        self.ledger({"status": "confirmed", "before_tickets": before, "after_tickets": after,
                                     "before_free": before_free, "after_free": after_free})
                        self.log(f"已确认奖励，免费次数{before_free}->{after_free}，门票保持{after}")
                        completed += 1
                        break
                    if after_free not in (None, before_free, before_free - 1):
                        raise RuntimeError("免费次数变化异常，停止后续操作")
                self.pause(.4)
            else:
                raise RuntimeError("已提交一次扫荡，结果未确认，不再次消耗门票")
        return True


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


class DailyFreeSummon(SeasonalScreen):
    label = "每日免费召唤"
    timeout = 240

    def diamond_balance(self):
        self.home()
        self.click(1236, 36, 1)
        if not self.find(r"游戏专属编号", (850, 55, 350, 50)):
            raise RuntimeError("未确认大厅菜单，无法核对召唤前后钻石")
        value = self.number((850, 655, 105, 42))
        self.click(1236, 36, .8)
        return value

    def select_tab(self, name):
        for step in range(8):
            tab = self.find("^" + name + "$", (35, 90, 190, 600))
            if tab:
                self.click_row(tab, 1)
                for _ in range(8):
                    if self.find("^" + name + "$", (270, 125, 400, 150)):
                        return
                    self.pause(.4)
                    self.capture()
                raise RuntimeError("未确认召唤分类：" + name)
            self.swipe(125, 180, 125, 600) if step < 2 else self.swipe(125, 590, 125, 180)
        raise RuntimeError("没有找到召唤分类：" + name)

    def summon(self, name):
        self.select_tab(name)
        free = self.find(r"^免费$", (740, 655, 150, 45))
        if not free:
            used_node = "Draw_CharacterFreeUsed_Ticket" if name == "领取角色" else "Draw_PetFreeUsed_Ticket"
            known_paid = self.node(used_node) or self.node("Draw_CharacterFreeUsed_Diamond")
            prices = "".join(row.text for row in self.ocr(r".+", (795, 655, 70, 45), only_rec=True))
            if not known_paid and unsigned_number(prices) is None:
                raise RuntimeError(name + "的免费状态无法确认，不召唤")
            self.log(name + "今日免费次数已用完，跳过")
            return
        tickets = self.number((1140, 14, 65, 40))
        button = self.find(r"^召唤1次$", (735, 615, 170, 45))
        if not button:
            raise RuntimeError("未确认免费单次召唤按钮")
        self.log(f"{name}已确认免费，当前召唤券{tickets}，只提交一次")
        self.click_row(button, .8)
        result_seen = False
        until = time.monotonic() + 45
        while time.monotonic() < until:
            self.capture()
            if self.find(r"取消", (300, 400, 650, 160)):
                raise RuntimeError("召唤出现额外确认框，停止且不确认扣费")
            skip = self.find(r"^[Ss][Kk][Ii][Pp]", (1080, 0, 200, 80))
            if skip:
                self.click_row(skip, .8)
                continue
            if self.find(r"蛋壳", (400, 615, 500, 100)):
                self.click(640, 460, .8)
                continue
            view = self.find(r"^查看全部$", (540, 630, 210, 80))
            if view:
                result_seen = True
                self.click_row(view, .8)
                continue
            confirm = self.find(r"^确认$", (540, 630, 210, 80))
            if confirm:
                result_seen = True
                self.click_row(confirm, .8)
                continue
            if self.find("^" + name + "$", (270, 125, 400, 150)):
                after = self.number((1140, 14, 65, 40))
                if after != tickets:
                    raise RuntimeError(name + "召唤券发生变化，停止后续召唤")
                if result_seen and not self.find(r"^免费$", (740, 655, 150, 45)):
                    self.log(f"{name}免费召唤结果已确认，召唤券保持{after}")
                    return
            self.pause(.5)
        raise RuntimeError(name + "已提交一次免费召唤，结果未确认，不重复点击")

    def execute(self):
        before = self.diamond_balance()
        self.open_menu("召唤")
        if self.param.get("inspect_only"):
            return True
        for name in ("领取角色", "领取宠物"):
            self.summon(name)
        after = self.diamond_balance()
        if after != before:
            raise RuntimeError(f"免费召唤前后钻石变化{before}->{after}")
        self.log(f"角色和宠物每日免费召唤已检查，钻石保持{after}")
        return True


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

    def entry_caption(self):
        return " ".join(row.text for row in self.ocr(r".+", (890,635,310,55)))

    def paid_entry_cost(self):
        caption = re.sub(r"\s", "", self.entry_caption())
        if (not re.fullmatch(r"(?:1)?进入", caption)
                or not self.node("LocalSecretCow_BellEntry")
                or self.number((1003,650,30,28)) != 1):
            raise RuntimeError("未确认奶牛入口只消耗1个铃铛，不进入")
        return 1

    def ensure_single_battle(self):
        self.capture()
        state = cow_free_state(self.entry_caption())
        if not self.title() or not self.find(r"^队伍编排$", (65,635,160,55)):
            raise RuntimeError("未确认奶牛副本队伍页，不进入")
        if state in (1,2,3):
            return state, 0
        if state == 0 and getattr(self,"use_custom_count",False):
            return state, self.paid_entry_cost()
        else:
            raise RuntimeError("未确认每周免费次数和队伍页，不进入奶牛副本")

    def battle_active(self):
        # The team page carries a similar stage title. It must have disappeared
        # before an entry can be treated as an observed battle.
        return (self.find(r"秘密奶牛副本.*第\s*\d+\s*层", (960, 75, 300, 55))
                and not self.find(r"^队伍编排$", (65, 635, 160, 55))
                and not self.find(r"^进入(?:\s*[0-3]\s*[/／]\s*3)?$", (1000, 635, 200, 60)))

    def wait_battle_start(self):
        until = time.monotonic() + 15
        while time.monotonic() < until:
            self.capture()
            if self.battle_active():
                self.log("已确认奶牛战斗画面，队伍编排和进入按钮已消失")
                return True
            self.pause(.25)
        raise RuntimeError("点击进入后未确认奶牛战斗，停止追加进入")

    def battle_bells(self):
        # Combat can hide the currency bar. Unrelated text in the old fixed
        # crop must not be interpreted as a balance or repaired by guessing.
        match = self.node("LocalSecretCow_BellBalance")
        if not match:
            return None
        box = match.best_result.box
        x, y, w, h = (box.x, box.y, box.w, box.h) if hasattr(box, "x") else box
        roi = (x + w + 4, max(0, y - 4), min(94, 1280 - x - w - 4), h + 8)
        readings = []
        for only_rec in (False, True):
            rows = [row for row in self.ocr(r".+", roi, only_rec=only_rec) if row.score >= .85]
            if len(rows) != 1:
                return None
            value = unsigned_number(rows[0].text)
            if value is None:
                return None
            readings.append(value)
        return readings[0] if readings[0] == readings[1] else None

    def wait_first_reward(self, bells):
        until = time.monotonic() + 150
        while time.monotonic() < until:
            self.capture()
            reward = self.find(r"(?:传说|英雄|稀有)\s*(?:武器|防具|饰品|符文|辅助道具)", (600,70,400,95))
            if reward or self.find(r"已获得道具|CLEAR|VICTORY", (350,60,650,300)):
                self.log("已确认奶牛战利品，立即退场，停止游戏继续重复挑战")
                return True
            if self.find(r"秘密奶牛副本", (960,75,300,55)):
                current = self.battle_bells()
                if current is not None and current < bells:
                    expected = getattr(self,"expected_entry_cost",0)
                    if current != bells-expected:
                        self.leave_battle()
                        raise RuntimeError(f"铃铛消耗异常{bells}->{current}，已退场并停止")
                    # One bell can be charged at entry. Spending alone is not
                    # a completed battle; keep waiting for actual loot.
            self.pause(.2)
        self.leave_battle()
        raise RuntimeError("奶牛战利品未能确认，已退场，不再进入")

    def leave_battle(self):
        # A task timeout must not prevent the exit that stops the game's own
        # repeat battles. The bounded cleanup still honors a user stop.
        original_deadline = getattr(self, "deadline", None)
        self.deadline = max(original_deadline or 0, time.monotonic() + 65)
        try:
            return self._leave_battle()
        finally:
            if original_deadline is not None:
                self.deadline = original_deadline

    def leave_result(self):
        result_back = self.find(r"^返回$", (865,620,180,80))
        if (not result_back or not self.find(r"^战术$", (1045,620,220,80))
                or not self.find(r"秘密奶牛副本", (960,75,300,55))):
            return False
        checked = self.node("LocalSecretCow_AutoRepeatChecked")
        if checked:
            self.click_row(checked.best_result, .1)
            result_back = self.find(r"^返回$", (865,620,180,80))
            if (not result_back or not self.find(r"^战术$", (1045,620,220,80))):
                return True
            if self.node("LocalSecretCow_AutoRepeatChecked"):
                return True
            self.log("已关闭奶牛结算页自动再次挑战")
        self.click_row(result_back, .2)
        self.log("已从奶牛结算页返回，阻止5秒自动再次挑战")
        return True

    def _leave_battle(self):
        """Leave through the menu's 退场 button and verify the village/lobby.

        The pin below the menu opens stage details while combat continues.
        Neither that team panel nor its floor list proves the battle stopped.
        """
        attempts, retry_after = 0, 0
        exit_submitted = False
        until = time.monotonic() + 60
        while time.monotonic() < until:
            self.capture()
            if self.leave_result():
                continue
            if self.find(r"是否.*(?:退场|退出|离开)", (330,250,650,200)):
                leave = self.find(r"^(?:退场|退出|确认|确定)$", (500,400,420,140))
                if not leave:
                    raise RuntimeError("已打开退场提示，但没有确认退场按钮")
                self.click_row(leave, .8)
                self.log("已确认退场，核对是否离开奶牛战斗")
                continue
            exit_button = self.find(r"^退场$", (875,640,185,65))
            if exit_button and not exit_submitted:
                self.click_row(exit_button, .3)
                exit_submitted = True
                self.log("已点击右上菜单中的退场，等待回到村庄")
                continue
            if self.find(r"HOT\s*DEAL|牛仔女王的提议", (80,90,1110,480)):
                self.click(1236,36,.3)
                continue
            if self.find(r"^背包$", (125,5,90,45)):
                raise RuntimeError("退场期间出现背包，停止其他导航并保留画面供检查")
            stage_panel = self.title() and (
                self.find(r"^队伍编排$", (65,635,160,55))
                or self.find(r"^选择$", (890,630,310,50)))
            if stage_panel:
                # This panel can be opened over a live battle by the map icon.
                # Closing it is not an exit receipt.
                self.click(1236, 36, .2)
                continue
            stage = self.find(r"秘密奶牛副本", (960,75,300,55))
            # The general home template can also match during combat. Require
            # the real lobby's three bottom navigation labels and no Cow HUD.
            if not stage:
                village = (self.find(r"^冒险$", (1080,80,170,90))
                           and self.node("LocalVillageOpenMenu"))
                lobby = all(self.find(pattern,roi) for pattern,roi in (
                    (r"^战斗$",(900,640,100,65)), (r"^角色$",(1030,640,100,65)),
                    (r"^召唤$",(1150,640,125,65))))
                if village or lobby:
                    self.log("已确认离开奶牛副本，当前在村庄" if village else "已确认离开奶牛副本，当前在大厅")
                    return True
            if stage and not exit_submitted and time.monotonic() >= retry_after:
                self.click(1236,36,.3)
                attempts += 1
                retry_after = time.monotonic() + 1.5
                continue
            self.pause(.4)
        raise RuntimeError("未能确认已退出奶牛副本，请从右上角手动退场")

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
        return self.find(r"秘密奶牛副本.*第\s*\d+\s*层", (900, 110, 300, 50))

    def bells(self):
        return self.number((1105, 15, 100, 40))

    def open_dungeon(self):
        if self.title() and self.find(r"^队伍编排$", (65,635,160,55)):
            return
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
        self.use_custom_count = self.param.get("use_custom_count",False)
        if not isinstance(self.use_custom_count,bool):
            raise RuntimeError("使用自定义次数必须为开关值")
        limit = None
        if self.use_custom_count:
            raw = self.param.get("limit",10)
            if isinstance(raw,bool) or not re.fullmatch(r"(?:0|[1-9][0-9]?)",str(raw)):
                raise RuntimeError("自定义铃铛次数须为0至99")
            limit = int(raw)
        if self.param.get("inspect_only"):
            self.open_dungeon()
            if not self.to_team():
                raise RuntimeError("未确认奶牛副本队伍页")
            state = cow_free_state(" ".join(row.text for row in self.ocr(r".+", (890, 635, 310, 55))))
            self.log(f"只核对未进入：免费次数{state}，铃铛{self.bells()}")
            return True
        records = self.ledger()
        used = cow_paid_attempts(records)
        if records and records[-1].get("status") == "submitted":
            raise RuntimeError("上次奶牛副本进入结果尚未核对，不重复进入")
        if self.use_custom_count:
            self.deadline = time.monotonic()+max(900,(max(0,limit-used)+3)*240+60)
        self.open_dungeon()
        while True:
            if not self.to_team():
                raise RuntimeError("未确认奶牛副本的进入按钮")
            floor = self.title().text
            state = cow_free_state(self.entry_caption())
            if state is None or state == -1:
                raise RuntimeError("未确认奶牛副本进入次数，不进入")
            if state == 0 and not self.use_custom_count:
                self.log("本周免费次数已用完（进入需要消耗铃铛），不使用铃铛，正常结束")
                return True
            if state == 0 and used >= limit:
                self.log(f"本周已由脚本使用铃铛{used}次，达到设置的{limit}次；免费次数另算，正常结束")
                return True
            state, cost = self.ensure_single_battle()
            before = self.bells()
            if cost and before < cost:
                self.log(f"铃铛不足，当前{before}个；本周已由脚本使用铃铛{used}次，本轮结束")
                return True
            self.expected_entry_cost = cost
            enter = self.find(r"进入", (1000, 635, 200, 60))
            attempt = uuid4().hex
            self.ledger({"status": "submitted", "attempt": attempt, "floor": floor, "bells": before,
                         "before_free": state,"entry_cost":cost,"custom_count":self.use_custom_count})
            progress = f"本周铃铛{used+1}/{limit}" if cost else f"免费剩余{state}/3，不计入自定义次数"
            self.log(f"确认{'使用1个铃铛' if cost else '免费'}进入，挑战{floor}（{progress}），铃铛{before}")
            self.click_row(enter, 1)
            if not self.battle(before, state):
                self.ledger({"status": "cancelled", "attempt": attempt, "floor": floor, "bells": before,
                             "entry_cost":cost})
                return True
            self.ledger({"status": "confirmed", "attempt": attempt, "floor": floor, "bells": before,
                         "before_free": state, "after_free": self.last_cow_free,
                         "entry_cost":cost,"paid_spent":cost,"custom_count":self.use_custom_count})
            used += cost

    def battle(self, bells, before_free):
        try:
            self.wait_battle_start()
            self.wait_first_reward(bells)
            self.leave_battle()
        except Exception:
            # A delayed transition may enter combat after a recognition
            # timeout. Always attempt containment before returning failure.
            self.leave_battle()
            raise
        self.open_dungeon()
        if not self.to_team():
            raise RuntimeError("退场后未确认奶牛副本队伍页，不再次进入")
        after = self.bells()
        cost = getattr(self,"expected_entry_cost",0)
        if after != bells-cost:
            raise RuntimeError(f"铃铛数量变化{bells}->{after}，已退场并停止后续挑战")
        after_free = cow_free_state(" ".join(row.text for row in self.ocr(r".+", (890,635,310,55))))
        valid_free = cost == 0 and before_free in (1,2,3) and after_free == before_free-1
        valid_paid = cost == 1 and before_free == 0 and after_free == 0
        if not (valid_free or valid_paid):
            raise RuntimeError("退场后剩余免费次数未确认，不再次进入")
        self.last_cow_free = after_free
        self.log(f"本次战利品与退场已确认，免费次数{before_free}->{after_free}，铃铛{bells}->{after}")
        return True


class CowLeave(SecretCow):
    timeout = 90

    def execute(self):
        return self.leave_battle()


ACTIONS.update({"LocalDailyFreeSummon": DailyFreeSummon(), "LocalFriendGift": FriendGift(),
                "LocalSecretCow": SecretCow(), "LocalSecretCowExit": CowLeave()})
