"""Resource preference policy for the labyrinth's automatic progression."""
import json
import re
import time
from datetime import datetime
from pathlib import Path

from maa.pipeline import JTemplateMatch

from agent.seasonal_actions import SeasonalScreen

DEFAULT_PRIORITIES = ("石头", "经验宝箱", "金币宝箱")


def resource_kind(text):
    text = re.sub(r"\s", "", text)
    if re.search(r"矿石|石头|石料|强化石|魔法石|煤炭", text):
        return "石头"
    if re.search(r"经验.*(?:宝箱|箱)|(?:宝箱|箱).*经验", text):
        return "经验宝箱"
    if re.search(r"金币.*(?:宝箱|箱)|(?:宝箱|箱).*金币", text):
        return "金币宝箱"
    return None


def choose_resource(available, priorities=DEFAULT_PRIORITIES, allow_other=True):
    """Choose only from resources positively found as available on the page.

    `available` is in screen order; a fallback never invents an absent resource.
    The page reader is responsible for excluding disabled or paid choices.
    """
    if not isinstance(allow_other, bool):
        raise ValueError("是否更换其他资源必须为开关值")
    available = list(dict.fromkeys(available))
    for name in dict.fromkeys(priorities):
        if name in available:
            return name
    return available[0] if allow_other and available else None


class MazeDaily(SeasonalScreen):
    label = "迷宫"
    timeout = 2400

    def journal(self, **record):
        path = Path(__file__).resolve().parents[1] / "debug" / f"maze-{datetime.now():%Y-%m-%d}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": datetime.now().astimezone().isoformat(), **record}, ensure_ascii=False) + "\n")

    def story(self):
        # Combat scenery can produce spurious "speaker" OCR. Require the
        # actual dialogue continue marker even when a name is recognized.
        return bool(self.find(r".+", (30,595,1170,55)) and self.dialogue_continue())

    def dialogue_continue(self):
        result = self.context.run_recognition_direct("TemplateMatch", JTemplateMatch(
            template=["local_maze_dialogue_next.png"], threshold=[.85], roi=[1190,625,90,95]), self.image)
        return bool(result and result.hit)

    def cards(self):
        return (self.find(r"^选择$", (490,610,300,85))
                and self.find(r".+", (400,65,480,80)))

    def select_card(self):
        # The first click turns all three cards over. Only then can their
        # rewards be ranked; the hidden card back has no resource identity.
        rows = self.ocr(r".+", (215,325,850,180))
        if not any(resource_kind(r.text) or re.search(r"增益型|消耗型|恢复型|提升|恢复", r.text) for r in rows):
            self.click(640,380,2)
            rows = self.ocr(r".+", (215,325,850,180))
        candidates = []
        for index, x in enumerate((340,640,940)):
            local = [r for r in rows if abs(r.box.x + r.box.w / 2 - x) < 140]
            text = " ".join(r.text for r in local)
            if not text or re.search(r"钻石|铃铛|门票|购买|阵亡|献祭", text):
                continue
            kind = next((resource_kind(r.text) for r in local if resource_kind(r.text)), None)
            candidates.append((kind or "其他资源", x, text, index))
        choice = choose_resource([c[0] for c in candidates], self.priorities, self.allow_other)
        if choice is None:
            raise RuntimeError("当前没有首选资源，已按设置停止选卡")
        chosen = next(c for c in candidates if c[0] == choice)
        self.journal(status="card_selected", resource=choice, text=chosen[2])
        self.log("迷宫选卡：" + chosen[2])
        self.click(chosen[1],410,.6)
        button = self.find(r"^选择$", (490,610,300,85))
        if not button or not self.cards():
            raise RuntimeError("选卡确认界面变化，停止提交")
        self.click_row(button,2)

    def advance_story(self):
        # Choice buttons overlap the upper story area. Read them before
        # advancing text so a dialogue click cannot silently choose a trap.
        if self.find(r"迷宫探索中发现了水井", (30,595,1170,55)):
            drink = self.find(r"^喝井水[。.!！]?$", (400,190,500,285))
            decline = self.find(r"^不喝[。.!！]?$", (400,190,500,285))
            if not (drink and decline):
                raise RuntimeError("水井剧情选项未识别完整，保留画面")
            self.journal(status="story_selected", event="well", choice=decline.text)
            self.log("发现水井，选择不喝，继续迷宫")
            self.click_row(decline,1)
            return
        stay = self.find(r"^保持不动[。.!！]?$", (400,190,500,285))
        if stay:
            if not (self.find(r"^最大生命值减少[。.!！]?$", (400,190,500,285))
                    and self.find(r"^受到伤害[。.!！]?$", (400,190,500,285))):
                raise RuntimeError("陷阱剧情选项未识别完整，保留画面")
            self.journal(status="story_selected", event="trap", choice=stay.text)
            self.log("发现陷阱选择，选择保持不动，继续迷宫")
            self.click_row(stay,1)
            return
        if self.find(r"三个不同颜色的按键", (30,595,1170,55)):
            buttons = [self.find(r"^按下" + color + r"色按键[。.!！]?$", (400,190,500,285))
                       for color in ("红", "蓝", "黄")]
            if not all(buttons):
                raise RuntimeError("三色按键剧情选项未识别完整，保留画面")
            # The recorded labyrinth event favors blue over the red/yellow traps:
            # https://techpost.tistory.com/371
            blue = buttons[1]
            self.journal(status="story_selected", event="colored_buttons", choice=blue.text)
            self.log("发现三色按键，选择蓝色按键，继续迷宫")
            self.click_row(blue,1)
            return
        choice = self.find(r"^魔法卡[!！]?$", (400,190,500,285))
        if not choice:
            choice = self.find(r"^无视[。.!！]?$|^离开[。.!！]?$", (400,190,500,285))
        if not choice:
            pattern = r"^捡起羽毛[。.!！]?$" if self.allow_other else r"^不去碰[。.!！]?$"
            choice = self.find(pattern, (400,190,500,285))
        if choice:
            self.click_row(choice,1)
            return
        if self.find(r"^陷阱卡[!！]?$", (400,190,500,285)):
            raise RuntimeError("剧情选项未识别完整，停止选择")
        options = self.ocr(r".+", (420,180,440,300))
        if options:
            raise RuntimeError("出现未识别的迷宫剧情选项，保留画面")
        self.click(640,625,1.2)

    def start_auto(self):
        if not self.find(r"自动进行迷宫", (480,60,330,80)):
            button = self.find(r"^自动进行$", (0,590,310,125))
            if not button:
                raise RuntimeError("未找到迷宫自动进行")
            self.click_row(button,1)
        if not self.find(r"自动进行迷宫", (480,60,330,80)):
            raise RuntimeError("自动进行设置未打开")
        # Keep the user's difficulty and route priorities. The resource
        # preference applies to revealed rewards, independently of routes.
        if not self.find(r"优先级[1-6]", (360,215,650,265)):
            raise RuntimeError("未确认迷宫路线设置")
        button = self.find(r"^自动进行$", (490,495,300,85))
        if not button:
            raise RuntimeError("未确认迷宫开始按钮")
        self.journal(status="auto_submitted", priorities=self.priorities, allow_other=self.allow_other)
        self.click_row(button,2)

    def page(self):
        return self.find(r"迷宫\s*\d+\s*层", (500,5,300,85))

    def completed(self):
        # At the end the title changes from 迷宫50层 to 完成 and the
        # player's marker is on the final Minotauros King node.
        return (self.find(r"^完成$", (500,5,300,85))
                and self.find(r"Minotauros\s*King", (900,420,370,100)))

    def final_team(self):
        return (self.find(r"迷宫\s*51\s*层", (925,60,300,70))
                and self.find(r"队伍编排", (25,625,220,70))
                and self.find(r"^出发$", (890,635,315,60)))

    def in_battle(self):
        return (self.find(r"^BATTLE$", (545,30,230,65))
                and self.find(r"牛头人王", (450,75,400,80)))

    def depart_final(self):
        caption = "".join(row.text for row in self.ocr(r".+", (890,635,315,60)))
        if not self.final_team() or re.sub(r"\s", "", caption) != "出发":
            raise RuntimeError("迷宫最终战入口不明确或出现费用，停止进入")
        self.journal(status="final_boss_submitted", floor=51)
        self.click_row(self.find(r"^出发$", (890,635,315,60)),2)

    def open_maze(self):
        if self.page() or self.completed():
            return
        self.open_menu("战斗")
        for _ in range(12):
            tab = self.find(r"^普通$", (110,65,170,65))
            if tab:
                self.click_row(tab, .8)
                break
            self.pause(.3)
            self.capture()
        else:
            raise RuntimeError("未确认战斗页的普通分类")
        for _ in range(8):
            card = self.find(r"迷宫", (0,535,1280,65))
            if card:
                self.click(card.box.x + card.box.w // 2, 400, .8)
                break
            self.swipe(1100,400,200,400)
        else:
            raise RuntimeError("普通战斗页没有找到迷宫入口")
        until = time.monotonic() + 20
        while time.monotonic() < until:
            self.capture()
            if self.page() or self.completed():
                return
            self.pause(.3)
        raise RuntimeError("点击迷宫入口后未确认迷宫页面")

    def execute(self):
        raw = self.param.get("priorities", list(DEFAULT_PRIORITIES))
        if isinstance(raw, str):
            raw = raw.split(",")
        if not isinstance(raw, list) or len(raw) != 3 or set(raw) != set(DEFAULT_PRIORITIES):
            raise RuntimeError("资源优先级须包含石头、经验宝箱、金币宝箱各一次")
        self.priorities = raw
        self.allow_other = self.param.get("allow_other", True)
        if not isinstance(self.allow_other, bool):
            raise RuntimeError("缺少首选时更换资源须为开关值")
        if self.completed():
            self.journal(status="skipped", reason="weekly_completed", evidence="完成标题和最终Boss路线")
            self.log("本周迷宫已完成，自动跳过")
            return True
        if not (self.page() or self.story() or self.cards() or self.final_team() or self.in_battle()
                or self.find(r"VICTORY", (40,20,470,150))):
            self.open_maze()
        if self.completed():
            self.journal(status="skipped", reason="weekly_completed", evidence="完成标题和最终Boss路线")
            self.log("本周迷宫已完成，自动跳过")
            return True
        if self.param.get("inspect_only"):
            self.log("已打开迷宫，尚未提交挑战")
            return True
        last_signature, last_change = None, time.monotonic()
        unknown_since = None
        started = not bool(self.page())
        while True:
            self.capture()
            rows = self.ocr()
            text = " ".join(r.text for r in rows)
            signature = tuple(re.sub(r"[\s。.!！,，]", "", r.text) for r in rows)
            if signature != last_signature:
                last_signature, last_change = signature, time.monotonic()
            if time.monotonic() - last_change > 150:
                raise RuntimeError("迷宫150秒没有实质画面变化，停止本项")
            if re.search(r"钻石.*不足|购买次数|补充.*(?:门票|铃铛)|网络错误|连接失败", text):
                raise RuntimeError("迷宫出现购买或网络提示，停止本项")
            recognized = bool(self.in_battle() or self.cards() or self.story() or self.final_team()
                              or self.page() or self.completed()
                              or self.find(r"VICTORY|DEFEAT", (40,20,600,210))
                              or self.find(r"已获得道具", (420,220,440,130)))
            unknown_since = None if recognized else unknown_since or time.monotonic()
            if unknown_since and time.monotonic() - unknown_since > 25:
                raise RuntimeError("迷宫出现未知画面超过25秒，保留画面并停止")
            if self.in_battle() and not self.find(r"VICTORY|DEFEAT", (40,20,600,210)):
                self.pause(.8)
            elif self.cards():
                self.select_card()
            elif self.story():
                self.advance_story()
            elif self.final_team():
                self.depart_final()
            elif self.find(r"VICTORY", (40,20,470,150)):
                self.journal(status="victory_observed", text=text)
                self.click(640,360,1.5)
            elif self.find(r"DEFEAT", (40,20,600,210)):
                raise RuntimeError("迷宫战斗失败，本轮不自动重试")
            elif self.find(r"已获得道具", (420,220,440,130)):
                self.journal(status="reward_observed", text=text)
                self.click(640,680,1)
            elif self.completed():
                self.journal(status="completed", text=text)
                self.log("已确认迷宫通关")
                return True
            elif self.page():
                if self.find(r"迷宫\s*50\s*层", (500,5,300,85)) and self.find(r"Minotauros\s*King", (900,420,370,100)):
                    self.click(1060,380,1)
                elif self.find(r"自动进行中|停止自动|自动结束", (0,585,380,130)):
                    started = True
                    self.pause(1)
                elif not started:
                    self.start_auto()
                    started = True
                else:
                    # Between an event and its reward the map can flash in
                    # before the automatic movement resumes.
                    self.pause(1)
            else:
                # Battles and loading continue without repeated input.
                self.pause(.8)


ACTIONS = {"LocalMazeDaily": MazeDaily()}
