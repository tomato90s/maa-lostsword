import json

from maa.custom_action import CustomAction
from maa.context import Context


def _offset_center(box, offset_x=0, offset_y=0):
    x, y, w, h = box
    return x + w // 2 + offset_x, y + h // 2 + offset_y


class MyCustomAction(CustomAction):

    def run(
        self,
        context: Context,
        argv: CustomAction.RunArg,
    ) -> bool:

        print("my_action_111 is running!")

        return True


class DisableNode(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        node_name = json.loads(argv.custom_action_param)["node_name"]
        context.override_pipeline({f"{node_name}": {"enabled": False}})
        return CustomAction.RunResult(success=True)


class NodeOverride(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        ppover = json.loads(argv.custom_action_param)
        if not ppover:
            return CustomAction.RunResult(success=True)
        context.override_pipeline(ppover)
        return CustomAction.RunResult(success=True)


class CenterClick(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        cx, cy = _offset_center(argv.box)
        job = context.tasker.controller.post_click(cx, cy).wait()
        return CustomAction.RunResult(success=job.succeeded)


class OffsetClick(CustomAction):
    def run(self, context: Context, argv: CustomAction.RunArg) -> CustomAction.RunResult:
        param = json.loads(argv.custom_action_param or "{}")
        cx, cy = _offset_center(argv.box, int(param.get("x", 0)), int(param.get("y", 0)))
        job = context.tasker.controller.post_click(cx, cy).wait()
        return CustomAction.RunResult(success=job.succeeded)

ACTIONS = {"my_action_111": MyCustomAction(), "DisableNode": DisableNode(), "NodeOverride": NodeOverride(), "CenterClick": CenterClick(), "OffsetClick": OffsetClick()}
