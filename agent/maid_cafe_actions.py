"""Weekly gold orders from the village's maid Rita."""
import json
import re
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from maa.pipeline import JTemplateMatch
from agent.seasonal_actions import game_week, unsigned_number
from agent.village_actions import VillageHunt, LobbyBounce


FOODS = (
    ("coffee", "心动美式咖啡", r"心动.*美式咖啡", 50000, 367),
    ("cookies", "手作女仆曲奇", r"手作女仆曲奇", 150000, 459),
    ("parfait", "坠入爱河芭菲", r".*爱河芭菲", 250000, 551),
    ("omurice", "必杀！黄金蛋包饭", r".*黄金蛋包饭.*", 500000, 643),
)


def weekly_count(text):
    clean = re.sub(r"[\s♡♥❤\ufe0f]", "", text).replace("／", "/")
    match = re.fullmatch(r"每周([0-5])/5", clean)
    return int(match[1]) if match else None


def cafe_progress(rows):
    levels, ratios = set(), set()
    for text in rows:
        level = re.fullmatch(r"Lv[.。]?\s*(\d+)", text, re.I)
        if level:
            levels.add(int(level[1]))
        clean = re.sub(r"[\s,，.。:：;；]", "", text).replace("／", "/")
        ratio = re.fullmatch(r"(\d+)/(\d+)", clean)
        if ratio and 0 <= int(ratio[1]) < int(ratio[2]):
            ratios.add((int(ratio[1]), int(ratio[2])))
    return (levels.pop(), *ratios.pop()) if len(levels) == len(ratios) == 1 else None


class MaidCafe(VillageHunt):
    label = "女仆店每周属性"
    timeout = 900

    def journal(self, record=None):
        path = Path(__file__).resolve().parents[1] / "debug" / "maid-cafe-weekly.jsonl"
        if record is None:
            return [json.loads(line) for line in path.read_text("utf-8").splitlines()] if path.exists() else []
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": datetime.now().astimezone().isoformat(),
                                     "week": game_week(), "username": self.username, **record},
                                    ensure_ascii=False) + "\n")
            stream.flush()

    def match(self, template, roi, threshold=.85):
        result = self.context.run_recognition_direct("TemplateMatch", JTemplateMatch(
            template=template if isinstance(template, list) else [template],
            roi=list(roi), threshold=[threshold]), self.image)
        return result.best_result.box if result and result.hit else None

    def room(self):
        return self.find(r"^(?:女仆丽塔|艾米|克拉拉)$", (0, 155, 1260, 220))

    def menu(self):
        return self.match("local_maid_cafe_menu.png", (560, 0, 420, 110))

    def walk(self, dx, dy, duration):
        if not self.village():
            raise RuntimeError("未确认村庄移动界面，停止走动")
        scale = max(abs(dx), abs(dy), 1)
        end = (158 + int(75*dx/scale), 540 + int(75*dy/scale))
        if not self.context.tasker.controller.post_swipe(158, 540, *end, duration).wait().succeeded:
            raise RuntimeError("前往女仆店时移动失败")
        self.pause(.5)
        self.capture()

    def enter_cafe_room(self):
        self.enter()
        if not self.room():
            self.leave_spawn()
        for _ in range(32):
            self.capture()
            if self.room():
                break
            if not self.village():
                self.pause(.5)
                continue
            door = self.match("local_maid_cafe_door.png", (0, 70, 1280, 390), .82)
            player = self.player()
            if door and player:
                x, y, w, h = door
                dx, dy = x+70-player[0], y+380-player[1]
                self.walk(dx, dy, min(260, max(80, int(max(abs(dx), abs(dy))*1.15))))
            else:
                # Search the street below the INN return circle.
                self.leave_spawn()
                self.move(1, 0, 400)
        else:
            raise RuntimeError("没有找到女仆店入口")

    def open_cafe(self):
        for attempt in range(3):
            try:
                self.enter_cafe_room()
                break
            except LobbyBounce:
                self.trace_navigation()
                if attempt == 2:
                    raise
                self.log("进村寻店时回到大厅，重新进入并先离开出生光圈")
        for _ in range(25):
            self.capture()
            if self.menu():
                return
            order = self.find(r"^点单$", (220, 140, 380, 330))
            if order:
                self.click_row(order, 1)
                continue
            rita = self.find(r"^女仆丽塔$", (0, 155, 1260, 220))
            player = self.player()
            if rita and player:
                dx = rita.box.x+rita.box.w/2-player[0]
                # The counter blocks walking closer, but Rita's interaction
                # button is already available from roughly 200 pixels away.
                if abs(dx) <= 260:
                    bubble = self.match("local_maid_cafe_interact.png", (740, 565, 100, 90))
                    if bubble:
                        x, y, w, h = bubble
                        self.click(x+w/2, y+h/2, .8)
                        continue
                    self.walk(0, -1, 100)
                else:
                    self.walk(dx, 0, min(400, max(80, int(abs(dx)*1.2))))
            elif self.village():
                self.walk(-1, 0, 400)
            else:
                self.pause(.5)
        raise RuntimeError("没有确认女仆丽塔的点单菜单")

    def count(self, food):
        y = food[4]
        rows = self.ocr(r".+", (730, y-45, 465, 85))
        if not any(re.search(food[2], row.text) for row in rows):
            raise RuntimeError(f"未确认餐点：{food[1]}")
        values = {weekly_count(row.text) for row in rows} - {None}
        if len(values) != 1:
            raise RuntimeError(f"{food[1]}的每周次数无法确认")
        return values.pop()

    def price(self, food):
        y = food[4]
        price = self.number((1070, y-22, 115, 42))
        coin = self.match(["local_maid_cafe_gold.png", "local_maid_cafe_gold_alt.png"],
                          (1015, y-22, 70, 44), .9)
        if price != food[3] or not coin:
            raise RuntimeError(f"{food[1]}没有确认固定金币价格，不点单")
        return price

    def stats(self):
        return [row.text for row in self.ocr(r".+", (615, 105, 590, 210))]

    def recover(self):
        records = self.journal()
        settled = {r.get("attempt") for r in records if r.get("status") in ("confirmed", "unchanged_observed")}
        for row in records:
            if (row.get("status") != "submitted" or row.get("attempt") in settled
                    or row.get("week") != game_week() or row.get("username") != self.username):
                continue
            food = next((f for f in FOODS if f[0] == row.get("food")), None)
            if food is None:
                raise RuntimeError("上次女仆店点单结果未核对，不重复购买")
            current = self.count(food)
            progress = cafe_progress(row.get("stats", []))
            if current == row["before"] and progress is not None:
                unchanged = True
                for _ in range(3):
                    self.pause(1)
                    self.capture()
                    if (not self.menu() or self.count(food) != current
                            or cafe_progress(self.stats()) != progress):
                        unchanged = False
                        break
                if unchanged:
                    # The user authorized the remaining weekly quota. Keep the
                    # original submission plus its unchanged UI observations;
                    # any later order still checks the game's five-order cap.
                    self.journal({"status":"unchanged_observed", "attempt":row["attempt"], "food":food[0],
                                  "count":current, "progress":progress, "fresh_observations":3})
                    self.log(f"{food[1]}上次点击后次数及经验连续保持不变，继续补齐每周剩余额度")
                    continue
                current = self.count(food)
            if current != row["before"]+1:
                raise RuntimeError("上次女仆店点单结果未核对，不重复购买")
            self.journal({"status": "confirmed", "attempt": row["attempt"], "food": food[0],
                          "before": row["before"], "after": row["before"]+1, "gold":food[3], "recovered": True})
            self.log(f"已恢复{food[1]}的上次点单确认")

    def purchase(self, food, before):
        price = self.price(food)
        attempt = uuid4().hex
        self.journal({"status": "submitted", "attempt": attempt, "food": food[0],
                      "before": before, "gold": price, "stats": self.stats()})
        self.click(1120, food[4], 1)
        confirm_sent = False
        until = time.monotonic()+25
        while time.monotonic() < until:
            self.capture()
            if self.find(r"金币不足|货币不足|资源不足", (320, 240, 650, 210)):
                raise RuntimeError("女仆店金币不足，停止后续点单")
            if self.menu():
                after = self.count(food)
                if after == before+1:
                    self.journal({"status": "confirmed", "attempt": attempt, "food": food[0],
                                  "before": before, "after": after, "gold": price, "stats": self.stats()})
                    self.log(f"{food[1]}已确认{after}/5，本次花费{price}金币")
                    self.pause(.8)
                    self.capture()
                    return
                if after != before:
                    raise RuntimeError("点单次数变化异常，停止后续购买")
            elif not confirm_sent:
                # An optional confirmation must quote this exact dish and gold cost.
                text = " ".join(r.text for r in self.ocr(r".+", (270, 175, 750, 340)))
                confirm = self.find(r"^(?:确认|确定)$", (360, 420, 580, 160))
                amounts = [unsigned_number(value) for value in re.findall(r"[\d,，]+", text)]
                if (confirm and re.search(food[2], text) and "金币" in text and price in amounts):
                    self.click_row(confirm, 1)
                    confirm_sent = True
                    continue
            self.pause(.5)
        raise RuntimeError("已提交一次女仆店点单，结果未确认，不再次点击")

    def execute(self):
        selected = []
        for food in FOODS:
            enabled = self.policy("LocalMaidCafe_" + food[0]).get("enabled")
            if not isinstance(enabled, bool):
                raise RuntimeError("女仆店餐点开关必须为开启或关闭")
            if enabled:
                selected.append(food)
        if not selected:
            self.log("四项餐点均关闭，跳过女仆店")
            return True
        self.home()
        name = self.find(r"\S+", (120, 45, 180, 50))
        if not name:
            raise RuntimeError("未确认当前角色名称")
        self.username = name.text.strip()
        self.open_cafe()
        self.recover()
        self.trace(0, None, [])
        start = self.stats()
        spent, orders = 0, 0
        for food in selected:
            before = self.count(food)
            while before < 5:
                self.purchase(food, before)
                spent += food[3]
                orders += 1
                before += 1
                self.trace(orders, None, [])
            self.log(f"{food[1]}本周已买满5/5")
        self.log(f"点单完成：本次{orders}份、共{spent}金币；属性页面{start} -> {self.stats()}")
        self.click(1233, 38, .8)
        self.home()
        return True


ACTIONS = {"LocalMaidCafe": MaidCafe()}
