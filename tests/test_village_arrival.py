import unittest
from agent.village_actions import VillageHunt, LobbyBounce
from agent.daily_actions import VillageReturnLobby
from types import SimpleNamespace as NS


class VillageArrivalTests(unittest.TestCase):
    def model(self, outcomes):
        action = VillageHunt()
        action.param, action.events = {}, []
        failures = iter(outcomes)
        action.enter = lambda: action.events.append("enter")
        action.ensure_street = lambda: action.events.append("street")
        action.log = lambda *args: None
        def leave():
            action.events.append("leave")
            error = next(failures, None)
            if error: raise error
        action.leave_spawn = leave
        return action

    def test_arrival_bounce_is_recovered_before_patrol_starts(self):
        action = self.model([LobbyBounce("bounce"), None])
        action.prepare_street()
        self.assertEqual(action.events, ["enter","street","leave"] * 2)

    def test_repeated_arrival_bounces_remain_failed(self):
        action = self.model([LobbyBounce("bounce")] * 3)
        with self.assertRaises(LobbyBounce): action.prepare_street()
        self.assertEqual(action.events.count("enter"), 3)

    def test_unknown_screen_errors_are_not_retried(self):
        action = self.model([RuntimeError("unknown screen")])
        with self.assertRaisesRegex(RuntimeError,"unknown screen"): action.prepare_street()
        self.assertEqual(action.events.count("enter"), 1)

    def return_model(self, opened=False, dropped=False):
        action = VillageReturnLobby()
        action.page = "menu" if opened else "village"
        action.opens, action.returns, action.frames = 0, 0, 0
        action.pause = action.log = lambda *args: None
        action.node = lambda name: action.page == ("village" if name == "LocalVillageOpenMenu" else "home")
        action.find = lambda *args: NS(text="前往大厅") if action.page == "menu" else None
        def capture():
            action.frames += 1
            if action.page == "loading" and action.frames >= 3: action.page = "home"
        def click(*args):
            action.opens += 1
            if action.opens > int(dropped): action.page = "menu"
        def click_row(*args):
            action.returns += 1
            action.page, action.frames = "loading", 0
        action.capture, action.click, action.click_row = capture, click, click_row
        return action

    def test_open_village_menu_uses_destination_without_toggling_it(self):
        action = self.return_model(opened=True)
        self.assertTrue(action.execute())
        self.assertEqual((action.opens, action.returns), (0,1))

    def test_dropped_menu_open_is_retried_but_destination_is_clicked_once(self):
        action = self.return_model(dropped=True)
        self.assertTrue(action.execute())
        self.assertEqual((action.opens, action.returns), (2,1))

    def test_other_pages_delegate_without_clicking(self):
        action = self.return_model()
        action.page = "other"
        self.assertTrue(action.execute())
        self.assertEqual((action.opens, action.returns), (0,0))


if __name__ == "__main__": unittest.main()
