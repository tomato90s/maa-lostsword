"""Bounded daily flows for the current Chinese Lost Sword UI."""
import json
import re
import time

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
            self.deadline = time.monotonic() + self.timeout
            self.capture()
            return self.execute()
        except Exception as exc:
            print(f"[{self.label}] {exc}", flush=True)
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
        if self.find(r"已获得道具|扫荡奖励|合成结果|领取成功", (350, 80, 650, 320)):
            self.click(640, 680)
            return True
        return False


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
        rows = self.ocr(r".+", (174, 10, 245, 45))
        rows = [r for r in rows if r.score >= .7 and not re.search(r"\d|对话|角色", r.text)]
        return character_key(max(rows, key=lambda r: r.score).text) if rows else None

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

    def execute(self):
        limit = max(0, min(7, int(self.param.get("limit", 7))))
        if not limit:
            self.log("本轮上限为0，跳过")
            return True
        self.seen = set()
        self.seen_aliases = set()
        pending_candidate = None
        completed = 0
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
        while completed < limit:
            self.capture()
            name = self.detail_name()
            if name:
                if pending_candidate:
                    self.seen_aliases.add(pending_candidate)
                    pending_candidate = None
                if not self.remaining(detail=True):
                    self.log(f"今日次数已用完，本轮完成{completed}人")
                    return True
                already_done = self.find(r"对话完成|已完成|1\s*/\s*1", (735, 575, 235, 90))
                if name in self.seen or already_done:
                    self.seen.add(name)
                    self.click(1235, 37)
                    continue
                button = self.find(r"^对话\s*[>›]?$", (738, 625, 220, 42))
                if not button:
                    raise RuntimeError(f"{name}的对话状态无法确认，停止")
                before = self.remaining(detail=True)
                # Remember before pressing: never retry the same person on an
                # ambiguous result, even when their affection level stays low.
                self.seen.add(name)
                self.click_row(button)
                self.finish_conversation(name, before)
                completed += 1
                self.log(f"已完成{completed}/{limit}人：{name}")
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
                self.log(f"没有其他可对话角色，本轮完成{completed}人，正常结束")
                return True
            last_bottom = signature
            self.swipe(405, 618, 405, 195)
            scrolls += 1
        self.log(f"达到本轮{limit}人上限，结束；每个角色只处理一次")
        return True

    def finish_conversation(self, name, before):
        until = time.monotonic() + 55
        while time.monotonic() < until:
            self.capture()
            if self.detail_name():
                after = self.remaining(detail=True)
                done = self.find(r"对话完成|已完成|1\s*/\s*1", (735, 575, 235, 90))
                if done and after == before - 1:
                    return
                # Do not click the talk button again after returning from a
                # conversation; only advance actual narrative screens below.
                self.pause(.4)
                continue
            if self.find(r"Log|LOG", (24, 4, 115, 65)):
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
        if not self.find(r"自动登录", (955, 640, 300, 65)):
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
            back = self.find(r"返回", (1070, 620, 180, 65))
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


class ShopFreeGift(ScreenAction):
    label = "每日免费礼包"
    timeout = 75

    def finish(self, message):
        # Return to the parent JumpBack chain so enabled exchange tasks can run.
        self.context.override_pipeline({"商店-商品": {"enabled": False}})
        self.log(message)
        return True

    def execute(self):
        submitted = False
        reward_seen = False
        popup_opened = False
        products_clicked = False
        for _ in range(65):
            self.capture()
            if self.close_reward():
                reward_seen = True
                continue
            popup = self.find(r"购买商品", (540, 75, 210, 60))
            if popup:
                if not self.find(r"每日免费礼包", (270, 480, 260, 65)):
                    raise RuntimeError("当前弹窗不是每日免费礼包，不购买")
                popup_opened = True
                bought = self.find(r"已购买|已领取|售罄|购买完成|售完", (250, 150, 730, 480))
                ratios = self.ocr(r".+", (305, 155, 240, 40))
                bought = bought or any(re.search(r"1\s*[/／]\s*1", r.text) for r in ratios)
                if bought or reward_seen:
                    self.click(1018, 103)
                    return self.finish("礼包已领取，正常结束并继续后续任务")
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
                    return self.finish("免费礼包领取完成，继续后续任务")
                gift = self.find(r"每日免费礼包", (340, 140, 230, 55))
                if gift and not popup_opened:
                    # The card can already be marked sold out without a popup.
                    card_rows = self.ocr(r".+", (335, 175, 230, 40))
                    if (self.find(r"已购买|已领取|售罄|售完", (315, 195, 265, 215))
                            or any(re.search(r"1\s*[/／]\s*1", r.text) for r in card_rows)):
                        return self.finish("每日礼包已领取，正常结束并继续后续任务")
                    self.click_row(gift)
                    popup_opened = True
                    continue
                if not products_clicked and not popup_opened:
                    product = self.find(r"^商品$", (350, 75, 135, 55))
                    if product:
                        self.click_row(product)
                        products_clicked = True
                        continue
            self.pause(.4)
        raise RuntimeError("免费礼包结果未确认，不重复购买")


ACTIONS = {"LocalGuildClaimReward": GuildClaimReward(), "LocalFavorTalk": FavorTalk(),
           "LocalArenaDaily": ArenaDaily(), "LocalGemCombine": GemCombine(),
           "LocalSquadDaily": SquadDaily(), "LocalShopFreeGift": ShopFreeGift(),
           "LocalStonehengeGate": StonehengeGate()}
