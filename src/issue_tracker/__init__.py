"""
Issue tracking inspired by Google Critique.
States: draft -> review -> approved -> done/abandoned
The attention set answers: whose turn is it?
"""
from .cli import main

__all__ = ["main"]
