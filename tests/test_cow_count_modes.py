import re
import unittest
from types import SimpleNamespace as NS
from unittest.mock import patch

from agent.seasonal_actions import SecretCow, cow_attempts, cow_paid_attempts


class CowModel(SecretCow):
    def __init__(self, param, free=3, bells=20, used=0):
        self.param, self.free, self.balance = param, free, bells
        self.records = [{"attempt":str(i),"status":"confirmed","entry_cost":1} for i in range(used)]
        self.entries, self.visits = [], 0
    def ledger(self, record=None):
        if record is not None: self.records.append(record)
        return self.records
    def open_dungeon(self): self.visits += 1
    def to_team(self): return True
    def title(self): return NS(text="秘密奶牛副本第16层")
    def ocr(self, *args): return [NS(text=f"进入{self.free}/3" if self.free else "1 进入")]
    def find(self, *args): return NS(text="进入")
    def ensure_single_battle(self): return self.free, 0 if self.free else 1
    def bells(self): return self.balance
    def click_row(self, *args): self.entries.append(self.expected_entry_cost)
    def log(self, *args): pass
    def battle(self, bells, before_free):
        if self.free: self.free -= 1
        else: self.balance -= 1
        self.last_cow_free = self.free
        return True


class CowCountModesTest(unittest.TestCase):
    def test_off_ignores_a_smaller_saved_limit_and_uses_all_remaining_free(self):
        action = CowModel({"use_custom_count":False,"limit":1},free=3,used=5)
        self.assertTrue(action.execute())
        self.assertEqual(action.entries,[0,0,0])
        self.assertEqual(action.balance,20)

    def test_off_does_not_parse_an_inactive_custom_input(self):
        action = CowModel({"limit":"not-a-number"},free=2)
        self.assertTrue(action.execute())
        self.assertEqual(action.entries,[0,0])

    def test_off_skips_exhausted_free_entries_even_when_the_saved_limit_is_ten(self):
        action = CowModel({"use_custom_count":False,"limit":10},free=0)
        self.assertTrue(action.execute())
        self.assertEqual(action.entries,[])
        self.assertEqual(action.balance,20)

    def test_on_ten_uses_three_free_plus_ten_bells_and_stops_at_the_target(self):
        action = CowModel({"use_custom_count":True,"limit":10})
        self.assertTrue(action.execute())
        self.assertEqual(action.entries,[0,0,0]+[1]*10)
        self.assertEqual((action.free,action.balance,cow_attempts(action.records)),(0,10,13))
        self.assertEqual(cow_paid_attempts(action.records),10)
        self.assertTrue(action.execute())
        self.assertEqual(len(action.entries),13)

    def test_custom_target_counts_weekly_paid_entries_only(self):
        action = CowModel({"use_custom_count":True,"limit":10},used=4,free=2)
        self.assertTrue(action.execute())
        self.assertEqual(action.entries,[0,0]+[1]*6)
        self.assertEqual(cow_paid_attempts(action.records),10)

    def test_free_refresh_is_still_used_when_the_paid_quota_is_full(self):
        action = CowModel({"use_custom_count":True,"limit":10},used=10,free=3)
        self.assertTrue(action.execute())
        self.assertEqual(action.entries,[0,0,0])
        self.assertEqual(action.balance,20)

    def test_missing_active_limit_defaults_to_ten_paid_entries(self):
        action = CowModel({"use_custom_count":True},free=0)
        self.assertTrue(action.execute())
        self.assertEqual(action.entries,[1]*10)

    def test_free_and_legacy_unknown_entries_are_not_paid_receipts(self):
        records = [{"attempt":"free","status":"confirmed","entry_cost":0},
                   {"attempt":"unknown","status":"confirmed"},
                   {"attempt":"paid","status":"submitted","entry_cost":1},
                   {"attempt":"paid","status":"confirmed","entry_cost":1}]
        self.assertEqual(cow_paid_attempts(records),1)

    def test_observed_auto_repeat_spending_counts_against_the_bell_quota(self):
        records=[{"attempt":"one","status":"confirmed","entry_cost":1,"paid_spent":1},
                 {"attempt":"repeat","status":"submitted","entry_cost":1},
                 {"attempt":"repeat","status":"safety_stopped","entry_cost":1,"paid_spent":13}]
        self.assertEqual(cow_paid_attempts(records),14)
        records.append({"attempt":"repeat","status":"safety_stopped","entry_cost":1,"paid_spent":13})
        self.assertEqual(cow_paid_attempts(records),14)

    def test_result_auto_repeat_is_disabled_before_clicking_return(self):
        action=SecretCow()
        checked=[True]
        action.find=lambda pattern,roi:NS(text="返回" if pattern==r"^返回$" else "matched")
        toggle=NS(text="repeat-toggle")
        action.node=lambda *args:NS(best_result=toggle) if checked[0] else None
        action.log=lambda *args:None
        sent=[]
        def click(row,*args):
            sent.append(row.text)
            if row is toggle:checked[0]=False
        action.click_row=click
        self.assertTrue(action.leave_result())
        self.assertEqual(sent,["repeat-toggle","返回"])

    def test_an_ignored_checkbox_click_is_rechecked_before_return(self):
        action=SecretCow()
        action.find=lambda *args:NS(text="返回")
        action.node=lambda *args:NS(best_result=NS(text="repeat-toggle"))
        action.log=lambda *args:None
        sent=[]
        action.click_row=lambda row,*args:sent.append(row.text)
        self.assertTrue(action.leave_result())
        self.assertEqual(sent,["repeat-toggle"])

    def test_current_cow_team_page_does_not_reopen_the_lobby_menu(self):
        action=SecretCow()
        action.title=lambda:True
        action.find=lambda *args:NS(text="队伍编排")
        action.open_menu=lambda *args:self.fail("The Cow team page is already open")
        action.open_dungeon()

    def test_insufficient_bells_stop_without_entering_or_buying(self):
        action = CowModel({"use_custom_count":True,"limit":10},free=0,bells=0)
        self.assertTrue(action.execute())
        self.assertEqual(action.entries,[])
        self.assertEqual(action.records,[])

    def test_custom_zero_still_uses_remaining_free_entries(self):
        action = CowModel({"use_custom_count":True,"limit":0})
        self.assertTrue(action.execute())
        self.assertEqual(action.entries,[0,0,0])
        self.assertEqual(action.balance,20)

    def test_invalid_switch_or_active_count_never_opens_the_game(self):
        for param in ({"use_custom_count":"Yes","limit":10},
                      {"use_custom_count":True,"limit":100},
                      {"use_custom_count":True,"limit":True}):
            action = CowModel(param)
            with self.assertRaises(RuntimeError): action.execute()
            self.assertEqual(action.visits,0)

    def test_paid_entry_requires_the_switch_the_bell_icon_and_exact_one_bell_price(self):
        for enabled, icon, price, allowed in ((False,True,1,False),(True,False,1,False),
                                               (True,True,2,False),(True,True,1,True)):
            action = SecretCow()
            action.use_custom_count = enabled
            action.capture = lambda: None
            action.title = lambda: True
            action.find = lambda *args: NS(text="队伍编排")
            action.ocr = lambda *args: [NS(text="1 进入")]
            action.node = lambda *args: icon
            action.number = lambda *args: price
            if allowed: self.assertEqual(action.ensure_single_battle(),(0,1))
            else:
                with self.assertRaises(RuntimeError): action.ensure_single_battle()

    def test_a_paid_entry_charge_alone_is_not_treated_as_battle_loot(self):
        action = SecretCow()
        action.expected_entry_cost = 1
        frames = [0]
        action.capture = lambda: frames.__setitem__(0,frames[0]+1)
        action.pause = lambda *args: None
        action.log = lambda *args: None
        action.number = lambda *args: 195
        action.battle_bells = lambda: 195
        def find(pattern, roi):
            if "(?:传说" in pattern: return NS(text="传说武器") if frames[0]>=3 else None
            if pattern == "秘密奶牛副本": return NS(text="秘密奶牛副本第16层")
            return None
        action.find = find
        self.assertTrue(action.wait_first_reward(196))
        self.assertEqual(frames[0],3)

    def test_combat_balance_is_unknown_without_a_visible_bell_icon(self):
        action = SecretCow()
        action.node = lambda *args: None
        action.ocr = lambda *args,**kwargs: self.fail("Unrelated combat text must not be read as bells")
        self.assertIsNone(action.battle_bells())

    def test_combat_balance_requires_two_agreeing_reads_beside_the_bell_icon(self):
        for readings,expected in ((("195","195"),195),(("95","195"),None),(("195","1,95x"),None)):
            action=SecretCow()
            action.node=lambda *args:NS(best_result=NS(box=[895,20,28,32]))
            values=iter(readings)
            action.ocr=lambda *args,**kwargs:[NS(text=next(values),score=.99)]
            self.assertEqual(action.battle_bells(),expected)

    def test_reward_banner_does_not_delay_exit_with_screen_center_taps(self):
        action=SecretCow()
        phase=["battle"]
        action.capture=action.pause=lambda *args:None
        action.title=lambda:None
        action.node=lambda *args:True
        action.log=lambda *args:None
        def find(pattern,roi):
            choices={"battle":["传说武器","秘密奶牛副本第16层"],"menu":["退场"],"home":["战斗","角色","召唤"]}[phase[0]]
            return next((NS(text=text) for text in choices if re.search(pattern,text)),None)
        action.find=find
        sent=[]
        def click(x,y,delay):
            sent.append((x,y))
            self.assertEqual((x,y),(1236,36))
            phase[0]="menu"
        action.click=click
        action.click_row=lambda *args:phase.__setitem__(0,"home")
        self.assertTrue(action.leave_battle())
        self.assertEqual(sent,[(1236,36)])

    def test_weak_duplicate_digit_does_not_override_two_clear_full_balance_reads(self):
        action=SecretCow()
        action.node=lambda *args:NS(best_result=NS(box=[1081,19,28,32]))
        def ocr(*args,only_rec=False):
            full=NS(text="196",score=.996)
            return [full] if only_rec else [NS(text="1",score=.826),full]
        action.ocr=ocr
        self.assertEqual(action.battle_bells(),196)

    def test_paid_result_requires_exactly_one_bell_and_no_free_counter_change(self):
        for after, expected in ((195,True),(194,False),(196,False)):
            action = SecretCow()
            action.expected_entry_cost = 1
            action.wait_battle_start = action.leave_battle = action.open_dungeon = lambda: None
            action.wait_first_reward = lambda *args: None
            action.to_team = lambda: True
            action.bells = lambda: after
            action.ocr = lambda *args: [NS(text="1 进入")]
            action.log = lambda *args: None
            if expected: self.assertTrue(action.battle(196,0))
            else:
                with self.assertRaises(RuntimeError): action.battle(196,0)

    def test_timeout_still_gives_exit_a_bounded_cleanup_window(self):
        action = SecretCow()
        action.deadline = 1
        observed = []
        action._leave_battle = lambda: observed.append(action.deadline) or True
        with patch("agent.seasonal_actions.time.monotonic",return_value=100):
            self.assertTrue(action.leave_battle())
        self.assertEqual(observed,[165])
        self.assertEqual(action.deadline,1)
