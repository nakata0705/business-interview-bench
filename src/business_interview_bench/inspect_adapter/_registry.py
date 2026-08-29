"""Inspect package component registration entry point."""

# Importing this module is the one intentional side effect of the
# ``business_interview_bench`` Inspect entry point: decorators register all
# packaged components before CLI name resolution.
# pyright: reportMissingImports=false

from .scorer import primary_scorer, reconstruction_pass_metric
from .solver import seed9004_replay_solver
from .task import seed9004_replay

__all__ = [
    "primary_scorer",
    "reconstruction_pass_metric",
    "seed9004_replay",
    "seed9004_replay_solver",
]
