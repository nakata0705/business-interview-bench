"""Build the seed 9004 Truth-addressed knowledge coverage fixture.

The source checkout is consulted only during generation. A short subprocess
loads the persisted source ``StakeholderKnowledge`` object, projects the
coverage-relevant states to Truth IDs, and emits no stakeholder-local IDs,
private mappings, descriptions, terms, annotations, or sidecar data.
"""

from __future__ import annotations

import argparse
import json
import subprocess
from collections.abc import Sequence
from pathlib import Path
from typing import Any

from build_seed9004_fixture import (
    _read_json,
    _safe_output_root,
    _source_context,
    _stable_json,
)

from business_interview.evaluation import KnowledgeCoverageView
from business_interview.models import (
    BusinessProcessGraph,
    business_edge_ids,
    business_node_ids,
)

SOURCE_PRIVATE_ARTIFACT = (
    "artifacts/business_interview_real_llm/run_00_seed9004.private.json"
)
TRUTH_FIXTURE = "src/business_interview/replay_data/seed9004/truth.json"
CONTEXT_FILE = "knowledge_coverage.json"

_SOURCE_EXTRACT_CODE = r"""
import json
import sys
from pathlib import Path

from tau2.domains.business_interview.graph import DontKnowType
from tau2.domains.business_interview.knowledge import StakeholderKnowledge

private = json.loads(Path(sys.argv[1]).read_text(encoding="utf-8"))
knowledge = StakeholderKnowledge.model_validate(private["knowledge"])
graph = knowledge.graph


def scalar(value):
    return "dont_know" if isinstance(value, DontKnowType) else "known"


def list_slot(value):
    if isinstance(value, DontKnowType):
        return {"state": "dont_know", "truth_concept_ids": []}
    if value is None:
        return {"state": "known_absent", "truth_concept_ids": []}
    if isinstance(value, list):
        return {
            "state": "known_values",
            "truth_concept_ids": sorted(
                graph.concepts[ref.concept_id].truth_concept_id for ref in value
            ),
        }
    raise TypeError(f"unexpected knowledge list slot: {type(value).__name__}")


def node_payload(truth_node_id, node):
    return {
        "truth_node_id": truth_node_id,
        "activity": scalar(node.activity),
        "actor": scalar(node.actor),
        "system": scalar(node.system),
        "reads": list_slot(node.reads),
        "writes": list_slot(node.writes),
        "rationale": scalar(node.necessity_rationale),
    }


def edge_payload(truth_edge_id, edge):
    return {
        "truth_edge_id": truth_edge_id,
        "condition": scalar(edge.condition),
    }

nodes = {
    truth_id: node_payload(truth_id, graph.nodes[local_id])
    for local_id, truth_id in sorted(
        graph.node_truth_ids.items(), key=lambda item: (item[1], item[0])
    )
}
edges = {
    truth_id: edge_payload(truth_id, graph.edges[local_id])
    for local_id, truth_id in sorted(
        graph.edge_truth_ids.items(), key=lambda item: (item[1], item[0])
    )
}
print(json.dumps({"nodes_by_truth_id": nodes, "edges_by_truth_id": edges}, sort_keys=True))
"""


def _extract_from_source(private_path: Path, source_root: Path) -> dict[str, Any]:
    result = subprocess.run(
        [
            "uv",
            "run",
            "python",
            "-c",
            _SOURCE_EXTRACT_CODE,
            str(private_path.resolve()),
        ],
        cwd=source_root,
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr[-4000:] or result.stdout[-4000:]
        raise RuntimeError(f"source knowledge extraction failed: {detail}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            "source knowledge extraction did not return JSON: "
            f"stdout={result.stdout[-2000:]!r}, stderr={result.stderr[-2000:]!r}"
        ) from exc
    if not isinstance(value, dict):
        raise ValueError("source knowledge extraction result must be an object")
    return value


def build_fixture(*, source_root: Path, output_root: Path) -> Path:
    project_root = Path(__file__).resolve().parents[2]
    source_root = source_root.resolve()
    metadata = _read_json(project_root / "migration" / "source.json")
    expected_source_root = Path(str(metadata["source_repository_path"])).resolve()
    if source_root != expected_source_root:
        raise ValueError(
            "--source-root must match migration/source.json source_repository_path"
        )
    _source_context(project_root, source_root)

    output_root = _safe_output_root(project_root, output_root)
    output_path = (output_root / CONTEXT_FILE).resolve()
    if output_path.parent != output_root:
        raise ValueError("fixture output must stay inside the output directory")

    private_path = source_root / SOURCE_PRIVATE_ARTIFACT
    if not private_path.is_file():
        raise FileNotFoundError(
            f"required private artifact is missing: {SOURCE_PRIVATE_ARTIFACT}"
        )
    source_payload = _extract_from_source(private_path, source_root)

    truth = BusinessProcessGraph.model_validate_json(
        (project_root / TRUTH_FIXTURE).read_text(encoding="utf-8")
    )
    source_payload["nodes_by_truth_id"] = {
        truth_id: item
        for truth_id, item in source_payload.get("nodes_by_truth_id", {}).items()
        if truth_id in set(business_node_ids(truth))
    }
    source_payload["edges_by_truth_id"] = {
        truth_id: item
        for truth_id, item in source_payload.get("edges_by_truth_id", {}).items()
        if truth_id in set(business_edge_ids(truth))
    }
    view = KnowledgeCoverageView.model_validate(source_payload)
    output_path.parent.mkdir(parents=True, exist_ok=True)
    output_path.write_text(_stable_json(view.model_dump(mode="json")), encoding="utf-8")
    return output_path


def _default_source_root() -> Path:
    return Path(__file__).resolve().parents[3] / "tau2-bench"


def _default_output_root() -> Path:
    return (
        Path(__file__).resolve().parents[2]
        / "src"
        / "business_interview"
        / "replay_data"
        / "seed9004"
    )


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--source-root", type=Path, default=_default_source_root())
    parser.add_argument("--output", type=Path, default=_default_output_root())
    args = parser.parse_args(argv)
    try:
        output = build_fixture(
            source_root=args.source_root,
            output_root=args.output,
        )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"seed9004 knowledge coverage generation failed: {exc}")
        return 1
    print(f"wrote seed9004 knowledge coverage fixture to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
