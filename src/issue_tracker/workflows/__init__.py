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

INITIAL_STATE = getattr(workflow, "INITIAL_STATE", None)
DONE_STATE = getattr(workflow, "DONE_STATE", None)


def _phase_graph(transitions: Dict[str, Transition]) -> Dict[str, Set[str]]:
    graph: Dict[str, Set[str]] = {}
    for frm, to, *_ in transitions.values():
        if not to:
            continue
        for state in frm:
            graph.setdefault(state, set()).add(to)
    return graph


def _phase_order(transitions: Dict[str, Transition], initial: Optional[str], done: Optional[str]) -> list[str]:
    if not initial or not done:
        return []
    if initial == done:
        return [done]

    graph = _phase_graph(transitions)

    def dfs(node: str, visited: Set[str]) -> Optional[list[str]]:
        if node == done:
            return [node]
        visited.add(node)
        best = None
        for nxt in sorted(graph.get(node, [])):
            if nxt in visited:
                continue
            path = dfs(nxt, visited)
            if path:
                candidate = [node] + path
                if best is None or len(candidate) > len(best):
                    best = candidate
        visited.remove(node)
        return best

    return dfs(initial, set()) or [initial]


# Mainline states for gantt (longest acyclic path from initial to done).
phase_order = _phase_order(workflow.transitions, INITIAL_STATE, DONE_STATE)
