"""State machine: transitions and handlers (re-exports from workflow module)."""
import os
import importlib
from .machine import StateMachine

workflow_name = os.environ.get("ISSUE_WORKFLOW", "issue")
workflow = importlib.import_module(f".workflows.{workflow_name}", __package__)

_machine = StateMachine(workflow)

# Re-export for external use
transition = _machine.transition
pending = getattr(workflow, 'pending', None)
status_colors = workflow.status_colors
