"""Tau2-free graph evaluation for canonical business interview graphs."""

# The workspace-level auxiliary Pyright runner can miss freshly added sibling
# modules; project-level ``uv run pyright`` remains the authoritative check.
# pyright: reportMissingImports=false

from .evaluator import evaluate_graph
from .result import GraphEvaluation

__all__ = ["GraphEvaluation", "evaluate_graph"]
