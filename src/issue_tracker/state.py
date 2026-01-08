"""State machine: transitions and handlers (re-exports from workflow module)."""
import os
from .machine import StateMachine

workflow_name = os.environ.get("ISSUE_WORKFLOW", "issue")
if workflow_name == "kanban":
    from .workflows import kanban as workflow
else:
    from .workflows import issue as workflow

_machine = StateMachine(workflow)

# Re-export for external use
transition = _machine.transition
pending = getattr(workflow, 'pending', None)
status_colors = workflow.status_colors
