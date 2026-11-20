"""Regressions from the peer's November 17-20 v0.1.39/40 failure frames."""
import re
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock, patch

from maa.define import Rect
from agent.daily_actions import StonehengeGate
from agent.seasonal_actions import RaidSweep
from agent.shop_actions import ShopBatch
from test_seasonal_tasks import RaidReplay
from test_shop_receipts import Replay as ShopReplay


class PeerRecognitionTests(unittest.TestCase):
    def ticket_reader(self, results):
        action = RaidSweep()
        values = iter(results)
        calls = []
        def ocr(pattern, roi, only_rec=False):
            calls.append((roi, only_rec))
            value = next(values)
            return [NS(text=value)] if value is not None else []
        action.ocr = ocr
        action.pause = Mock()
        action.capture = Mock()
        action.click = action.click_row = Mock(side_effect=AssertionError("Reading must not send input"))
        return action, calls

    def test_raid_numeric_crop_keeps_leading_digits_and_crosschecks_modes(self):
        for value in ("0", "15", "335", "403", "12345"):
            action, calls = self.ticket_reader([value, value])
            self.assertEqual(action.ticket_balance(), int(value))
            self.assertEqual(calls, [((1140,21,65,25), False), ((1140,21,65,25), True)])
            action.capture.assert_not_called()

    def test_raid_disagreement_refreshes_without_repeating_the_sweep(self):
        action, _ = self.ticket_reader(["5", "15", "15", "15"])
        self.assertEqual(action.ticket_balance(), 15)
        action.capture.assert_called_once()
        action.click.assert_not_called()

    def test_raid_persistent_conflict_or_unreadable_value_stops(self):
        for readings in (["5", "15"]*3, [None, "15"]*3, ["1/3", "15"]*3):
            action, _ = self.ticket_reader(readings)
            with self.assertRaisesRegex(RuntimeError, "门票数量识别不一致"):
                action.ticket_balance()
            self.assertEqual(action.capture.call_count, 2)
            action.click.assert_not_called()

    def test_actual_ticket_spend_still_stops_after_one_submission(self):
        model = RaidReplay()
        click = model.click_row
        def spend(row, delay=.5):
            click(row, delay)
            model.tickets -= 1
        model.click_row = spend
        with patch("agent.seasonal_actions.time.monotonic", lambda:model.clock):
            with self.assertRaisesRegex(RuntimeError, "门票变化"):
                model.execute()
        self.assertEqual(model.commits, 1)
        self.assertEqual(model.records[-1]["status"], "reward_observed")

    def test_saved_reward_can_resume_only_the_two_remaining_free_sweeps(self):
        model = RaidReplay(previous={"status":"reward_observed", "before_tickets":403,
                                     "before_free":3}, free=2)
        with patch("agent.seasonal_actions.time.monotonic", lambda:model.clock):
            self.assertTrue(model.execute())
        self.assertEqual((model.commits, model.free, model.tickets), (2,0,403))
        self.assertEqual(model.records[1]["status"], "counter_confirmed")
        self.assertEqual(model.records[1]["after_free"], 2)

    def test_stonehenge_return_uses_the_separate_free_sweep_button(self):
        action = StonehengeGate()
        action.context = NS(get_node_data=lambda name:{"enabled":True}, override_next=Mock(return_value=True))
        action.argv = NS(node_name="Local_DungeonAfter")
        action.capture = action.pause = action.log = lambda *args:None
        state, clicks = ["preparation"], []
        def find(pattern, roi):
            texts = {(690,635,145,55):["-", "一键扫荡"],
                     (550,620,400,75):["-", "键扫荡", "10"]} if state[0] == "preparation" else {
                         (125,535,130,70):["巨石阵"]}
            return next((NS(text=t) for t in texts.get(roi,[]) if re.search(pattern,t)), None)
        def click(x,y,delay):
            clicks.append((x,y))
            state[0] = "list"
        action.find, action.click = find, click
        self.assertTrue(action.execute())
        self.assertEqual(clicks, [(1235,35)])
        action.context.override_next.assert_called_once_with("Local_DungeonAfter", ["副本_点击巨石阵"])

    def test_precommit_shop_recognition_failure_does_not_mark_the_category_bought(self):
        model = ShopReplay()
        walk = model.walk
        model.walk = Mock(side_effect=RuntimeError("商品勾选状态不明确：普通精炼石"))
        with patch("agent.shop_actions.time.monotonic", lambda:model.clock):
            with self.assertRaisesRegex(RuntimeError, "勾选状态不明确"):
                model.execute()
            self.assertEqual((model.commits, model.records), (0,[]))
            model.walk = walk
            self.assertTrue(model.execute())
        self.assertEqual(model.commits, 1)
        self.assertEqual(model.records[-1]["status"], "confirmed")

    def test_achievement_toast_can_clear_before_reading_batch_rows(self):
        action = ShopBatch()
        frames = [0]
        action.popup = lambda:frames[0] >= 2
        action.capture = lambda:frames.__setitem__(0, frames[0]+1)
        action.pause = lambda *args:None
        action.ocr = lambda *args:[NS(text="精灵王的信物", box=Rect(258,148,108,24))]
        action.number = lambda roi, parser=None:(3,3) if parser else 1500
        action.template = lambda name, roi, *args, **kwargs:name in ("local_shop_checked.png", "local_shop_raid.png")
        action.click = Mock(side_effect=AssertionError("Waiting must not submit a purchase"))
        self.assertEqual(action.rows()[0]["quantity"], 3)
        self.assertEqual(frames[0], 2)
        action.click.assert_not_called()

    def test_closed_batch_cannot_scroll_or_send_purchase_input(self):
        action = ShopBatch()
        action.popup = lambda:False
        action.check = action.capture = action.pause = lambda *args:None
        swipe = Mock()
        action.context = NS(tasker=NS(controller=NS(post_swipe=swipe)))
        with self.assertRaisesRegex(RuntimeError, "批量窗口已关闭"):
            action.scroll()
        swipe.assert_not_called()

    def shop_checkbox_reader(self, states):
        action = ShopBatch()
        frame = [0]
        action.popup = lambda: True
        action.ocr = Mock(return_value=[NS(text='普通精炼石', box=Rect(258, 408, 108, 24))])
        action.number = Mock(side_effect=lambda roi, parser=None: (0, 5) if parser else 0)
        def template(name, roi, *args, **kwargs):
            selected, unchecked = states[min(frame[0], len(states) - 1)]
            return {'local_shop_checked.png': selected, 'local_shop_unchecked.png': unchecked,
                    'local_shop_raid.png': True}.get(name, False)
        action.template = template
        action.capture = Mock(side_effect=lambda: frame.__setitem__(0, frame[0] + 1))
        action.pause, action.log = Mock(), Mock()
        action.click = action.click_row = Mock(side_effect=AssertionError('Reading must not send input'))
        return action

    def test_shop_flash_refreshes_the_whole_page_without_toggling(self):
        for ambiguous in [(False, False), (True, True)]:
            with self.subTest(ambiguous=ambiguous):
                action = self.shop_checkbox_reader([ambiguous, (False, True)])
                items = action.rows()
                self.assertEqual([(item['name'], item['selected'], item['quantity']) for item in items],
                                 [('普通精炼石', False, 0)])
                action.capture.assert_called_once()
                self.assertEqual(action.ocr.call_count, 2)
                action.pause.assert_called()
                action.click.assert_not_called()

    def test_persistent_shop_checkbox_ambiguity_stops_after_bounded_wait(self):
        action = self.shop_checkbox_reader([(False, False)])
        with self.assertRaisesRegex(RuntimeError, '勾选状态.*不明确.*普通精炼石'):
            action.rows()
        self.assertGreater(action.capture.call_count, 0)
        self.assertLessEqual(action.capture.call_count, 10)
        action.click.assert_not_called()

    def test_shop_price_error_is_not_hidden_as_a_flash(self):
        action = self.shop_checkbox_reader([(False, True)])
        action.number.side_effect = RuntimeError('无法确认商店数量或价格')
        with self.assertRaisesRegex(RuntimeError, '数量或价格'):
            action.rows()
        action.capture.assert_not_called()
        action.click.assert_not_called()


if __name__ == "__main__":
    unittest.main()
