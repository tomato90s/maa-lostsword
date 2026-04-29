import json

from maa.agent.agent_server import AgentServer
from maa.custom_action import CustomAction
from maa.context import Context


@AgentServer.custom_action("my_action_111")
class MyCustomAction(CustomAction):

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:

        print("my_action_111 is running!")

        return True


@AgentServer.custom_action("DisableNode")
class DisableNode(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        node_name = json.loads(argv.custom_action_param)["node_name"]
        context.override_pipeline({f"{node_name}": {"enabled": False}})
        return CustomAction.RunResult(success=True)


@AgentServer.custom_action("NodeOverride")
class NodeOverride(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        ppover = json.loads(argv.custom_action_param)
        if not ppover:
            return CustomAction.RunResult(success=True)
        context.override_pipeline(ppover)
        return CustomAction.RunResult(success=True)
