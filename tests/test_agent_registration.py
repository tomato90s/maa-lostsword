import importlib
import json
import sys
import unittest
from pathlib import Path
from unittest.mock import patch

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))

from maa.agent.agent_server import AgentServer


class AgentRegistrationTests(unittest.TestCase):
    def test_main_registers_every_action_used_by_pipeline(self):
        # Import decorators and invoke the real entry point with the IPC/native
        # boundaries replaced, so no game, framework process or UI is needed.
        with patch.object(AgentServer, "register_custom_recognition"):
            main = importlib.import_module("agent.main")
        with patch.object(sys, "argv", ["agent/main.py", "test-socket"]), \
                patch.object(main.Toolkit, "init_option"), \
                patch.object(main.crash_recovery, "configure_shell_api"), \
                patch.object(main.crash_recovery, "initialize_preferences"), \
                patch.object(AgentServer, "register_custom_action") as actions, \
                patch.object(AgentServer, "register_custom_recognition") as recognitions, \
                patch.object(AgentServer, "start_up") as start, \
                patch.object(AgentServer, "join"), \
                patch.object(AgentServer, "shut_down"):
            main.main()
        registered = {call.args[0] for call in actions.call_args_list}
        self.assertIn("LocalGameMissing", {call.args[0] for call in recognitions.call_args_list})
        start.assert_called_once_with("test-socket")
        for path in (ROOT / "assets/resource/pipeline").glob("*.json"):
            nodes = json.loads(path.read_text(encoding="utf-8"))
            for name, node in nodes.items():
                if name.startswith("$") or not isinstance(node, dict):
                    continue
                action = node.get("action", {})
                if isinstance(action, dict) and action.get("type") == "Custom":
                    custom = action["param"]["custom_action"]
                    self.assertIn(custom, registered, f"{path.name}: {name} -> {custom}")


if __name__ == "__main__":
    unittest.main(verbosity=2)
