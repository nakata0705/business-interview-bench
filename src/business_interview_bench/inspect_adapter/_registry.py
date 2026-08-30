"""Inspect package component registration entry point."""

# Importing this module is the one intentional side effect of the
# ``business_interview_bench`` Inspect entry point: decorators register all
# packaged components before CLI name resolution.
# pyright: reportMissingImports=false

from .multiturn import phase13_interview
from .scorer import primary_scorer
from .task import seed9004_replay

__all__ = ["phase13_interview", "primary_scorer", "seed9004_replay"]
