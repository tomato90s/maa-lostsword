import json
import unittest
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
COMMON = json.loads((ROOT / "assets/resource/pipeline/common.json").read_text("utf-8"))
STARTUP = json.loads((ROOT / "assets/resource/pipeline/startup.json").read_text("utf-8"))


class StartupRouteTests(unittest.TestCase):
    def test_existing_village_and_its_menu_have_a_route_to_lobby(self):
        for nodes in (STARTUP["StartApp"]["next"], COMMON["ReturnMain"]["next"]):
            self.assertIn("[JumpBack]LocalVillageGoLobby", nodes)
            self.assertIn("[JumpBack]LocalVillageOpenMenu", nodes)
            if "[JumpBack]全局-关闭菜单" in nodes:
                self.assertLess(nodes.index("[JumpBack]LocalVillageGoLobby"), nodes.index("[JumpBack]全局-关闭菜单"))
        self.assertIn("LinkStart", STARTUP["StartApp"]["next"])
        self.assertIn("HomeFlagCloseReturnMain", STARTUP["StartApp"]["next"])

    def test_village_exit_identifies_controls_and_uses_the_menu(self):
        village = COMMON["LocalVillageOpenMenu"]
        self.assertEqual(village["recognition"]["type"], "And")
        self.assertEqual(len(village["recognition"]["param"]["all_of"]), 2)
        self.assertEqual(village["action"]["param"]["target"], [1236, 36, 1, 1])
        self.assertEqual(COMMON["LocalVillageGoLobby"]["recognition"]["param"]["expected"], ["^前往大厅$"])
        self.assertGreaterEqual(COMMON["ReturnMain"]["timeout"], 60000)


if __name__ == "__main__":
    unittest.main()
