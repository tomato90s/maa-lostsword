import json
import re
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
from unittest.mock import Mock

from maa.define import Rect
from agent.seasonal_actions import MailClaim


class MailReplay(MailClaim):
    def __init__(self, response="empty", delay=0):
        self.param = {}
        self.state, self.response, self.delay = "mail", response, delay
        self.frames, self.commits, self.reward_closed = 0, 0, 0
        self.events = []

    def open_mail(self): pass
    def leave_mail(self):
        assert self.page(), "Result must first return to mailbox"
        self.state = "home"
    def page(self):return self.state == "mail"
    def empty_notice(self):return self.state == "empty"
    def pause(self,*args):pass
    def log(self,*args):pass
    def capture(self):
        self.frames += 1
        if self.state == "waiting" and self.frames > self.delay:
            self.state = self.response
    def find(self, pattern, roi=None):
        texts = {"mail":["一键领取"],"empty":["暂无可领取的奖励。","确认"],
                 "waiting":[],"reward":[],"unknown":[]}[self.state]
        return next((NS(text=t) for t in texts if re.search(pattern,t)),None)
    def click_row(self,row,delay=.5):
        self.events.append(row.text)
        if row.text == "一键领取":
            self.commits += 1
            self.frames, self.state = 0, "waiting"
        elif row.text == "确认" and self.state == "empty":
            self.state = "mail"
        else:raise AssertionError("Unexpected mailbox input: "+row.text)
    def close_reward(self):
        if self.state != "reward":return False
        self.reward_closed += 1
        self.state = "mail"
        return True


class MailTests(unittest.TestCase):
    def test_mail_is_imported_as_a_separate_daily_task(self):
        root = Path(__file__).resolve().parents[1]
        interface = json.loads((root/"assets/interface.json").read_text("utf-8"))
        task = json.loads((root/"assets/resource/tasks/daily/mail_task.json").read_text("utf-8"))["task"][0]
        self.assertIn("resource/tasks/daily/mail_task.json", interface["import"])
        self.assertEqual(task["entry"], "LocalMail_Entry")
        self.assertTrue(task["default_check"])

    def test_empty_mail_is_acknowledged_once_without_deleting_anything(self):
        action = MailReplay()
        self.assertTrue(action.execute())
        self.assertEqual(action.events,["一键领取","确认"])
        self.assertEqual(action.commits,1)

    def test_reopening_an_existing_empty_notice_does_not_submit_again(self):
        action = MailReplay()
        action.state = "empty"
        self.assertTrue(action.execute())
        self.assertEqual((action.events,action.commits),(["确认"],0))

    def test_reward_must_close_and_return_to_mailbox_before_success(self):
        action = MailReplay(response="reward",delay=4)
        self.assertTrue(action.execute())
        self.assertEqual((action.commits,action.reward_closed),(1,1))
        self.assertEqual(action.state,"home")

    def test_unobserved_result_never_repeats_the_claim(self):
        action = MailReplay(response="unknown")
        with self.assertRaisesRegex(RuntimeError,"结果尚未确认"):
            action.execute()
        self.assertEqual(action.events,["一键领取"])

    def test_inspect_only_never_claims(self):
        action = MailReplay()
        action.param = {"inspect_only":True}
        self.assertTrue(action.execute())
        self.assertEqual(action.commits,0)

    def test_missing_claim_button_fails_without_an_input(self):
        action = MailReplay()
        action.find = lambda *args:None
        with self.assertRaisesRegex(RuntimeError,"一键领取按钮"):
            action.execute()
        self.assertEqual(action.events,[])

    def test_navigation_requires_menu_and_the_mail_icon(self):
        action = MailClaim()
        state, events = ["home"], []
        action.home = Mock()
        action.page = lambda:state[0] == "mail"
        action.capture = action.pause = lambda *args:None
        action.find = lambda *args:NS(text="游戏专属编号") if state[0] == "menu" else None
        action.node = lambda name:(NS(best_result=NS(box=Rect(1215,175,38,32))) if name == "LocalMail_MenuIcon" and state[0] == "menu"
                                  else name == "HomeFlagCloseReturnMain" and state[0] == "home")
        def click(x,y,delay):
            events.append((x,y))
            if (x,y) == (1236,36) and state[0] == "home":state[0] = "menu"
            elif (x,y) == (1234,191) and state[0] == "menu":state[0] = "mail"
            else:raise AssertionError((x,y,state[0]))
        action.click = click
        action.open_mail()
        self.assertEqual(events,[(1236,36),(1234,191)])

    def test_known_mail_page_is_closed_before_fresh_parent_navigation(self):
        action = MailClaim()
        state = ["mail"]
        action.page = lambda:state[0] == "mail"
        def click(x,y,delay):
            self.assertEqual((x,y),(1236,36))
            state[0] = "village"
        def home():
            self.assertEqual(state[0],"village")
            state[0] = "home"
        action.click, action.home = click, home
        action.leave_mail()
        self.assertEqual(state[0],"home")


if __name__ == "__main__":unittest.main()
