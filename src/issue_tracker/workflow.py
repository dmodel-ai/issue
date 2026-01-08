"""Workflow protocol: signature for state machine modules."""
from typing import Protocol, Set, Callable, Tuple, Optional, Dict, runtime_checkable

Handler = Callable[..., None]
Guard = Callable[..., bool]
Transition = (
    Tuple[Set[str], Optional[str], Handler]
    | Tuple[Set[str], Optional[str], Handler, Guard]
)


@runtime_checkable
class Workflow(Protocol):
    terminal: Set[str]
    active: Set[str]
    transitions: Dict[str, Transition]

    def on_block(self, a: dict, b: dict) -> None: ...
    def on_unblock(self, a: dict, b: dict) -> None: ...
