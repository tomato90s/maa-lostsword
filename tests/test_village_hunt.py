import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS
sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent.village_actions import VillageHunt, verified_reward

class VillageTests(unittest.TestCase):
    def test_only_bounded_thirty_diamond_receipts_are_accepted(self):
        self.assertEqual(verified_reward(144347,144377,1),30)
        self.assertEqual(verified_reward(144347,144707,12),360)
        self.assertEqual(verified_reward(144347,144347,0),0)
        for after in (144346,144348,144737):
            with self.assertRaises(RuntimeError): verified_reward(144347,after,1)
        with self.assertRaises(RuntimeError): verified_reward(144347,144407,30)

    def test_changed_screen_never_sends_movement(self):
        action = VillageHunt()
        sent = []
        action.village = lambda:False
        action.pause = action.capture = lambda *args:None
        action.node = lambda name:None
        action.context = NS(tasker=NS(controller=NS(post_swipe=lambda *args:sent.append(args))))
        with self.assertRaisesRegex(RuntimeError,"界面已改变"):
            action.move(1,0)
        self.assertEqual(sent,[])

    def test_reentering_the_village_does_not_keep_pushing_the_player_down(self):
        action = VillageHunt()
        action.player = lambda: (640,600)
        action.move = lambda *args: self.fail("Already below the lobby portal")
        action.leave_spawn()

    def test_already_open_lobby_menu_is_not_toggled_closed(self):
        action = VillageHunt()
        action.find = lambda *args: True
        action.click = lambda *args: self.fail("Menu already open")
        action.open_menu()

    def test_ignored_menu_click_retries_only_after_confirming_the_lobby(self):
        from unittest.mock import patch
        action = VillageHunt()
        clock, clicks = [0], []
        action.find = lambda *args: len(clicks) == 2
        action.node = lambda *args: True
        action.pause = lambda seconds: clock.__setitem__(0,clock[0]+seconds)
        action.capture = lambda: None
        action.click = lambda *args: clicks.append(args[:2])
        with patch('agent.village_actions.time.monotonic',lambda:clock[0]):
            action.open_menu()
        self.assertEqual(clicks,[(1236,36),(1236,36)])

    def test_player_at_the_bottom_returns_to_the_safe_patrol_lane(self):
        action = VillageHunt()
        action.player = lambda: (640,716)
        sent = []
        action.move = lambda *args: sent.append(args)
        action.leave_spawn()
        self.assertEqual(sent,[(0,-1,178)])

    def test_candy_below_the_first_bag_page_is_found(self):
        import numpy as np
        action = VillageHunt()
        pages = [np.full((720,1280,3),value,dtype=np.uint8) for value in (10,60,110)]
        state = {"page":0,"swipes":0}
        action.image = pages[0]
        def swipe(*args):
            state["swipes"] += 1
            state["page"] += 1
            action.image = pages[state["page"]]
        hit = NS(hit=True,best_result=NS(box=(300,400,80,80)))
        miss = NS(hit=False)
        action.swipe = swipe
        action.find = lambda *args:True
        action.context = NS(run_recognition_direct=lambda *args:hit if state["page"]==2 else miss)
        self.assertEqual(action.find_candy(),(300,400,80,80))
        self.assertEqual(state["swipes"],2)

    def test_unmoving_bag_means_no_candy(self):
        import numpy as np
        action = VillageHunt()
        action.image = np.full((720,1280,3),10,dtype=np.uint8)
        swipes = []
        action.swipe = lambda *args:swipes.append(args)
        action.find = lambda *args:True
        action.context = NS(run_recognition_direct=lambda *args:NS(hit=False))
        self.assertIsNone(action.find_candy())
        self.assertEqual(len(swipes),1)

    def test_verified_daily_cap_does_not_open_the_game_again(self):
        action = VillageHunt()
        action.param = {"limit":12,"steps":16}
        action.journal = lambda:[{"status":"complete","gain":360}]
        action.log = lambda message:None
        action.wallet = lambda:(_ for _ in ()).throw(AssertionError("Should not open the game"))
        self.assertTrue(action.execute())

    def test_candy_selector_requires_the_complete_owned_quantity(self):
        for chosen, expected in (("21", True), ("2", False), ("[T", False)):
            with self.subTest(chosen=chosen):
                action = VillageHunt()
                sent = []
                balances = iter((1000, 1630))
                action.wallet = lambda: next(balances)
                action.open_menu = lambda: None
                action.find_candy = lambda: (200, 350, 100, 100)
                action.find = lambda *args: True
                action.ocr = lambda pattern, roi, only_rec=False: [NS(text="[21]" if roi == (760,120,90,35) else chosen)]
                action.click = lambda x, y, delay=.5: sent.append((x,y))
                if expected:
                    self.assertEqual(action.redeem(), (1000,1630,21))
                    self.assertIn((1085,666), sent)
                else:
                    with self.assertRaisesRegex(RuntimeError,"使用数量"):
                        action.redeem()
                    self.assertNotIn((1085,666), sent)

    def test_stored_candy_does_not_count_as_todays_hunt(self):
        action = VillageHunt()
        action.param = {"limit":12, "steps":1}
        records = [{"status":"inventory_redeemed", "gain":630}]
        def journal(record=None):
            if record is not None: records.append(record)
            return records
        action.journal = journal
        receipts = iter(((1000,1630,21), (1630,1660,1)))
        action.redeem = lambda: next(receipts)
        action.home = lambda: None
        action.find = lambda *args: NS(text="Ronot256")
        action.node = lambda *args: True
        action.patrol = lambda steps: (1,1)
        action.log = lambda message: None
        self.assertFalse(action.execute())
        self.assertEqual(records[-1]["confirmed_today"],30)
        self.assertEqual(records[-1]["status"],"partial")

    def test_chicken_without_templates_stops_before_touching_the_game(self):
        import agent.village_actions as module
        action = VillageHunt()
        action.param = {"target":"chicken","steps":16}
        action.home = lambda:(_ for _ in ()).throw(AssertionError("Should not open the game"))
        original = module.chicken_templates
        module.chicken_templates = lambda:[]
        try:
            with self.assertRaisesRegex(RuntimeError,"还没有鸡的识别图片"):
                action.execute()
        finally:
            module.chicken_templates = original

    def test_chicken_patrol_leaves_the_meat_in_the_bag(self):
        import agent.village_actions as module
        action = VillageHunt()
        action.param = {"target":"chicken","steps":16}
        calls = []
        action.home = lambda:calls.append("home")
        action.find = lambda *args:NS(text="Robot256")
        action.patrol = lambda steps:(calls.append(("patrol",steps)) or (5,2))
        action.node = lambda name:True
        action.log = lambda message:None
        action.redeem = lambda:(_ for _ in ()).throw(AssertionError("Chicken meat must stay in the bag"))
        action.journal = lambda *args:(_ for _ in ()).throw(AssertionError("No diamond journal for chickens"))
        original = module.chicken_templates
        module.chicken_templates = lambda:["local_village_chicken.png"]
        try:
            self.assertTrue(action.execute())
        finally:
            module.chicken_templates = original
        self.assertEqual(action.templates,["local_village_chicken.png"])
        self.assertIn(("patrol",16),calls)

    def test_chicken_templates_are_read_from_the_image_folder(self):
        import tempfile
        from agent.village_actions import chicken_templates
        with tempfile.TemporaryDirectory() as empty, tempfile.TemporaryDirectory() as folder:
            for name in ("local_village_chicken_side.png","local_village_chicken.png","local_village_hood.png"):
                (Path(folder)/name).write_bytes(b"")
            self.assertEqual(chicken_templates((empty,folder)),
                             ["local_village_chicken.png","local_village_chicken_side.png"])
            self.assertEqual(chicken_templates((empty,)),[])

    def test_unknown_target_is_rejected(self):
        action = VillageHunt()
        action.param = {"target":"duck"}
        with self.assertRaisesRegex(RuntimeError,"目标类型"):
            action.execute()

    def test_missing_targets_do_not_turn_or_end_the_patrol_early(self):
        action = VillageHunt()
        action.find = lambda *args: None
        action.player = lambda: (640,600)
        action.targets = lambda player: []
        action.portal = lambda: None
        action.trace = action.log = lambda *args: None
        action.move = action.strike = lambda *args, **kwargs: None
        for previous_misses in (9,23):
            result = action.patrol_step(previous_misses,previous_misses,0,1,0)
            self.assertEqual(result[2],1)
            self.assertFalse(result[-1])

    def test_a_stationary_player_and_background_turn_the_patrol_around(self):
        import numpy as np
        action = VillageHunt()
        action.image = np.zeros((720,1280,3),dtype=np.uint8)
        action.find = lambda *args: None
        action.player = lambda: (640,600)
        action.targets = lambda player: []
        action.portal = lambda: None
        action.trace = action.log = lambda *args: None
        action.move = action.strike = lambda *args, **kwargs: None
        direction = 1
        for step in range(3):
            result = action.patrol_step(step,step,0,direction,0)
            direction = result[2]
        self.assertEqual(direction,-1)

    def test_a_nearby_target_is_attacked_immediately_after_approach(self):
        action = VillageHunt()
        action.find = lambda *args: None
        action.player = lambda: (644,599)
        action.targets = lambda player: [(396,638)]
        action.trace = action.log = lambda *args: None
        calls = []
        action.move = lambda *args: calls.append('approach')
        action.strike = lambda **kwargs: calls.append('attack')
        result = action.patrol_step(1,0,0,1,0)
        self.assertEqual(calls,['approach','attack'])
        self.assertEqual(result[1],1)

    def test_an_empty_patrol_does_not_claim_the_unverified_daily_reward(self):
        action = VillageHunt()
        action.redeem = lambda: (1000,1000,0)
        action.journal = action.log = lambda *args: None
        self.assertFalse(action.collect_patrol_reward(12,0,0,360))

    def test_interrupted_patrol_settles_before_treating_candy_as_old_stock(self):
        action = VillageHunt()
        action.param = {"limit":1,"steps":1}
        records = [{"status":"started","attempt":"pending","inventory_empty":True,"username":"Player"}]
        action.journal = lambda record=None: records.append(record) if record is not None else records
        action.username = "Player"
        action.wallet = lambda: 1000
        action.redeem = lambda: (1000,1030,1)
        action.log = lambda *args: None
        action.patrol = lambda *args: self.fail("Reward already meets today's cap")
        self.assertTrue(action.execute())
        self.assertEqual(records[-1]["attempt"],"pending")
        self.assertEqual(records[-1]["gain"],30)

if __name__ == "__main__":unittest.main()
