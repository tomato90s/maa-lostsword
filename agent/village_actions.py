"""Halloween town patrol using the same joystick area as the user's WASD map."""
import json
import math
import re
import struct
import time
import zlib
from datetime import datetime
from difflib import SequenceMatcher
from pathlib import Path
from uuid import uuid4

from maa.pipeline import JTemplateMatch
from agent.seasonal_actions import SeasonalScreen


def verified_reward(before, after, candies):
    # Each defeated target drops one 奇怪的糖果; using it grants 30 diamonds.
    gain = after - before
    if gain != candies*30:
        raise RuntimeError("糖果使用后钻石变化与每颗30钻不一致，停止核对")
    return gain


class LobbyBounce(RuntimeError):
    """The game moved the character back to the lobby during the patrol."""


# Template sets per village target. The Halloween woman drops 奇怪的糖果 that is
# redeemed for diamonds; the regular chicken only drops chicken meat that stays
# in the bag, so its patrol ends without touching the bag.
TARGETS = {
    "hood": {"label": "万圣节女人", "redeem": True,
             "templates": ["local_village_hood.png","local_village_hood_right.png","local_village_hood_front.png",
                           "local_village_hood_back.png","local_village_hood_side.png"]},
    "chicken": {"label": "鸡", "redeem": False, "templates": []},
}
ROOT = Path(__file__).resolve().parents[1]
# The release keeps images in resource/image; the source tree in assets/resource/image.
IMAGE_DIRS = (ROOT / "resource" / "image", ROOT / "assets" / "resource" / "image")


def chicken_templates(directories=IMAGE_DIRS):
    """Chicken templates are captured once the event ends: local_village_chicken*.png."""
    for directory in directories:
        names = sorted(path.name for path in Path(directory).glob("local_village_chicken*.png"))
        if names:
            return names
    return []


class VillageHunt(SeasonalScreen):
    label = "万圣节村庄目标"
    timeout = 1200

    def trace(self, step, player, targets):
        directory = self.param.get("trace_dir")
        if not directory: return
        root = Path(directory)
        if not root.is_absolute(): raise RuntimeError("诊断目录须为绝对路径")
        root.mkdir(parents=True,exist_ok=True)
        path = root / f"{step:03d}.png"
        if path.exists(): raise RuntimeError("诊断截图已存在，不覆盖")
        height,width = self.image.shape[:2]
        raw = b"".join(b"\0"+row.tobytes() for row in self.image[:,:,:3][:,:,::-1])
        def chunk(kind,data): return struct.pack(">I",len(data))+kind+data+struct.pack(">I",zlib.crc32(kind+data))
        path.write_bytes(b"\x89PNG\r\n\x1a\n"+chunk(b"IHDR",struct.pack(">IIBBBBB",width,height,8,2,0,0,0))+chunk(b"IDAT",zlib.compress(raw))+chunk(b"IEND",b""))
        (root / f"{step:03d}.json").write_text(json.dumps({"player":player,"targets":targets,"portal":self.portal()},ensure_ascii=False),encoding="utf-8")

    def journal(self, record=None):
        path = Path(__file__).resolve().parents[1] / "debug" / f"village-hunt-{datetime.now():%Y-%m-%d}.jsonl"
        if record is None:
            return [json.loads(line) for line in path.read_text("utf-8").splitlines()] if path.exists() else []
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time":datetime.now().astimezone().isoformat(), **record},ensure_ascii=False)+"\n")

    def village(self):
        return bool(self.node("LocalVillageOpenMenu"))

    def guard(self):
        # Skill flashes briefly wash out the village HUD; only stop when the
        # village controls stay missing across several fresh screenshots.
        if self.village():
            return
        for _ in range(6):
            self.pause(.5)
            self.capture()
            if self.village():
                return
        if self.node("HomeFlagCloseReturnMain"):
            raise LobbyBounce("村庄巡查中被送回大厅")
        raise RuntimeError("村庄攻击界面已改变，停止移动和攻击")

    def open_menu(self):
        """Open the lobby menu and wait for its slide-in animation to settle."""
        clicks, retry_after = 0, 0
        until = time.monotonic()+10
        while time.monotonic() < until:
            if self.find(r"游戏专属编号", (850,55,350,50)):
                return
            if (self.node("HomeFlagCloseReturnMain") and clicks < 2
                    and time.monotonic() >= retry_after):
                self.click(1236,36,.6)
                clicks += 1
                retry_after = time.monotonic()+2
                continue
            self.pause(.3)
            self.capture()
        raise RuntimeError("未确认大厅菜单")

    def wallet(self):
        self.home()
        name = self.find(r"\S+", (120, 45, 180, 50))
        if not name:
            raise RuntimeError("未确认当前角色名称")
        self.username = name.text.strip()
        self.open_menu()
        diamonds = self.number((850,655,105,42))
        self.click(1236,36,1.0)
        return diamonds

    def redeem(self):
        """Use every 奇怪的糖果 in the bag and verify the 30-diamond payout."""
        self._redemption_id = None
        before = self.wallet()
        self.open_menu()
        self.click(910,195,1.5)
        if not self.find(r"^背包$", (130,5,80,45)):
            raise RuntimeError("未确认背包界面")
        box = self.find_candy()
        if box is None:
            self.log("背包内没有奇怪的糖果")
            self.click(1233,38,.8)
            return before, before, 0
        x,y,w,h = (box.x,box.y,box.w,box.h) if hasattr(box,"x") else box
        self.click(x+w/2,y+h/2,.8)
        if not self.find(r"奇怪的糖果", (750,75,250,45)):
            raise RuntimeError("选中的道具不是奇怪的糖果")
        counts = [re.fullmatch(r"\[?(\d+)\]?", re.sub(r"[\s,，]","",row.text)) for row in self.ocr(r".+",(760,120,90,35))]
        counts = [int(match.group(1)) for match in counts if match]
        if len(counts) != 1:
            raise RuntimeError("无法确认糖果持有数量")
        owned = counts[0]
        if not self.find(r"^使用$", (1040,650,90,35)):
            raise RuntimeError("未找到糖果使用按钮")
        if owned > 1:
            # The quantity selector only exists when more than one candy is held.
            self.click(1180,588,.5)  # Select the maximum quantity.
            # The wide dark selector makes OCR detect only the first digit
            # (21 was read as 2). Read the centered value without its borders.
            selected = self.ocr(r".+", (940,528,95,35), only_rec=True)
            values = [re.fullmatch(r"\d+", row.text.strip()) for row in selected]
            chosen = int(values[0][0]) if len(values) == 1 and values[0] else None
            if chosen != owned:
                raise RuntimeError("糖果使用数量与持有数量不一致")
        self.click(1085,666,1.5)
        if not self.find(r"已获得道具", (500,260,280,60)):
            raise RuntimeError("未确认糖果使用结果")
        self._redemption_id = uuid4().hex
        self.journal({"status":"redemption_reward","redemption":self._redemption_id,
                      "attempt":getattr(self,"attempt",None),"username":self.username,
                      "before":before,"candies":owned})
        self.click(640,640,1)
        self.click(1233,38,.8)
        after = self.wallet()
        return before, after, owned

    def find_candy(self):
        """Scan the bag page by page; viewed candies lose the "new" badge and
        move from the first row to their sorted slot further down."""
        for _ in range(40):
            result = self.context.run_recognition_direct("TemplateMatch", JTemplateMatch(
                template=["local_village_candy.png"], threshold=[.8], roi=[190,130,500,520]), self.image)
            if result and result.hit:
                return result.best_result.box
            grid = self.image[140:640,200:680].astype("int16")
            self.swipe(440,600,440,160)
            if not self.find(r"^背包$", (130,5,80,45)):
                raise RuntimeError("翻找糖果时离开了背包界面")
            if abs(self.image[140:640,200:680].astype("int16")-grid).mean() < 3:
                return None  # The grid stopped moving: bottom of the bag.
        raise RuntimeError("背包翻页次数过多，未确认是否有糖果")

    def enter(self):
        entry = self.find(r"前往.*村庄", (1050,140,190,90))
        if not entry or not self.node("HomeFlagCloseReturnMain"):
            raise RuntimeError("未确认大厅村庄入口")
        self.click_row(entry,3)
        for _ in range(18):
            self.capture()
            if self.village():
                # The HUD flashes in before the arrival finishes; moving then
                # leaves the character on the spawn circle, which teleports back.
                self.pause(2.5)
                self.capture()
                if self.village():
                    return
            self.pause(.5)
        raise RuntimeError("进入村庄后未确认攻击界面")

    def leave_spawn(self):
        """Walk well below the lobby circle in front of the INN door."""
        player = self.player()
        if player and player[1] >= self.SAFE_Y+20:
            # Village entry keeps the last location. Repeatedly moving down
            # on every visit eventually pushes the character against the HUD.
            if player[1] > self.SAFE_Y+80:
                self.move(0,-1,min(300,max(80,int((player[1]-(self.SAFE_Y+40))/.65))))
            return
        for _ in range(4):
            self.move(0,1,400)
            player = self.player()
            if player and player[1] >= self.SAFE_Y+20:
                return
        self.log("未确认已离开出生光圈，继续巡查时保持在下方")

    # Feet at or above this screen height are on the INN-door lobby circle row.
    SAFE_Y = 560

    def player(self):
        # OCR occasionally drops letters from the name tag (Ronot256 -> Mot256).
        rows = [row for row in self.ocr(r".+", (250,150,650,400))
                if SequenceMatcher(None, row.text.strip(), self.username).ratio() >= .7]
        if not rows:
            return None
        row = max(rows, key=lambda r: SequenceMatcher(None, r.text.strip(), self.username).ratio())
        return row.box.x+row.box.w/2, row.box.y+255

    def targets(self, player):
        result = self.context.run_recognition_direct("TemplateMatch", JTemplateMatch(
            template=self.templates, threshold=[.7], roi=[0,230,1240,350]), self.image)
        points = []
        for hit in (result.filtered_results if result and result.hit else []):
            box = hit.box
            x,y,w,h = (box.x,box.y,box.w,box.h) if hasattr(box,"x") else box
            point = (x+w/2, y+238)
            if math.hypot(point[0]-player[0], point[1]-(player[1]+15)) < 50:
                # Exclude an accidental match on the controlled character's head.
                continue
            if not any(math.hypot(point[0]-p[0],point[1]-p[1]) < 60 for p in points):
                points.append(point)
        return points

    def move(self, dx, dy, duration=180):
        self.guard()
        player, portal = self.player(), self.portal()
        size = max(abs(dx),abs(dy),1)
        if (player and portal and dy < 0 and abs(player[0]-portal[0]) < 260
                and player[1]+dy/size*duration*.65 < self.SAFE_Y):
            # The lobby circle sits on the upper row; never climb onto that row beside it.
            dy = 0
            if not dx:
                return
        if player and portal:
            size = max(abs(dx),abs(dy),1)
            predicted = (player[0]+dx/size*duration*.65, player[1]+dy/size*duration*.65)
            if (abs(predicted[0]-portal[0])<170 and abs(predicted[1]-portal[1])<110
                    and not (dy>0 and player[1]>=portal[1])):
                dx,dy = (1 if player[0]>=portal[0] else -1),1
                self.log("绕开大厅入口后再靠近目标")
        size = max(abs(dx),abs(dy),1)
        end = (158+int(75*dx/size), 540+int(75*dy/size))
        controller = self.context.tasker.controller
        if not controller.post_swipe(158,540,*end,int(duration)).wait().succeeded:
            raise RuntimeError("村庄摇杆移动失败")
        self.pause(.2)
        self.capture()

    def portal(self):
        result = self.context.run_recognition_direct("TemplateMatch", JTemplateMatch(
            template=["local_village_in.png"],threshold=[.8],roi=[0,150,1240,400]),self.image)
        if not result or not result.hit: return None
        box = result.best_result.box
        x,y,w,h = (box.x,box.y,box.w,box.h) if hasattr(box,"x") else box
        return x+w/2-130,y+h/2+160

    def strike(self, use_skill=False):
        self.guard()
        self.click(1086,563,1.0)
        if use_skill:
            player,portal = self.player(),self.portal()
            if player and portal and math.hypot(player[0]-portal[0],player[1]-portal[1])<220:
                return
            self.guard()
            self.click(952,472,.8)
            self.guard()
            self.click(1060,400,1.2)

    def execute(self):
        self.attempt = None
        kind = self.param.get("target","hood")
        if kind not in TARGETS:
            raise RuntimeError("村庄目标类型须为万圣节女人或鸡")
        self.kind = kind
        self.templates = TARGETS[kind]["templates"] or chicken_templates()
        if not self.templates:
            raise RuntimeError("还没有鸡的识别图片，暂时不能打鸡")
        if not TARGETS[kind]["redeem"]:
            return self.hunt_only()
        limit = int(self.param.get("limit",12))
        steps = int(self.param.get("steps",96))
        if not 0 <= limit <= 12 or not 1 <= steps <= 96:
            raise RuntimeError("村庄目标上限须为0至12，巡查步数须为1至96")
        wanted = limit*30
        previous = self.journal()
        total = sum(item.get("gain",0) for item in previous if item.get("status") in ("partial","complete"))
        if not wanted or total >= wanted:
            self.log(f"本日已核对{total}钻奖励，达到本轮上限，跳过")
            return True
        # Old candy can remain in the bag across days. Redeem it separately so
        # a stored stack never counts as today's twelve defeated targets.
        pending = next((item for item in reversed(previous)
                        if item.get("status") == "started" and item.get("inventory_empty")
                        and item.get("attempt") and not any(
                            row.get("attempt") == item["attempt"]
                            and row.get("status") in ("partial", "complete") for row in previous)), None)
        if pending:
            balance = self.wallet()
            if pending.get("username") != self.username:
                raise RuntimeError("待结算巡查属于其他角色，停止领取")
            self.attempt = pending["attempt"]
            reward = next((row for row in reversed(previous)
                           if row.get("status") == "redemption_reward" and row.get("attempt") == self.attempt
                           and not any(done.get("redemption") == row.get("redemption")
                                       and done.get("status") in ("partial","complete") for done in previous)), None)
            if reward:
                gain = verified_reward(reward["before"],balance,reward["candies"])
                total += gain
                self.journal({"status":"complete" if total>=wanted else "partial", "attempt":self.attempt,
                              "redemption":reward["redemption"],"username":self.username,
                              "before":reward["before"],"after":balance,"candies":reward["candies"],
                              "gain":gain,"confirmed_today":total,"recovered":True})
                self.log(f"已恢复上次糖果到账确认：{gain}钻，本日共{total}钻")
            else:
                self.collect_patrol_reward(0,0,total,wanted)
            previous = self.journal()
            total = sum(item.get("gain",0) for item in previous if item.get("status") in ("partial","complete"))
            if total >= wanted:
                return True
        before, after, stored = self.redeem()
        stored_gain = verified_reward(before, after, stored)
        if stored:
            self.journal({"status":"inventory_redeemed", "before":before, "after":after,
                          "candies":stored, "gain":stored_gain})
            self.log(f"已领取背包原有糖果{stored}颗、{stored_gain}钻，另行核对本次巡查")
        self.home()
        name = self.find(r"\S+", (120, 45, 180, 50))
        if not name:
            raise RuntimeError("未确认当前角色名称")
        self.username = name.text.strip()
        self.attempt = uuid4().hex
        last_start = next((item for item in reversed(previous) if item.get("status") == "started"), None)
        self.patrol_direction = -last_start.get("direction",1) if last_start else 1
        self.journal({"status":"started","attempt":self.attempt,"username":self.username,
                      "confirmed_today":total,"inventory_empty":True,"steps":steps,"direction":self.patrol_direction})
        attacks, sighted = self.patrol(steps)
        if not self.node("HomeFlagCloseReturnMain"):
            self.home()
        return self.collect_patrol_reward(attacks, sighted, total, wanted)

    def collect_patrol_reward(self, attacks, sighted, total, wanted):
        before, after, candies = self.redeem()
        gain = verified_reward(before,after,candies)
        total += gain
        self.journal({"status":"complete" if total>=wanted else "partial", "before":before,"after":after,
                      "attempt":getattr(self,"attempt",None),"username":getattr(self,"username",None),
                      "redemption":getattr(self,"_redemption_id",None),
                      "candies":candies,"gain":gain,"confirmed_today":total,"attacks":attacks,"sighted":sighted})
        self.log(f"使用糖果{candies}颗，钻石{before}->{after}，实收{gain}钻；本日已核对{total}钻")
        if candies == 0 and not sighted:
            self.log("本次没有发现新目标，按实际到账奖励保留进度")
        if total < wanted:
            self.log("尚未核对全部目标奖励，保留未完成状态")
            return False
        return True

    def hunt_only(self):
        """Chicken patrol: attack what is found and leave the meat in the bag."""
        steps = int(self.param.get("steps",96))
        if not 1 <= steps <= 96:
            raise RuntimeError("巡查步数须为1至96")
        self.home()
        name = self.find(r"\S+", (120, 45, 180, 50))
        if not name:
            raise RuntimeError("未确认当前角色名称")
        self.username = name.text.strip()
        attacks, sighted = self.patrol(steps)
        if not self.node("HomeFlagCloseReturnMain"):
            self.home()
        self.log(f"打鸡结束：发现目标{sighted}次，攻击{attacks}轮，鸡肉留在背包")
        return True

    def patrol(self, steps):
        label = TARGETS[self.kind]["label"]
        self.enter()
        self.leave_spawn()
        attacks, misses, direction, sighted, bounces = 0,0,getattr(self,"patrol_direction",1),0,0
        self._last_patrol_view = None
        self._last_patrol_player = None
        self._still_patrol_frames = 0
        for step in range(steps):
            if time.monotonic() + 120 >= self.deadline:
                self.log("预留回大厅和领取糖果的时间，结束本次巡查")
                break
            try:
                self.capture()
                self.guard()
                misses, attacks, direction, sighted, stop = self.patrol_step(step, misses, attacks, direction, sighted)
            except LobbyBounce:
                bounces += 1
                if bounces > 3:
                    self.log("连续多次被送回大厅，停止巡查")
                    break
                self.log(f"被送回大厅，第{bounces}次重新进入村庄")
                self.enter()
                self.leave_spawn()
                continue
            if stop:
                break
            if (step+1)%12==0:
                self.log(f"已巡查{step+1}步，攻击{attacks}轮")
        if not sighted:
            self.log(f"本次巡查没有发现{label}")
        return attacks, sighted

    def patrol_step(self, step, misses, attacks, direction, sighted):
        """One patrol step; returns updated counters and whether to stop."""
        if True:
            if self.find(r"克拉拉", (150,180,200,40)):
                # A shop door leads into the maid cafe; stop instead of wandering inside.
                self.log("误入咖啡店，停止巡查并回大厅结算")
                return misses, attacks, direction, sighted, True
            player = self.player()
            if not player:
                self.trace(step, None, [])
                misses += 1
                self.pause(.3)
                return misses, attacks, direction, sighted, misses >= 5
            targets = self.targets(player)
            self.trace(step, player, targets)
            if targets:
                misses, sighted = 0, sighted+1
                target = min(targets,key=lambda p:abs(p[0]-player[0])+2*abs(p[1]-player[1]))
                dx,dy = target[0]-player[0],target[1]-player[1]
                self.log(f"巡查{step+1}：人物({player[0]:.0f},{player[1]:.0f})，目标({target[0]:.0f},{target[1]:.0f})")
                if abs(dy)>60 or abs(dx)>170:
                    self.move(dx,dy,min(250,max(80,int(max(abs(dx),abs(dy))*1.2))))
                    if abs(dx) <= 330 and abs(dy) <= 150:
                        # A turning target can disappear from the template
                        # immediately after approach. Attack while still close
                        # instead of walking away on the next missing frame.
                        self.strike(use_skill=attacks%3==0)
                        attacks += 1
                else:
                    self.move(1 if dx>=0 else -1,0,65)
                    self.strike(use_skill=attacks%3==0)
                    attacks += 1
            else:
                misses += 1
                image = getattr(self, "image", None)
                if image is not None:
                    view = image[200:400:8,300:1000:8].copy()
                    previous = getattr(self, "_last_patrol_view", None)
                    position = getattr(self, "_last_patrol_player", None)
                    stalled = False
                    if previous is not None and position is not None:
                        difference = abs(view.astype("int16") - previous.astype("int16"))
                        stalled = (float(difference.mean()) < 2
                                   and float((difference < 5).mean()) > .95
                                   and math.hypot(player[0]-position[0],player[1]-position[1]) < 20)
                    self._still_patrol_frames = getattr(self,"_still_patrol_frames",0) + 1 if stalled else 0
                    if self._still_patrol_frames >= 2:
                        direction = -direction
                        self._still_patrol_frames = 0
                        self.log("人物与背景连续未移动，换向继续巡查")
                    self._last_patrol_view, self._last_patrol_player = view, player
                portal = self.portal()
                if portal and abs(player[0]-portal[0])<190 and player[1]>portal[1]+90:
                    self.move(direction,0,400)
                else:
                    if player[0]>1000: direction=-1
                    if player[0]<300: direction=1
                    self.move(direction,0,400)
                if misses%2==0:
                    self.strike(use_skill=misses%6==0)
                    attacks += 1
                # Keep walking to the village edge. Turning after ten misses
                # returned to the same streets, then stopped before the user's
                # selected patrol budget could cover the rest of the village.
            return misses, attacks, direction, sighted, False


ACTIONS = {"LocalVillageHunt":VillageHunt()}
