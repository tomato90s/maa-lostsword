import sys
from pathlib import Path

# 嵌入式 Python 的 _pth 文件限制 sys.path 时不会自动加入脚本目录，需手动确保
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maa.agent.agent_server import AgentServer
from maa.toolkit import Toolkit

from agent import my_action
from agent import local_actions
from agent import crash_recovery
from agent import daily_actions
from agent import seasonal_actions
from agent import shop_actions
from agent import village_actions
from agent import my_reco


def main():
    Toolkit.init_option("./")

    if len(sys.argv) < 2:
        print("Usage: python main.py <socket_id>")
        print("socket_id is provided by AgentIdentifier.")
        sys.exit(1)

    socket_id = sys.argv[-1]

    crash_recovery.configure_shell_api()
    crash_recovery.initialize_preferences(Path(__file__).resolve().parent.parent)
    for name, action in {**my_action.ACTIONS, **local_actions.ACTIONS,
                         **crash_recovery.ACTIONS, **daily_actions.ACTIONS,
                         **seasonal_actions.ACTIONS, **shop_actions.ACTIONS, **village_actions.ACTIONS}.items():
        AgentServer.register_custom_action(name, action)
    for name, recognition in crash_recovery.RECOGNITIONS.items():
        AgentServer.register_custom_recognition(name, recognition)

    AgentServer.start_up(socket_id)
    AgentServer.join()
    AgentServer.shut_down()


if __name__ == "__main__":
    main()
