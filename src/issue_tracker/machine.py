"""State machine functor: parameterized by a workflow module."""
from types import ModuleType
from typing import Union

from .workflow import Workflow
from .utils import die


class StateMachine:
    def __init__(self, workflow: Union[Workflow, ModuleType]):
        self.terminal = workflow.terminal
        self.active = workflow.active
        self.transitions = workflow.transitions
        self.on_block = workflow.on_block
        self.on_unblock = workflow.on_unblock

    def transition(self, issue: dict, name: str, **ctx) -> None:
        t = self.transitions.get(name)
        if not t:
            die(f"Unknown transition: {name}")

        frm, to, action = t[:3]
        guard = t[3] if len(t) > 3 else lambda **_: True

        if issue["status"] not in frm:
            die(f"Cannot {name} from '{issue['status']}'")

        action(issue, **ctx)
        if to and guard(issue=issue, **ctx):
            issue["status"] = to
