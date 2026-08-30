"""Inspect Store schema for the private seed 9004 replay payload."""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` remains the authoritative adapter check.
# pyright: reportMissingImports=false

from __future__ import annotations

from typing import Any

from inspect_ai.util import StoreModel
from pydantic import Field

from business_interview.evaluation import KnowledgeCoverageView
from business_interview.models import (
    AgentGraph,
    BusinessProcessGraph,
    InterviewEvaluationContext,
    validate_canonical_graph,
)
from business_interview.replay_data import load_seed9004_payload


class BusinessInterviewReplayStore(StoreModel):
    """JSON-compatible, sample-scoped inputs needed by the primary scorer.

    Domain models intentionally do not live in the Inspect store. The solver
    writes canonical JSON-compatible dictionaries and the scorer validates
    them back into the standalone domain models before evaluation.
    """

    agent: dict[str, Any] = Field(default_factory=dict)
    truth: dict[str, Any] = Field(default_factory=dict)
    evaluation_context: dict[str, Any] = Field(default_factory=dict)
    knowledge_coverage: dict[str, Any] = Field(default_factory=dict)


def _load_seed9004_scoring_inputs() -> dict[str, Any]:
    """Validate and return the four packaged inputs required by scoring."""
    agent = AgentGraph.model_validate(load_seed9004_payload("agent.json"))
    truth = BusinessProcessGraph.model_validate(load_seed9004_payload("truth.json"))
    validate_canonical_graph(truth)
    context = InterviewEvaluationContext.model_validate(
        load_seed9004_payload("evaluation_context.json")
    )
    knowledge_coverage = KnowledgeCoverageView.model_validate(
        load_seed9004_payload("knowledge_coverage.json")
    )
    return {
        "agent": agent.model_dump(mode="json"),
        "truth": truth.model_dump(mode="json"),
        "evaluation_context": context.model_dump(mode="json"),
        "knowledge_coverage": knowledge_coverage.model_dump(mode="json"),
    }


__all__ = ["BusinessInterviewReplayStore"]
