import sys
import unittest
from pathlib import Path
from types import SimpleNamespace as NS

sys.path.insert(0,str(Path(__file__).resolve().parents[1]))
from agent.daily_actions import GuildDonationLimit


class GuildLimitTests(unittest.TestCase):
    def test_known_daily_limit_closes_once_and_disables_the_donation_entry(self):
        action = GuildDonationLimit()
        modal, clicks, overrides = [True], [], {}
        action.context = NS(override_pipeline=overrides.update)
        action.log = lambda *args: None
        action.find = lambda pattern, roi: (NS(text="确认") if pattern == "^确认$" else
            modal[0] if "今日捐献" in pattern else not modal[0])
        def click(row, delay):
            clicks.append(row.text)
            modal[0] = False
        action.click_row = click
        self.assertTrue(action.execute())
        self.assertEqual(clicks,["确认"])
        self.assertEqual(overrides,{"公会-捐献":{"enabled":False}})

    def test_unknown_modal_does_not_get_clicked(self):
        action = GuildDonationLimit()
        action.find = lambda *args: None
        action.click_row = lambda *args: self.fail("Unknown modal must stay untouched")
        with self.assertRaisesRegex(RuntimeError,"未确认公会捐献已满"):
            action.execute()


if __name__ == "__main__": unittest.main()
