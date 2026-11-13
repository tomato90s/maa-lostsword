"""Purchase bounded exchange batches with an item and currency receipt."""
import json
import re
import time
from collections import defaultdict
from datetime import datetime
from pathlib import Path

from maa.pipeline import JTemplateMatch
from agent.daily_actions import ScreenAction


CURRENCY_IMAGES = {
    "金币": "template_1780926976910.png",
    "信物": "shop_xinwu.png",
    "突袭币": "local_shop_raid.png",
    "南瓜币": "local_shop_pumpkin.png",
    "公会币": "shop_gonghuibi.png",
    "竞技场币": "shop_jingjichangbi.png",
    "钻石": "piliang_zuanshi.png",
}
PRODUCTS = {
    "消耗品": {
        "金币": ("褪色的宝石箱", "领主召唤券：巨石阵", "黄金指南针：巨石阵", "4种强化秘典宝箱", "初级经验书", "稀有灵魂"),
        "信物": ("金币券", "紫色门票"),
    },
    "突袭": {"突袭币": ("梅林的特制药水", "银河精髓", "领主召唤券：巨石阵", "精灵王的信物", "初级经验书")},
    "公会": {"公会币": ("褪色的宝石箱", "经验值宝箱", "金币宝箱")},
    "竞技场": {"竞技场币": ("竞技场补给箱",)},
    "南瓜币": {"金币": ("南瓜票券",), "南瓜币": ("轮盘券", "Boss Raid Ticket")},
}


def amount(text):
    text = re.sub(r"\s", "", text)
    if re.fullmatch(r"\d+", text):
        return int(text)
    if re.fullmatch(r"\d{1,3}(?:[,，.]\d{3})+", text):
        return int(re.sub(r"[,，.]", "", text))
    return None


def quantity(text):
    match = re.fullmatch(r"\s*(\d+)\s*[/／]\s*(\d+)\s*", text)
    if not match:
        return None
    value, maximum = map(int, match.groups())
    return (value, maximum) if 0 <= value <= maximum <= 10000 else None


def product_allowed(category, name, currency):
    clean = lambda value: re.sub(r"\s", "", value).replace(":", "：")
    return clean(name) in {clean(item) for item in PRODUCTS.get(category, {}).get(currency, ())}


def totals(items):
    result = defaultdict(int)
    for item in items:
        if item["selected"] and item["quantity"]:
            if item["currency"] in ("钻石", "unknown") or item["price"] is None:
                raise RuntimeError("勾选商品存在钻石或无法识别的价格，不购买")
            result[item["currency"]] += item["price"]
    return dict(result)


class ShopBatch(ScreenAction):
    label = "交易所批量购买"
    timeout = 600

    def log(self, message):
        super().log(message)
        path = Path(__file__).resolve().parents[1] / "debug" / f"local-shop-{datetime.now():%Y-%m-%d}.jsonl"
        path.parent.mkdir(parents=True, exist_ok=True)
        with path.open("a", encoding="utf-8") as stream:
            stream.write(json.dumps({"time": datetime.now().astimezone().isoformat(),
                                     "category": self.param.get("category"), "message": message}, ensure_ascii=False) + "\n")

    def template(self, name, roi, threshold=.8):
        result = self.context.run_recognition_direct("TemplateMatch", JTemplateMatch(
            template=[name], roi=list(roi), threshold=[threshold]), self.image)
        return result if result and result.hit else None

    def popup(self):
        return self.find(r"^批量购买$", (530, 60, 220, 55)) and self.find(r"总购买金额", (670, 535, 170, 45))

    def open_batch(self):
        until = time.monotonic() + 10
        clicks, retry_after = 0, 0
        while time.monotonic() < until:
            self.capture()
            if self.popup():
                return
            button = self.find(r"^批量购买$", (95, 640, 185, 65))
            shop = self.find(r"^商店$", (45, 10, 120, 55))
            if button and shop and clicks < 2 and time.monotonic() >= retry_after:
                self.click_row(button, .5)
                clicks += 1
                retry_after = time.monotonic() + 2
            else:
                self.pause(.3)
        raise RuntimeError("未确认批量购买窗口已经打开，本次没有提交购买")

    def scroll(self, top=False):
        self.check()
        if not self.popup():
            raise RuntimeError("批量窗口已关闭，停止滚动")
        start, end = ((180, 480) if top else (475, 175))
        if not self.context.tasker.controller.post_swipe(500, start, 500, end, 1100).wait().succeeded:
            raise RuntimeError("商店翻页失败")
        self.pause(1.2)
        self.capture()

    def number(self, roi, parser=amount):
        for only_rec in (True, False):
            rows = self.ocr(r".+", roi, only_rec=only_rec)
            values = [parser(row.text) for row in rows]
            if len(values) == 1 and values[0] is not None:
                return values[0]
        raise RuntimeError(f"无法确认商店数量或价格（区域{roi}，读到{[row.text for row in rows]}）")

    def rows(self):
        if not self.popup():
            raise RuntimeError("未确认交易所批量购买窗口")
        result = []
        for row in sorted(self.ocr(r".+", (250, 141, 320, 380)), key=lambda row: row.box.y):
            y = row.box.y + row.box.h // 2
            if not 160 <= y <= 500:
                continue
            count = self.number((870, y - 18, 140, 37), quantity)
            selected = bool(self.template("local_shop_checked.png", (129, y - 24, 47, 48)))
            unchecked = bool(self.template("shop_exchange_unchecked.png", (129, y - 24, 47, 48), .85))
            if selected == unchecked:
                raise RuntimeError("商品勾选状态不明确：" + row.text)
            matched = [name for name, image in CURRENCY_IMAGES.items()
                       if self.template(image, (568, y - 24, 40, 48))]
            currency = matched[0] if len(matched) == 1 else "unknown"
            price = self.number((605, y - 20, 118, 42))
            result.append({"name": row.text, "currency": currency, "selected": selected,
                           "quantity": count[0], "maximum": count[1], "price": price, "y": y})
        if not result:
            raise RuntimeError("批量窗口没有读到完整商品行")
        return result

    def walk(self, configure=False):
        for _ in range(4):
            self.scroll(top=True)
        inventory, previous, stable = {}, None, 0
        for page in range(18):
            rows = self.rows()
            if configure:
                for item in rows:
                    allowed = product_allowed(self.category, item["name"], item["currency"])
                    if not allowed and item["selected"]:
                        self.click(151, item["y"], .6)
                    elif allowed and item["maximum"] > 0:
                        if not item["selected"]:
                            self.click(151, item["y"], .6)
                        if item["quantity"] != item["maximum"]:
                            self.click(1120, item["y"], .6)
                rows = self.rows()
                for item in rows:
                    allowed = product_allowed(self.category, item["name"], item["currency"])
                    if item["selected"] and not allowed:
                        raise RuntimeError("未能取消不在购买清单中的商品")
                    if allowed and item["maximum"] and (not item["selected"] or item["quantity"] != item["maximum"]):
                        raise RuntimeError("商品勾选或最大可购买数量未确认")
            signature = tuple((item["name"], item["currency"], item["y"]) for item in rows)
            stable = stable + 1 if signature == previous else 0
            previous = signature
            for item in rows:
                key = (item["name"], item["currency"])
                inventory[key] = item
            if stable >= 2:
                self.log("商品列表：" + json.dumps(list(inventory.values()), ensure_ascii=False))
                return list(inventory.values())
            self.scroll()
        raise RuntimeError("未确认批量商品列表底部，不购买")

    def summary(self):
        icons = []
        summary_images = {**CURRENCY_IMAGES, "金币": "local_shop_total_gold.png", "信物": "local_shop_total_token.png", "突袭币": "local_shop_total_raid.png", "公会币": "local_shop_total_guild.png", "竞技场币": "local_shop_total_arena.png", "南瓜币": "local_shop_total_pumpkin.png"}
        for currency, image in summary_images.items():
            hit = self.template(image, (785, 538, 375, 45), .85)
            if hit:
                box = hit.best_result.box
                icons.append((box.x if hasattr(box, "x") else box[0], currency))
        values, start = {}, 790
        for x, currency in sorted(icons):
            value = self.number((start, 541, max(1, x - start), 36))
            values[currency] = value
            start = x + 30
        if values.get("钻石", 0):
            raise RuntimeError("结算包含钻石，不购买")
        return {name: value for name, value in values.items() if value}

    def wallet(self):
        if self.popup():
            self.click(1143, 85)
        if self.find(r"^商店$", (45, 10, 120, 55)):
            self.click(1236, 36, .8)
        result = self.context.run_task("ReturnMain", {
            "HomeFlagCloseReturnMain": {"next": []}, "LocalCrashRecovery": {"enabled": False}})
        if not result or not result.status.succeeded:
            raise RuntimeError("未能返回大厅核对余额")
        if not self.wait_for(lambda: self.node("HomeFlagCloseReturnMain"), stable=2):
            raise RuntimeError("大厅未稳定，无法核对余额")
        menu = lambda: self.find(r"游戏专属编号", (850, 55, 350, 50))
        for _ in range(2):
            if menu():
                break
            if not self.node("HomeFlagCloseReturnMain"):
                raise RuntimeError("未确认大厅，不打开余额菜单")
            self.click(1236, 36, .8)
            if self.wait_for(menu, stable=2):
                break
        if not menu():
            raise RuntimeError("未确认大厅菜单余额栏")
        return {"金币": self.number((1025, 655, 145, 42)),
                "钻石": self.number((850, 655, 105, 42))}

    def open_category(self):
        shop = self.find(r"^商店$", (755, 180, 100, 100))
        if not shop:
            raise RuntimeError("未找到大厅菜单中的商店")
        self.click_row(shop, .8)
        exchange = self.find(r"^交易所$", (600, 70, 140, 60))
        if not exchange:
            raise RuntimeError("未找到交易所")
        self.click_row(exchange, .8)
        category = self.find("^" + re.escape(self.category) + "$", (90, 140, 180, 510))
        if not category:
            raise RuntimeError("未找到交易所分类：" + self.category)
        self.click_row(category, .8)

    def category_balance(self):
        roi = (825, 12, 110, 44) if self.category == "消耗品" else ((980, 12, 90, 44) if self.category == "南瓜币" else (1110, 12, 95, 44))
        rows = self.ocr(r".+", roi)
        values = [amount(row.text) for row in rows]
        if len(values) == 1 and values[0] is not None:
            return values[0]
        if not any(re.fullmatch(r"\s*\d+(?:\.\d+)?[万亿]\+?\s*", row.text) for row in rows):
            return self.number(roi)
        # The top bar abbreviates large balances. The currency icon opens an
        # item description showing the exact owned amount, including commas.
        self.click(roi[0] - 20, 34, .8)
        keyword = {"消耗品": "信物", "南瓜币": "南瓜", "突袭": "突袭",
                   "公会": "公会", "竞技场": "竞技"}[self.category]
        if (not self.find(keyword, (480, 180, 350, 70))
                or not self.find(r"^说明$", (470, 245, 130, 55))):
            raise RuntimeError("未确认分类代币详情，不按缩写估算余额")
        exact = self.number((825, 195, 95, 45))
        close = self.find(r"^确认$", (540, 550, 210, 90))
        if not close:
            raise RuntimeError("代币详情没有确认按钮")
        self.click_row(close, .8)
        return exact

    def ledger(self, record=None):
        path = Path(__file__).resolve().parents[1] / "debug" / f"shop-purchases-{datetime.now():%Y-%m-%d}.jsonl"
        if record is not None:
            path.parent.mkdir(parents=True, exist_ok=True)
            with path.open("a", encoding="utf-8") as stream:
                stream.write(json.dumps({"time": datetime.now().astimezone().isoformat(),
                    "category": self.category, **record}, ensure_ascii=False) + "\n")
            return
        records = [json.loads(line) for line in path.read_text("utf-8").splitlines()] if path.exists() else []
        return next((item for item in reversed(records) if item["category"] == self.category), None)

    def reconcile_unapplied(self):
        previous = self.ledger()
        if not previous or previous["status"] != "unknown":
            raise RuntimeError("没有待核对的购买提交")
        if self.popup():
            self.click(1143, 85)
        observed_tokens = self.category_balance()
        observed = self.wallet()
        expected = previous["before"]
        if (observed != {key: expected[key] for key in ("金币", "钻石")}
                or observed_tokens != expected["分类代币"]):
            raise RuntimeError("此前提交后余额发生变化，保留未知状态，不重新购买")
        self.open_category()
        button = self.find(r"^批量购买$", (95, 640, 185, 65))
        if not button:
            raise RuntimeError("未能重新核对商品剩余上限")
        self.open_batch()
        items = self.walk(configure=False)
        fields = ("name", "currency", "quantity", "maximum", "price")
        signature = lambda rows: sorted(tuple(item[key] for key in fields) for item in rows if item["selected"] and item["quantity"])
        if (signature(items) != signature(previous["items"])
                or totals(items) != previous["cost"] or self.summary() != previous["cost"]):
            raise RuntimeError("商品剩余数量或总价已变化，保留未知状态，不重新购买")
        self.ledger({**{key: value for key, value in previous.items() if key not in ("time", "category")},
                     "status": "not_applied", "attempt": previous.get("attempt", 1),
                     "observed": {**observed, "分类代币": observed_tokens}, "rechecked_items": items})
        self.log("已核对金币、钻石、代币和商品剩余上限均未变化；上次点击未成交")
        self.click(1143, 85)
        return True

    def execute(self):
        self.category = self.param.get("category")
        if self.category not in PRODUCTS:
            raise RuntimeError("不支持的商店分类")
        if self.param.get("reconcile_only", False):
            return self.reconcile_unapplied()
        inspect_only = self.param.get("inspect_only", False)
        before = None
        attempt = 1
        if not inspect_only:
            previous = self.ledger()
            if previous:
                if previous["status"] == "confirmed":
                    self.log("今日该分类购买已有到账回执，跳过重复购买")
                    return True
                if previous["status"] != "not_applied" or previous.get("attempt", 1) >= 2:
                    raise RuntimeError("该分类此前购买结果未确认，不重复提交")
                attempt = previous.get("attempt", 1) + 1
            before = self.wallet()
            self.open_category()
            before["分类代币"] = self.category_balance()
        self.open_batch()
        items = self.walk(configure=not self.param.get("inspect_only", False))
        expected = totals(items)
        actual = self.summary()
        if expected != actual:
            raise RuntimeError(f"逐项金额与游戏总价不一致：{expected} / {actual}，不购买")
        self.log("已核对总价：" + json.dumps(actual, ensure_ascii=False))
        if self.param.get("inspect_only", False):
            self.log("本次只识别，没有提交购买")
            return True
        if not expected:
            self.log("所选商品已经售罄或没有可购买数量，跳过")
            self.click(1143, 85)
            return True
        selected = [item for item in items if item["selected"] and item["quantity"]]
        confirm = self.find(r"^批量购买$", (480, 600, 325, 65))
        if not confirm:
            raise RuntimeError("未确认批量购买按钮")
        token_cost = sum(value for currency, value in expected.items() if currency != "金币")
        if expected.get("金币", 0) > before["金币"] or token_cost > before["分类代币"]:
            self.log("余额不足以兑换所选整批商品，本次跳过，不追加资源")
            self.click(1143, 85)
            return True
        if self.param.get("preview", False):
            self.log("预览核对通过，余额：" + json.dumps(before, ensure_ascii=False) + "；未提交购买")
            self.click(1143, 85)
            return True
        self.ledger({"status": "unknown", "attempt": attempt, "before": before, "cost": expected, "items": selected})
        self.log("提交一次购买：" + json.dumps(selected, ensure_ascii=False))
        self.click_row(confirm, .8)
        until = time.monotonic() + 30
        reward_seen = False
        while time.monotonic() < until:
            self.capture()
            if self.close_reward():
                reward_seen = True
                continue
            if self.find(r"不足|没有足够|无法购买", (280, 200, 750, 300)):
                raise RuntimeError("游戏提示余额不足或无法购买，不重复提交")
            if reward_seen:
                if self.popup():
                    self.click(1143, 85)
                after_tokens = self.category_balance()
                after = self.wallet()
                if (after["金币"] != before["金币"] - expected.get("金币", 0)
                        or after["钻石"] != before["钻石"]
                        or after_tokens != before["分类代币"] - token_cost):
                    raise RuntimeError("已看到购买奖励，但余额变化与总价不一致，不再次购买")
                self.ledger({"status": "confirmed", "before": before, "after": {**after, "分类代币": after_tokens}, "cost": expected, "items": selected})
                self.log("购买奖励、实际扣款和钻石未变均已确认")
                self.open_category()
                return True
            self.pause(.5)
        if not reward_seen and self.popup() and attempt < 2:
            self.reconcile_unapplied()
            self.capture()
            return self.execute()
        raise RuntimeError("已提交一次购买，结果未确认，不再次购买")


ACTIONS = {"LocalShopBatch": ShopBatch()}
