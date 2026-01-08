"""State machine: transitions and handlers (re-exports from workflow module)."""
from .machine import StateMachine
from .workflows import issue as workflow

_machine = StateMachine(workflow)

# Re-export for external use
transition = _machine.transition
pending = workflow.pending
status_colors = workflow.status_colors
