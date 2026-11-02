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

if __name__ == "__main__":unittest.main()
