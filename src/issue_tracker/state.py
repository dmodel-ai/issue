"""State machine: transitions and handlers (re-exports from workflow module)."""
from .machine import StateMachine
from .workflows import issue as workflow

_machine = StateMachine(workflow)

# Re-export for backwards compat
TERMINAL = workflow.terminal
ACTIVE = workflow.active
transition = _machine.transition
pending = workflow.pending
on_block = workflow.on_block
on_unblock = workflow.on_unblock
