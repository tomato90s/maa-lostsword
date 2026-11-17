import copy
import re
import unittest
from types import SimpleNamespace as NS
from unittest.mock import Mock

from maa.define import Rect
from agent.seasonal_actions import SecretCow,cow_attempts
from agent.slime_race_actions import SlimeRace


class CowFinnRecoveryTests(unittest.TestCase):
    def test_last_free_battle_uses_the_crop_without_the_bell_picture(self):
        action=SecretCow()
        action.expected_entry_cost=0
        action.wait_battle_start=action.leave_battle=action.open_dungeon=lambda:None
        action.wait_first_reward=lambda *args:None
        action.to_team=lambda:True
        action.bells=lambda:190
        action.log=lambda *args:None
        crops=[]
        def ocr(pattern,roi):
            crops.append(roi)
            return [NS(text=text) for text in (["1","进入"] if roi==(990,640,205,50) else ["簡","进入"])]
        action.ocr=ocr
        self.assertTrue(action.battle(190,1))
        self.assertEqual(action.last_cow_free,0)
        self.assertEqual(crops,[(990,640,205,50)])

    def pending(self,free=0,bells=190,floor="秘密奶牛副本第16层"):
        action=SecretCow()
        action.param={"use_custom_count":False,"limit":10}
        records=[{"status":"submitted","attempt":"last-free","time":"2026-11-17T14:19:39+08:00",
                  "week":"2026-W47","before_free":1,"entry_cost":0,"bells":190,"floor":"秘密奶牛副本第16层"}]
        original=copy.deepcopy(records[0])
        def ledger(record=None):
            if record is not None:records.append(record)
            return records
        action.ledger=ledger
        action.open_dungeon=lambda:None
        action.to_team=lambda:True
        action.title=lambda:NS(text=floor)
        action.free_remaining=lambda:free
        action.bells=lambda:bells
        action.log=lambda *args:None
        action.click_row=action.ensure_single_battle=lambda *args:self.fail("Never enter again while reconciling")
        return action,records,original

    def test_exhausted_last_free_receipt_recovers_without_fabricating_loot(self):
        action,records,original=self.pending()
        self.assertTrue(action.execute())
        self.assertEqual(records[0],original)
        self.assertEqual(records[-1]["status"],"counter_confirmed")
        self.assertFalse(records[-1]["reward_verified"])
        self.assertEqual(records[-1]["submission_time"],original["time"])
        self.assertNotIn("time",records[-1])
        self.assertEqual(cow_attempts(records),1)

    def test_changed_bells_unreadable_or_unchanged_free_count_and_other_floor_cannot_recover(self):
        for values in ({"bells":189},{"free":None},{"free":1},{"floor":"秘密奶牛副本第15层"}):
            action,records,_=self.pending(**values)
            with self.assertRaisesRegex(RuntimeError,"尚未核对"):action.execute()
            self.assertEqual(len(records),1)

    def test_nonfinal_or_paid_pending_entry_is_not_inferred_from_zero_free(self):
        for values in ({"before_free":2},{"entry_cost":1}):
            action,records,_=self.pending()
            records[0].update(values)
            with self.assertRaisesRegex(RuntimeError,"尚未核对"):action.execute()
            self.assertEqual(len(records),1)

    def test_finn_must_be_approached_vertically_before_using_the_nearest_npc_button(self):
        action=SlimeRace()
        action.move=Mock()
        action.click=lambda *args:self.fail("Joan is still nearer at this position")
        action.approach_finn(NS(box=Rect(620,270,40,20)),(640,615))
        self.assertEqual(action.move.call_args.args[:2],(0,-90))

    def test_only_close_horizontal_and_vertical_position_can_open_finn_chat(self):
        action=SlimeRace()
        action.move=lambda *args:self.fail("Already next to Finn")
        action.log=lambda *args:None
        action.click=Mock()
        action.approach_finn(NS(box=Rect(620,270,40,20)),(640,535))
        action.click.assert_called_once_with(790,610,.8)

    def test_finn_guide_title_survives_overlapping_player_and_npc_names(self):
        action=SlimeRace()
        guide=NS(text="[竞速向导",box=Rect(605,239,72,19))
        action.find=lambda pattern,roi:guide if "竞速向导" in pattern else None
        anchor,offset=action.finn_anchor()
        self.assertIs(anchor,guide)
        self.assertEqual(offset,275)
        action.log=lambda *args:None
        action.move=lambda *args:self.fail("Already within the visible guide's interaction radius")
        action.click=Mock()
        action.approach_finn(anchor,(643,526),offset)
        action.click.assert_called_once_with(790,610,.8)

    def test_merged_player_tag_recovers_only_beside_finn_with_both_name_ends(self):
        action=SlimeRace()
        action.username="Ronot256"
        guide=NS(text="[竞速向导]",box=Rect(598,238,75,22))
        action.find=lambda pattern,roi:guide if "竞速向导" in pattern else None
        merged=NS(text="Ro萜恩56",box=Rect(593,259,81,29),score=.74)
        action.ocr=lambda *args:[merged]
        self.assertEqual(action.player(),(633.5,514))
        for text in ("Other56","Ro萜恩99"):
            merged.text=text
            self.assertIsNone(action.player())

    def test_partial_player_name_elsewhere_in_the_frame_cannot_supply_a_position(self):
        action=SlimeRace()
        action.username="Ronot256"
        guide=NS(text="[竞速向导]",box=Rect(598,238,75,22))
        action.find=lambda pattern,roi:guide if "竞速向导" in pattern else None
        action.ocr=lambda *args:[NS(text="Ro萜恩56",box=Rect(145,62,90,18),score=.74)]
        self.assertIsNone(action.player())

    def test_other_npc_dialogue_requires_the_log_header_and_a_different_speaker(self):
        action=SlimeRace()
        visible={"header":"Log用","speaker":"圣女贞德"}
        def find(pattern,roi):
            text=visible["header" if roi==(25,10,150,60) else "speaker"]
            return NS(text=text) if re.search(pattern,text) else None
        action.find=find
        self.assertEqual(action.other_dialogue().text,"圣女贞德")
        visible["speaker"]="芬恩"
        self.assertIsNone(action.other_dialogue())
        visible.update(header="村庄",speaker="圣女贞德")
        self.assertIsNone(action.other_dialogue())

    def test_finn_search_goes_left_until_his_name_is_visible(self):
        action=SlimeRace()
        action.enter=action.ensure_street=action.leave_spawn=action.capture=lambda:None
        action.trace_navigation=lambda:None
        moves=[]
        action.move=lambda *args:moves.append(args)
        action.phase=lambda:"betting" if moves else None
        action.selection=action.result=action.dialogue=lambda:False
        action.other_dialogue=lambda:None
        action.find=action.player=lambda *args:None
        action.village=lambda:True
        action.open_race()
        self.assertEqual(moves,[(-1,0,400)])


if __name__=="__main__":unittest.main()
