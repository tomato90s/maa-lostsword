import sys
from pathlib import Path

# 嵌入式 Python 的 _pth 文件限制 sys.path 时不会自动加入脚本目录，需手动确保
sys.path.insert(0, str(Path(__file__).resolve().parent.parent))

from maa.agent.agent_server import AgentServer
from maa.toolkit import Toolkit

from agent import my_action
from agent import my_reco


def _apply_pending_update():
    """agent 启动前：先完成上次因 Windows 文件锁定未做完的替换。"""
    try:
        from agent.updater import ResourceUpdater

        root = Path(__file__).resolve().parent.parent
        ResourceUpdater.apply_pending(root)
    except Exception as e:
        print(f"[WARN] 应用未完成更新失败: {e}")


def _check_resource_update():
    try:
        from agent.updater import ResourceUpdater

        root = Path(__file__).resolve().parent.parent
        updater = ResourceUpdater(root)
        updater.check_and_update()
    except Exception as e:
        print(f"[WARN] 资源更新检查失败: {e}")


def main():
    _apply_pending_update()
    _check_resource_update()

    Toolkit.init_option("./")

    if len(sys.argv) < 2:
        print("Usage: python main.py <socket_id>")
        print("socket_id is provided by AgentIdentifier.")
        sys.exit(1)

    socket_id = sys.argv[-1]

    AgentServer.start_up(socket_id)
    AgentServer.join()
    AgentServer.shut_down()


if __name__ == "__main__":
    main()
