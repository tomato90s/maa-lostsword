"""Finn's weekly ticket race: one random runner, a durable submission, one result."""
import json
import os
import re
import secrets
import time
from datetime import datetime
from pathlib import Path
from uuid import uuid4

from maa.pipeline import JTemplateMatch
from agent.seasonal_actions import game_week
from agent.village_actions import VillageHunt


ROW_Y = (238, 318, 398, 478, 556)
RANK_REWARDS = (500, 400, 350, 300, 250)


def race_seconds(text):
    match = re.fullmatch(r"\s*(\d{1,2})\s*[:：]\s*([0-5]\d)\s*", text)
    return int(match[1])*60+int(match[2]) if match else None


def pending_race(records, username, week):
    terminal = {r.get("attempt") for r in records
                if r.get("status") in ("settled", "not_submitted")}
    rows = [r for r in records if r.get("status") == "submitted"
            and r.get("username") == username and r.get("attempt") not in terminal]
    if len(rows) > 1:
        raise RuntimeError("有多笔史莱姆应援未核对，停止新增投注")
    # An old unresolved submission must also block a fresh week.
    return rows[0] if rows else None


def expected_reward(tickets, rank):
    if type(tickets) is not int or not 1 <= tickets <= 7 or type(rank) is not int or not 1 <= rank <= 5:
        raise RuntimeError("史莱姆票数或名次无效")
    return tickets*RANK_REWARDS[rank-1]


def settled_result(text, pending):
    clean = re.sub(r"\s", "", text)
    rank = re.search(r"排名([1-5])", clean)
    tickets = re.search(r"[xX×]([1-7])(?:\D|$)", clean)
    reward = re.search(r"已领奖励([\d,，]+)(?:\D|$)", clean)
    if not (rank and tickets and reward and pending["name"] in clean):
        raise RuntimeError("结算选手、票数、名次或已领奖励无法核对")
    rank, tickets, reward = int(rank[1]), int(tickets[1]), int(reward[1].replace(",", "").replace("，", ""))
    if tickets != pending["tickets"] or reward != expected_reward(tickets, rank):
        raise RuntimeError("史莱姆结算奖励与票数、名次不一致")
    return {"rank": rank, "tickets": tickets, "coins": reward, "name": pending["name"]}


def week_spent(records, username, week):
    receipts = {}
    for row in records:
        if row.get("status") == "settled" and row.get("username") == username and row.get("week") == week:
            if not row.get("attempt") or row.get("coins") != expected_reward(row.get("tickets"), row.get("rank")):
                raise RuntimeError("已有史莱姆结算记录无法核对")
            receipts[row["attempt"]] = row["tickets"]
    return sum(receipts.values())


class SlimeRace(VillageHunt):
    label = "芬恩史莱姆竞速"
    timeout = 1200

    def journal(self, record=None):
        path = Path(__file__).resolve().parents[1] / "debug" / "slime-race-weekly.jsonl"
        if record is None:
            return [json.loads(line) for line in path.read_text("utf-8").splitlines()] if path.exists() else []
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": datetime.now().astimezone().isoformat(),
                                     "week": game_week(), "username": self.username, **record},
                                    ensure_ascii=False)+"\n")
            stream.flush()
            os.fsync(stream.fileno())

    def match(self, name, roi, threshold=.88):
        result = self.context.run_recognition_direct("TemplateMatch", JTemplateMatch(
            template=[name], roi=list(roi), threshold=[threshold]), self.image)
        return bool(result and result.hit)

    def selection(self):
        return bool(self.find(r"^选择应援选手$", (460, 28, 360, 62)))

    def confirmation(self):
        return bool(self.find(r"是否使用应援票券为所选选手应援", (340, 310, 600, 95)))

    def result(self):
        return bool(self.find(r"^我的应援结果$", (640, 86, 400, 65)))

    def phase(self):
        rows = self.ocr(r".+", (495, 12, 290, 50))
        text = "".join(r.text for r in rows)
        if "投注中" in text:
            return "betting"
        if "结果公布" in text:
            return "result"
        if re.search(r"竞速|比赛|进行|出发", text):
            return "racing"
        return None

    def dialogue(self):
        return bool(self.find(r"^芬恩$", (25, 515, 180, 65)))

    def home(self):
        for _ in range(6):
            self.capture()
            if self.selection():
                self.click(1177, 58, .5)
            elif self.result():
                self.click(1161, 119, .5)
            elif self.find(r"是否返回村庄", (470, 320, 340, 85)):
                self.click(640, 470, 2)
            elif self.phase():
                self.click(1219, 42, .8)
            else:
                break
        super().home()

    def tick(self):
        """Keep sparse retained frames for debugging, without overwriting earlier evidence."""
        if self.param.get("trace_dir"):
            self.trace(self.frame_index, None, [])
            self.frame_index += 1

    def open_race(self):
        self.enter()
        self.ensure_street()
        self.leave_spawn()
        for _ in range(40):
            self.capture()
            if self.phase() or self.selection() or self.result():
                return
            if self.dialogue():
                # The dialogue body advances reliably. The corner arrow can
                # dismiss this line without opening its follow-up panel.
                self.click(640, 626, 1.5)
                continue
            choice = self.find(r"^史莱姆竞速$", (630, 235, 590, 260))
            if choice:
                self.click_row(choice, .9)
                continue
            finn = self.find(r"^芬恩$", (0, 180, 1260, 220))
            player = self.player()
            if finn and player:
                dx = finn.box.x+finn.box.w/2-player[0]
                if abs(dx) <= 150:
                    self.click(790, 610, .8)
                else:
                    self.move(dx, 0, min(400, max(80, int(abs(dx)*1.1))))
            elif self.village():
                self.move(-1, 0, 400)
            else:
                self.pause(.5)
        raise RuntimeError("未确认芬恩的史莱姆竞速入口")

    def open_selection(self):
        for _ in range(8):
            self.capture()
            if self.selection() or self.result():
                return
            if self.dialogue():
                self.click(640, 626, 1.1)
            elif self.phase() == "betting":
                self.click(860, 610, .8)
            else:
                return
        raise RuntimeError("与芬恩对话后未确认应援选手面板")

    def tickets(self):
        if not self.selection() or not self.match("local_slime_ticket.png", (1000, 35, 65, 55)):
            raise RuntimeError("未确认史莱姆应援券，不投注")
        value = self.number((1080, 45, 48, 30))
        if not 0 <= value <= 7:
            raise RuntimeError("史莱姆应援券数量超出每周7张范围")
        return value

    def allocations(self):
        values = tuple(self.number((555, y-22, 100, 44)) for y in ROW_Y)
        if any(value < 0 or value > 7 for value in values) or sum(values) > 7:
            raise RuntimeError("选手票数无法确认，不投注")
        return values

    def runner_names(self):
        names = []
        for y in ROW_Y:
            row = self.find(r"\S+", (210, y-23, 180, 46))
            if not row:
                raise RuntimeError("无法确认史莱姆选手名称")
            names.append(row.text.strip())
        if len(set(names)) != 5:
            raise RuntimeError("选手名单识别冲突")
        return names

    def verify_rewards(self):
        if not self.match("local_slime_coin.png", (849, 204, 70, 76)):
            raise RuntimeError("未确认奖励币种为史莱姆币")
        values = tuple(self.number((1135, y-21, 60, 42)) for y in ROW_Y)
        if values != RANK_REWARDS:
            raise RuntimeError("史莱姆排名奖励表发生变化，不投注")

    def submit(self, before):
        self.verify_rewards()
        names = self.runner_names()
        allocations = self.allocations()
        if any(allocations):
            raise RuntimeError("已有选手票数，保留当前选择，不覆盖或重复投注")
        runner = secrets.randbelow(5)
        self.click(777, ROW_Y[runner], .35)
        chosen = self.allocations()
        wanted = tuple(before if i == runner else 0 for i in range(5))
        if chosen != wanted or self.tickets() not in (before, 0):
            raise RuntimeError("最大票数与持有票数不一致，不提交应援")
        self.tick()
        attempt = {"status": "submitted", "attempt": uuid4().hex,
                   "runner": runner+1, "name": names[runner], "names": names,
                   "tickets": before, "before": before, "allocation": list(chosen)}
        self.journal(attempt)
        # Persist the selection before opening the final confirmation, and
        # persist that final click separately before any tickets can be spent.
        self.click(770, 652, 1.5)
        self.tick()
        if self.confirmation():
            self.journal({"status": "confirmation_submitted", "attempt": attempt["attempt"]})
            self.click(770, 484, 1)
            self.tick()
            self.log(f"已确认使用{before}张现有应援券给{names[runner]}；等待本场结算")
        else:
            raise RuntimeError("未确认史莱姆应援二次确认框，不重复提交")
        return attempt

    def read_result(self, pending):
        """Return a verified receipt only after the exact result layout is understood."""
        text = " ".join(r.text for r in self.ocr(r".+", (480, 165, 710, 440)))
        if re.search(r"未给任何人应援|未能获得奖励", text):
            if pending and any(r.get("status") == "confirmation_submitted" and r.get("attempt") == pending.get("attempt") for r in self.journal()):
                raise RuntimeError("存在已提交记录，但本场显示未应援；保留记录，停止新增投注")
            return None
        self.journal({"status": "result_observed", "attempt": pending.get("attempt") if pending else None,
                      "text": text})
        self.tick()
        if not pending:
            return None
        receipt = settled_result(text, pending)
        if not self.match("local_slime_result_coin.png", (1050, 210, 100, 90), .85):
            raise RuntimeError("结算奖励币种无法核对")
        self.journal({"status": "settled", "attempt": pending["attempt"], **receipt})
        claim = self.find(r"^(?:领取|领取奖励)$", (470, 535, 730, 100))
        if claim:
            self.click_row(claim, 1)
            self.journal({"status": "claim_clicked", "attempt": pending.get("attempt") if pending else None})
            self.tick()
        if self.result():
            self.click(1161, 119, .6)
        self.log(f"{receipt['name']}第{receipt['rank']}名，{receipt['tickets']}张票已领取{receipt['coins']}史莱姆币；关闭结果")
        return receipt

    def wait_and_play(self, pending):
        def confirmed_intent(row):
            return bool(row and row.get("attempt") and any(r.get("attempt") == row["attempt"] and r.get("status") == "confirmation_submitted"
                                    for r in self.journal()))
        last_log, submitted = 0, confirmed_intent(pending)
        while True:
            self.capture()
            if self.result():
                receipt = self.read_result(pending)
                if receipt:
                    return True
                self.click(1161, 119, .7)
            elif self.selection():
                count = self.tickets()
                if pending:
                    if (pending.get("names") and not confirmed_intent(pending) and count == pending["before"]
                            and not any(self.allocations()) and self.runner_names() != pending["names"]):
                        self.journal({"status": "not_submitted", "attempt": pending["attempt"],
                                      "reason": "new race, unchanged tickets, final confirmation never sent"})
                        self.log("上次只选择了票数，未最终确认；票券保留，改在本场应援")
                        pending = self.submit(count)
                        submitted = True
                        continue
                    if count == pending["before"]-pending["tickets"]:
                        self.log("应援券已扣除，继续等待本次结算，不重复提交")
                    else:
                        raise RuntimeError("上次应援结果尚未确认，停止新增投注")
                    self.click(1177, 58, .5)
                elif count == 0:
                    self.log("现有史莱姆应援券为0，正常跳过")
                    self.click(1177, 58, .5)
                    return True
                elif self.param.get("inspect_only"):
                    self.verify_rewards()
                    self.tick()
                    self.log("已打开应援面板，仅检查，不提交")
                    return True
                else:
                    pending = self.submit(count)
                    submitted = True
            elif self.dialogue():
                self.click(640, 626, 1)
            elif self.phase() == "betting" and not submitted:
                self.open_selection()
                continue
            if time.monotonic()-last_log > 60:
                self.log("等待史莱姆比赛阶段切换" + ("；本次已提交，不再下注" if submitted else ""))
                self.tick()
                last_log = time.monotonic()
            self.pause(5)

    def execute(self):
        self.frame_index = 0
        records = self.journal()
        if self.confirmation():
            submitted = [r for r in records if r.get("status") == "submitted"]
            if not submitted:
                raise RuntimeError("未找到当前应援确认框的原始记录")
            old = submitted[-1]
            self.username = old["username"]
            if any(r.get("attempt") == old["attempt"] and r.get("status") == "confirmation_submitted" for r in records):
                raise RuntimeError("上次已经确认过应援，不再次确认")
            # Earlier builds stopped before this final confirmation. Cancel that
            # uncommitted selection, verify all tickets remain, then wait for a
            # fresh betting window instead of submitting an expired race.
            self.click(509, 484, .6)
            if self.tickets() != old["before"]:
                raise RuntimeError("取消未确认的应援后票数变化，停止核对")
            self.journal({"status": "not_submitted", "attempt": old["attempt"],
                          "reason": "final confirmation was never sent", "tickets": old["before"]})
        if self.selection() or self.result():
            self.click(1177 if self.selection() else 1161, 58 if self.selection() else 119, .5)
        in_arena = bool(self.phase())
        if not in_arena:
            self.home()
        name = self.find(r"\S+", (500, 130, 250, 45) if in_arena else (120, 45, 180, 50))
        if not name:
            raise RuntimeError("未确认当前角色名称")
        self.username = name.text.strip()
        records = self.journal()
        pending = pending_race(records, self.username, game_week())
        if not pending and week_spent(records, self.username, game_week()) >= 7:
            self.log("本周7张应援券已经结算，正常跳过")
            if in_arena:
                self.home()
            return True
        if not in_arena:
            self.open_race()
        finished = self.wait_and_play(pending)
        if not self.param.get("inspect_only"):
            self.home()
        return finished


ACTIONS = {"LocalSlimeRace": SlimeRace()}
