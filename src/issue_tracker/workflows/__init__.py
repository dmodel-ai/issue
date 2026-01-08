"""Workflows: protocol, machine, and dynamic loading."""
import os
import importlib
from types import ModuleType
from typing import Protocol, Set, Callable, Tuple, Optional, Dict, Union, runtime_checkable

from ..utils import die

# Protocol
Handler = Callable[..., None]
Guard = Callable[..., bool]
Transition = (
    Tuple[Set[str], Optional[str], Handler]
    | Tuple[Set[str], Optional[str], Handler, Guard]
)


@runtime_checkable
class Workflow(Protocol):
    transitions: Dict[str, Transition]
    status_colors: Dict[str, str]


# Machine
class StateMachine:
    def __init__(self, workflow: Union[Workflow, ModuleType]):
        self.transitions = workflow.transitions
        self.status_colors = workflow.status_colors

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


# Load active workflow
name = os.environ.get("ISSUE_WORKFLOW", "issue")
workflow = importlib.import_module(f".{name}", __package__)

_machine = StateMachine(workflow)
transition = _machine.transition
status_colors = workflow.status_colors
pending = getattr(workflow, 'pending', None)
