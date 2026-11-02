import sys
import types
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))

try:
    from agent import seasonal_actions as seasonal
except ImportError as exc:  # maafw is bundled only with the runtime
    raise unittest.SkipTest(str(exc))


class FriendPointsTest(unittest.TestCase):
    def test_reads_live_counters(self):
        self.assertEqual(seasonal.friend_points("今日已赠送友情点数15/30 今日已领取友情点数4/30"), (15, 4))

    def test_missing_counter_is_unknown(self):
        self.assertIsNone(seasonal.friend_points("今日已赠送友情点数15/30"))


class CowFreeStateTest(unittest.TestCase):
    def test_bell_cost_is_not_free(self):
        # Live screen after this week's free entries: bell icon, "1", "进入".
        self.assertEqual(seasonal.cow_free_state("1 进入"), 0)
        self.assertEqual(seasonal.cow_free_state("进入"), 0)

    def test_explicit_free_marker(self):
        self.assertEqual(seasonal.cow_free_state("免费 2/3 进入"), 2)
        self.assertEqual(seasonal.cow_free_state("免费进入"), -1)
        self.assertEqual(seasonal.cow_free_state("进入 0/3"), 0)

    def test_week_uses_game_reset_timezone(self):
        # Sunday 15:30 UTC is already Monday in UTC+9.
        self.assertEqual(seasonal.game_week(datetime(2026, 11, 1, 15, 30, tzinfo=timezone.utc)), "2026-W45")
        self.assertEqual(seasonal.game_week(datetime(2026, 11, 1, 14, 30, tzinfo=timezone.utc)), "2026-W44")


if __name__ == "__main__":
    unittest.main()
