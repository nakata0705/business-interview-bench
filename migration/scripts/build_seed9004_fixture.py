"""Build the curated, tau2-free seed 9004 parity fixture.

This is migration tooling, not runtime code.  It reads the legacy split
artifact from the sibling ``tau2-bench`` checkout, preserves the saved final
Agent state, obtains Truth from the saved deterministic Truth payload, and
runs the source evaluator offline to capture a primary oracle snapshot.

The source checkout is intentionally required only while generating the
fixture.  The checked-in JSON files load through ``business_interview.models``
without importing tau2 or requiring the source checkout.
"""

from __future__ import annotations

import argparse
import hashlib
import json
import subprocess
import sys
from collections.abc import Mapping, Sequence
from datetime import datetime, timezone
from pathlib import Path
from typing import Any

from business_interview.models import (
    AbsentType,
    AgentConcept,
    AgentEdge,
    AgentGraph,
    AgentNode,
    BusinessProcessGraph,
    ConceptRef,
    DontKnowType,
    EvidenceRef,
    TruthConcept,
    TruthEdge,
    TruthNode,
    UnsetType,
    canonicalize_truth_graph,
    validate_canonical_graph,
)

PHASE2_CHECKPOINT = "9bd4713647ba7eff2df4ebb6181743351c257ee2"
SOURCE_ARTIFACTS = (
    (
        "artifacts/business_interview_real_llm/run_00_seed9004.json",
        "legacy public run artifact",
    ),
    (
        "artifacts/business_interview_real_llm/run_00_seed9004.private.json",
        "legacy evaluator-private sidecar used only for oracle recomputation",
    ),
    (
        "artifacts/business_interview_real_llm/run_00_seed9004.diagnostics.json",
        "legacy diagnostics artifact retained for provenance only",
    ),
)
SOURCE_ORACLE_FILES = (
    "src/tau2/domains/business_interview/scenario.py",
    "src/tau2/domains/business_interview/graph.py",
    "src/tau2/domains/business_interview/artifact_provenance.py",
    "src/tau2/domains/business_interview/evaluation.py",
    "src/tau2/domains/business_interview/comparison.py",
)
FIXTURE_SCHEMA_VERSION = "business_interview.phase3.normalized_fixture.v1"
EXPECTED_SCHEMA_VERSION = "business_interview.phase3.primary_oracle.v1"


_SOURCE_RECOMPUTE_CODE = r"""
import json
import sys
from pathlib import Path

from tau2.domains.business_interview.evaluation import (
    EvaluationSpec,
    PrimaryEvaluationResult,
    evaluate,
)
from tau2.domains.business_interview.graph import (
    AbsentType,
    AgentConcept,
    AgentGraph,
    ConceptRef,
    DontKnowType,
    Edge,
    EvidenceRef,
    InterviewDB,
    Node,
    Observation,
    UnsetType,
)
from tau2.domains.business_interview.knowledge import StakeholderKnowledge
from tau2.domains.business_interview.scenario import quotation_truth


def evidence(value):
    return [
        EvidenceRef(
            observation_id=item["observation_id"],
            quote=item.get("quote"),
            occurrence=item.get("occurrence", 0),
        )
        for item in (value or [])
    ]


def ref(value):
    return ConceptRef(
        concept_id=value["concept_id"],
        confidence=value.get("confidence", 1.0),
        evidence=evidence(value.get("evidence")),
    )


def slot(value, *, list_slot=False):
    if isinstance(value, list):
        if not list_slot:
            raise ValueError("list in scalar Agent slot")
        return [ref(item) for item in value]
    state = value.get("state")
    if state == "value":
        return ref(value)
    if state == "unset":
        return UnsetType()
    if state == "absent":
        return AbsentType(evidence=evidence(value.get("evidence")))
    if state == "dont_know":
        return DontKnowType(evidence=evidence(value.get("evidence")))
    raise ValueError(f"unknown normalized Agent slot state: {value!r}")


def agent_graph(value):
    concepts = {
        key: AgentConcept(
            id=item["id"],
            kind=item["kind"],
            display_label=item["display_label"],
            description=item.get("description", ""),
            mentions=evidence(item.get("mentions")),
        )
        for key, item in value["concepts"].items()
    }
    nodes = {
        key: Node(
            id=item["id"],
            activity=slot(item["activity"]),
            actor=slot(item["actor"]),
            system=slot(item["system"]),
            reads=slot(item["reads"], list_slot=True),
            writes=slot(item["writes"], list_slot=True),
            necessity_rationale=slot(item["necessity_rationale"]),
        )
        for key, item in value["nodes"].items()
    }
    edges = {
        key: Edge(
            id=item["id"],
            from_node=item["from_node"],
            to_node=item["to_node"],
            condition=slot(item["condition"]),
            evidence=evidence(item.get("evidence")),
        )
        for key, item in value["edges"].items()
    }
    starts = list(value["start_node_ids"])
    return AgentGraph(
        id=value["id"],
        name=value.get("name", ""),
        concepts=concepts,
        nodes=nodes,
        edges=edges,
        start_node_id=starts[0] if len(starts) == 1 else None,
        start_node_ids=starts,
        end_node_ids=list(value["end_node_ids"]),
    )


public_path = Path(sys.argv[1])
private_path = Path(sys.argv[2]) if sys.argv[2] else None
agent = agent_graph(json.load(sys.stdin))
public = json.loads(public_path.read_text(encoding="utf-8"))
private = (
    json.loads(private_path.read_text(encoding="utf-8"))
    if private_path is not None
    else None
)
knowledge = (
    StakeholderKnowledge.model_validate(private["knowledge"])
    if private is not None and private.get("knowledge") is not None
    else None
)
db = InterviewDB(
    graph=agent,
    messages=public["db_messages_ledger"],
    observations=[Observation.model_validate(item) for item in public["observations"]],
    interview_complete=public["interview_complete"],
)
result = evaluate(db, knowledge, EvaluationSpec(), truth=quotation_truth())
dump = result.model_dump(mode="json")
fields = list(PrimaryEvaluationResult.model_fields)
print(json.dumps({"field_names": fields, "fields": {key: dump[key] for key in fields}}, sort_keys=True))
"""


def _mapping(value: object, path: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise ValueError(f"{path} must be an object")
    return value


def _required(mapping: Mapping[str, Any], key: str, path: str) -> Any:
    if key not in mapping:
        raise ValueError(f"{path}.{key} is required")
    return mapping[key]


def _string(value: object, path: str) -> str:
    if not isinstance(value, str) or not value:
        raise ValueError(f"{path} must be a non-empty string")
    return value


def _description(value: object, path: str) -> str:
    if not isinstance(value, str):
        raise ValueError(f"{path} must be a string")
    return value


def _string_list(value: object, path: str) -> list[str]:
    if not isinstance(value, list) or any(not isinstance(item, str) for item in value):
        raise ValueError(f"{path} must be a list of strings")
    return list(value)


def _evidence(value: object, path: str) -> list[EvidenceRef]:
    if value is None:
        return []
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list")
    result: list[EvidenceRef] = []
    for index, raw_item in enumerate(value):
        item = _mapping(raw_item, f"{path}[{index}]")
        occurrence = item.get("occurrence", 0)
        if not isinstance(occurrence, int) or isinstance(occurrence, bool):
            raise ValueError(f"{path}[{index}].occurrence must be an integer")
        quote = item.get("quote")
        if quote is not None and not isinstance(quote, str):
            raise ValueError(f"{path}[{index}].quote must be a string or null")
        result.append(
            EvidenceRef(
                observation_id=_string(
                    _required(item, "observation_id", f"{path}[{index}]"),
                    f"{path}[{index}].observation_id",
                ),
                quote=quote,
                occurrence=occurrence,
            )
        )
    return result


def _ref(value: object, path: str) -> ConceptRef:
    item = _mapping(value, path)
    state = item.get("state")
    if state is not None and state != "value":
        raise ValueError(f"{path} is not a Truth value reference")
    return ConceptRef(
        concept_id=_string(_required(item, "concept_id", path), f"{path}.concept_id"),
        confidence=item.get("confidence", 1.0),
        evidence=_evidence(item.get("evidence"), f"{path}.evidence"),
    )


def _truth_slot(value: object, path: str) -> ConceptRef | None:
    return None if value is None else _ref(value, path)


def _truth_list_slot(value: object, path: str) -> list[ConceptRef] | None:
    if value is None:
        return None
    if not isinstance(value, list):
        raise ValueError(f"{path} must be a list or null")
    return [_ref(item, f"{path}[{index}]") for index, item in enumerate(value)]


def _normalize_truth(public: Mapping[str, Any]) -> BusinessProcessGraph:
    raw_graph = _mapping(
        _required(public, "truth_graph", "public"), "public.truth_graph"
    )
    raw_concepts = _mapping(
        _required(raw_graph, "concepts", "public.truth_graph"),
        "public.truth_graph.concepts",
    )
    concepts: dict[str, TruthConcept] = {}
    for key in sorted(raw_concepts):
        item = _mapping(raw_concepts[key], f"public.truth_graph.concepts.{key}")
        concept_id = _string(
            _required(item, "id", f"...concepts.{key}"), f"...concepts.{key}.id"
        )
        if concept_id != key:
            raise ValueError(
                f"Truth concept key/id mismatch: {key!r} != {concept_id!r}"
            )
        terms = item.get("canonical_terms", [])
        concepts[key] = TruthConcept(
            id=concept_id,
            kind=_string(
                _required(item, "kind", f"...concepts.{key}"), f"...concepts.{key}.kind"
            ),  # type: ignore[arg-type]
            description=_description(
                item.get("description", ""), f"...concepts.{key}.description"
            ),
            canonical_terms=_string_list(terms, f"...concepts.{key}.canonical_terms"),
        )

    raw_nodes = _mapping(
        _required(raw_graph, "nodes", "public.truth_graph"),
        "public.truth_graph.nodes",
    )
    nodes: dict[str, TruthNode] = {}
    for key in sorted(raw_nodes):
        item = _mapping(raw_nodes[key], f"public.truth_graph.nodes.{key}")
        node_id = _string(
            _required(item, "id", f"...nodes.{key}"), f"...nodes.{key}.id"
        )
        if node_id != key:
            raise ValueError(f"Truth node key/id mismatch: {key!r} != {node_id!r}")
        if (
            item.get("structural")
            or item.get("structural_role")
            or item.get("protected")
        ):
            raise ValueError(
                "seed 9004 Truth payload unexpectedly contains structural metadata"
            )
        nodes[key] = TruthNode(
            id=node_id,
            activity=_truth_slot(item.get("activity"), f"...nodes.{key}.activity"),
            actor=_truth_slot(item.get("actor"), f"...nodes.{key}.actor"),
            system=_truth_slot(item.get("system"), f"...nodes.{key}.system"),
            reads=_truth_list_slot(item.get("reads"), f"...nodes.{key}.reads"),
            writes=_truth_list_slot(item.get("writes"), f"...nodes.{key}.writes"),
            necessity_rationale=_truth_slot(
                item.get("necessity_rationale"), f"...nodes.{key}.necessity_rationale"
            ),
        )

    raw_edges = _mapping(
        _required(raw_graph, "edges", "public.truth_graph"),
        "public.truth_graph.edges",
    )
    edges: dict[str, TruthEdge] = {}
    for key in sorted(raw_edges):
        item = _mapping(raw_edges[key], f"public.truth_graph.edges.{key}")
        edge_id = _string(
            _required(item, "id", f"...edges.{key}"), f"...edges.{key}.id"
        )
        if edge_id != key:
            raise ValueError(f"Truth edge key/id mismatch: {key!r} != {edge_id!r}")
        edges[key] = TruthEdge(
            id=edge_id,
            from_node=_string(item.get("from_node"), f"...edges.{key}.from_node"),
            to_node=_string(item.get("to_node"), f"...edges.{key}.to_node"),
            condition=_truth_slot(item.get("condition"), f"...edges.{key}.condition"),
        )

    start = _string(
        _required(raw_graph, "start_node_id", "public.truth_graph"),
        "public.truth_graph.start_node_id",
    )
    ends = _string_list(
        _required(raw_graph, "end_node_ids", "public.truth_graph"),
        "public.truth_graph.end_node_ids",
    )
    if start not in nodes or any(node_id not in nodes for node_id in ends):
        raise ValueError(
            "Truth endpoint references are not present in the legacy nodes"
        )
    if raw_graph.get("terminology_agreements"):
        raise ValueError("non-empty Truth terminology agreements are not representable")

    legacy = BusinessProcessGraph(
        id=_string(
            _required(raw_graph, "id", "public.truth_graph"), "public.truth_graph.id"
        ),
        name=_description(raw_graph.get("name", ""), "public.truth_graph.name"),
        concepts=concepts,
        nodes=nodes,
        edges=edges,
    )
    canonical = canonicalize_truth_graph(
        legacy,
        entry_node_ids=[start],
        exit_node_ids=ends,
    )
    validate_canonical_graph(canonical)
    return canonical


def _agent_ref(value: object, path: str) -> ConceptRef:
    item = _mapping(value, path)
    allowed = {"state", "concept_id", "confidence", "evidence"}
    unknown = set(item) - allowed
    if unknown:
        raise ValueError(
            f"{path} contains unsupported reference fields: {sorted(unknown)!r}"
        )
    state = item.get("state")
    if state is not None and state != "value":
        raise ValueError(f"{path} has invalid value state: {state!r}")
    return ConceptRef(
        concept_id=_string(_required(item, "concept_id", path), f"{path}.concept_id"),
        confidence=item.get("confidence", 1.0),
        evidence=_evidence(item.get("evidence"), f"{path}.evidence"),
    )


def _agent_slot(value: object, path: str, *, list_slot: bool = False) -> Any:
    if isinstance(value, list):
        if not list_slot:
            raise ValueError(f"{path} is a scalar slot but contains a list")
        return [
            _agent_ref(item, f"{path}[{index}]") for index, item in enumerate(value)
        ]

    item = _mapping(value, path)
    marker_keys = ("unset", "absent", "dont_know")
    state = item.get("state")
    marked = [
        key for key in marker_keys if isinstance(item.get(key), bool) and item.get(key)
    ]
    if "concept_id" in item:
        if marked or state not in (None, "value"):
            raise ValueError(f"{path} mixes a concept reference with a marker")
        return _agent_ref(item, path)
    if state is not None:
        if state not in {"unset", "absent", "dont_know"}:
            raise ValueError(f"{path} has unknown normalized state {state!r}")
        if marked and marked != [state]:
            raise ValueError(
                f"{path} contains conflicting legacy and normalized states"
            )
    elif len(marked) != 1:
        raise ValueError(f"{path} must contain exactly one Agent epistemic state")

    selected = state if state is not None else marked[0]
    if selected == "unset":
        allowed = {"state", "unset", "evidence"}
        if set(item) - allowed:
            raise ValueError(f"{path} contains unsupported UNSET fields")
        if item.get("evidence"):
            raise ValueError(f"{path} has evidence that target UNSET cannot preserve")
        return UnsetType()
    if selected == "absent":
        allowed = {"state", "absent", "evidence"}
        if set(item) - allowed:
            raise ValueError(f"{path} contains unsupported ABSENT fields")
        return AbsentType(evidence=_evidence(item.get("evidence"), f"{path}.evidence"))
    if selected == "dont_know":
        allowed = {"state", "dont_know", "evidence"}
        if set(item) - allowed:
            raise ValueError(f"{path} contains unsupported DONT_KNOW fields")
        return DontKnowType(
            evidence=_evidence(item.get("evidence"), f"{path}.evidence")
        )
    raise ValueError(f"{path} could not be normalized")


def _normalize_agent(public: Mapping[str, Any]) -> AgentGraph:
    raw_graph = _mapping(
        _required(public, "final_graph", "public"), "public.final_graph"
    )
    raw_concepts = _mapping(
        _required(raw_graph, "concepts", "public.final_graph"),
        "public.final_graph.concepts",
    )
    concepts: dict[str, AgentConcept] = {}
    for key in sorted(raw_concepts):
        item = _mapping(raw_concepts[key], f"public.final_graph.concepts.{key}")
        concept_id = _string(
            _required(item, "id", f"...concepts.{key}"), f"...concepts.{key}.id"
        )
        if concept_id != key:
            raise ValueError(
                f"Agent concept key/id mismatch: {key!r} != {concept_id!r}"
            )
        concepts[key] = AgentConcept(
            id=concept_id,
            kind=_string(
                _required(item, "kind", f"...concepts.{key}"), f"...concepts.{key}.kind"
            ),  # type: ignore[arg-type]
            display_label=_string(
                _required(item, "display_label", f"...concepts.{key}"),
                f"...concepts.{key}.display_label",
            ),
            description=_description(
                item.get("description", ""), f"...concepts.{key}.description"
            ),
            mentions=_evidence(item.get("mentions"), f"...concepts.{key}.mentions"),
        )

    raw_nodes = _mapping(
        _required(raw_graph, "nodes", "public.final_graph"),
        "public.final_graph.nodes",
    )
    nodes: dict[str, AgentNode] = {}
    for key in sorted(raw_nodes):
        item = _mapping(raw_nodes[key], f"public.final_graph.nodes.{key}")
        node_id = _string(
            _required(item, "id", f"...nodes.{key}"), f"...nodes.{key}.id"
        )
        if node_id != key:
            raise ValueError(f"Agent node key/id mismatch: {key!r} != {node_id!r}")
        nodes[key] = AgentNode(
            id=node_id,
            activity=_agent_slot(item.get("activity"), f"...nodes.{key}.activity"),
            actor=_agent_slot(item.get("actor"), f"...nodes.{key}.actor"),
            system=_agent_slot(item.get("system"), f"...nodes.{key}.system"),
            reads=_agent_slot(
                item.get("reads"), f"...nodes.{key}.reads", list_slot=True
            ),
            writes=_agent_slot(
                item.get("writes"), f"...nodes.{key}.writes", list_slot=True
            ),
            necessity_rationale=_agent_slot(
                item.get("necessity_rationale"), f"...nodes.{key}.necessity_rationale"
            ),
        )

    raw_edges = _mapping(
        _required(raw_graph, "edges", "public.final_graph"),
        "public.final_graph.edges",
    )
    edges: dict[str, AgentEdge] = {}
    for key in sorted(raw_edges):
        item = _mapping(raw_edges[key], f"public.final_graph.edges.{key}")
        edge_id = _string(
            _required(item, "id", f"...edges.{key}"), f"...edges.{key}.id"
        )
        if edge_id != key:
            raise ValueError(f"Agent edge key/id mismatch: {key!r} != {edge_id!r}")
        edges[key] = AgentEdge(
            id=edge_id,
            from_node=_string(item.get("from_node"), f"...edges.{key}.from_node"),
            to_node=_string(item.get("to_node"), f"...edges.{key}.to_node"),
            condition=_agent_slot(item.get("condition"), f"...edges.{key}.condition"),
            evidence=_evidence(item.get("evidence"), f"...edges.{key}.evidence"),
        )

    if raw_graph.get("terminology_agreements"):
        raise ValueError("non-empty Agent terminology agreements are not representable")
    if "start_node_ids" in raw_graph:
        starts = _string_list(
            raw_graph["start_node_ids"], "public.final_graph.start_node_ids"
        )
    else:
        starts = [
            _string(
                _required(raw_graph, "start_node_id", "public.final_graph"),
                "public.final_graph.start_node_id",
            )
        ]
    ends = _string_list(
        _required(raw_graph, "end_node_ids", "public.final_graph"),
        "public.final_graph.end_node_ids",
    )
    graph = AgentGraph(
        id=_string(
            _required(raw_graph, "id", "public.final_graph"), "public.final_graph.id"
        ),
        name=_description(raw_graph.get("name", ""), "public.final_graph.name"),
        concepts=concepts,
        nodes=nodes,
        edges=edges,
        start_node_ids=starts,
        end_node_ids=ends,
    )
    if not graph.is_valid:
        raise ValueError(
            "normalized AgentGraph is invalid: " + "; ".join(graph.structure_errors())
        )
    return graph


def _read_json(path: Path) -> Mapping[str, Any]:
    try:
        value = json.loads(path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as exc:
        raise ValueError(f"cannot read JSON {path}: {exc}") from exc
    return _mapping(value, str(path))


def _git(source_root: Path, *args: str) -> str:
    result = subprocess.run(
        ["git", "-C", str(source_root), *args],
        check=True,
        capture_output=True,
        text=True,
    )
    return result.stdout.strip()


def _sha256(path: Path) -> str:
    return hashlib.sha256(path.read_bytes()).hexdigest()


def _git_blob_sha(source_root: Path, commit: str, relative_path: str) -> str:
    return _git(source_root, "rev-parse", f"{commit}:{relative_path}")


def _source_context(project_root: Path, source_root: Path) -> dict[str, Any]:
    source_metadata = _read_json(project_root / "migration" / "source.json")
    head = _git(source_root, "rev-parse", "HEAD")
    branch = _git(source_root, "branch", "--show-current")
    status = _git(source_root, "status", "--porcelain")
    expected_head = source_metadata.get("source_head_sha")
    if head != expected_head:
        raise ValueError(
            f"source HEAD {head} does not match migration/source.json {expected_head}"
        )
    if branch != source_metadata.get("source_branch"):
        raise ValueError(f"source branch is {branch!r}, expected business-interview")
    if status:
        raise ValueError(f"source working tree is not clean:\n{status}")
    artifacts: list[dict[str, str]] = []
    for relative_path, role in SOURCE_ARTIFACTS:
        path = source_root / relative_path
        if not path.is_file():
            continue
        artifacts.append(
            {
                "path": relative_path,
                "role": role,
                "git_blob_sha": _git_blob_sha(source_root, head, relative_path),
                "sha256": _sha256(path),
            }
        )
    oracle_sources: list[dict[str, str]] = []
    for relative_path in SOURCE_ORACLE_FILES:
        path = source_root / relative_path
        if path.is_file():
            oracle_sources.append(
                {
                    "path": relative_path,
                    "git_blob_sha": _git_blob_sha(source_root, head, relative_path),
                    "sha256": _sha256(path),
                }
            )
    return {
        "repository": source_metadata["source_repository"],
        "branch": branch,
        "commit_sha": head,
        "working_tree_clean": True,
        "artifacts": artifacts,
        "oracle_sources": oracle_sources,
    }


def _safe_output_root(project_root: Path, output_root: Path) -> Path:
    project = project_root.resolve()
    output = output_root.resolve()
    try:
        output.relative_to(project)
    except ValueError as exc:
        raise ValueError("fixture output must stay inside the target project") from exc
    return output


def _source_artifact_path(source_root: Path, relative_path: str) -> Path | None:
    path = source_root / relative_path
    return path if path.is_file() else None


def _recompute_primary(
    source_root: Path,
    public_path: Path,
    private_path: Path | None,
    agent: AgentGraph,
) -> Mapping[str, Any]:
    command = [
        "uv",
        "run",
        "python",
        "-c",
        _SOURCE_RECOMPUTE_CODE,
        str(public_path.resolve()),
        str(private_path.resolve()) if private_path is not None else "",
    ]
    result = subprocess.run(
        command,
        cwd=source_root,
        input=json.dumps(
            agent.model_dump(mode="json"), ensure_ascii=False, sort_keys=True
        ),
        capture_output=True,
        text=True,
        timeout=300,
        check=False,
    )
    if result.returncode != 0:
        detail = result.stderr[-4000:] or result.stdout[-4000:]
        raise RuntimeError(f"source evaluator recomputation failed: {detail}")
    try:
        value = json.loads(result.stdout)
    except json.JSONDecodeError as exc:
        raise RuntimeError(
            f"source evaluator did not return JSON; stdout={result.stdout[-2000:]!r}; "
            f"stderr={result.stderr[-2000:]!r}"
        ) from exc
    return _mapping(value, "source evaluator result")


def _expected_payload(
    public: Mapping[str, Any], recomputed: Mapping[str, Any]
) -> dict[str, Any]:
    field_names = _string_list(
        _required(recomputed, "field_names", "source evaluator result"),
        "source evaluator result.field_names",
    )
    recomputed_fields = _mapping(
        _required(recomputed, "fields", "source evaluator result"),
        "source evaluator result.fields",
    )
    stored = _mapping(
        _required(public, "evaluator_metrics", "public"),
        "public.evaluator_metrics",
    )
    missing = [
        field
        for field in field_names
        if field not in stored or field not in recomputed_fields
    ]
    if missing:
        raise ValueError(
            f"primary evaluator fields missing from stored/recomputed result: {missing}"
        )
    stored_fields = {field: stored[field] for field in field_names}
    current_fields = {field: recomputed_fields[field] for field in field_names}
    differences = [
        {
            "field": field,
            "stored": stored_fields[field],
            "recomputed": current_fields[field],
        }
        for field in field_names
        if stored_fields[field] != current_fields[field]
    ]
    return {
        "schema_version": EXPECTED_SCHEMA_VERSION,
        "seed": 9004,
        "task_id": "quotation_workflow_1",
        "scope": "primary_agent_to_truth",
        "oracle": {
            "kind": "recomputed_primary",
            "fields": current_fields,
        },
        "legacy_stored_comparison": {
            "source_field": "run_00_seed9004.json:evaluator_metrics",
            "fields": stored_fields,
            "status": "matched" if not differences else "different",
            "differences": differences,
            "adopted": "recomputed_primary",
        },
        "field_sources": {
            field: {
                "legacy_stored": f"run_00_seed9004.json:evaluator_metrics.{field}",
                "recomputed": f"offline_source_primary_result.{field}",
            }
            for field in field_names
        },
    }


def _stable_json(value: Any) -> str:
    return (
        json.dumps(
            value,
            ensure_ascii=False,
            indent=2,
            sort_keys=True,
            allow_nan=False,
        )
        + "\n"
    )


def _write_json(path: Path, value: Any) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(_stable_json(value), encoding="utf-8")


def _deterministic_file_digest(path: Path) -> str:
    return _sha256(path)


def _provenance(
    source: Mapping[str, Any],
    fixture_root: Path,
    generated_at: str,
) -> dict[str, Any]:
    artifact_digests = {
        name: _deterministic_file_digest(fixture_root / name)
        for name in ("truth.json", "agent.json", "expected.json")
    }
    return {
        "schema_version": FIXTURE_SCHEMA_VERSION,
        "seed": 9004,
        "task_id": "quotation_workflow_1",
        "source_repository": source["repository"],
        "source_branch": source["branch"],
        "source_commit_sha": source["commit_sha"],
        "source_artifact_paths": [item["path"] for item in source["artifacts"]],
        "source_artifact_sha256": {
            item["path"]: item["sha256"] for item in source["artifacts"]
        },
        "generation_method": "migration/scripts/build_seed9004_fixture.py",
        "fixture": {
            "seed": 9004,
            "task_id": "quotation_workflow_1",
            "files": {
                "truth": "truth.json",
                "agent": "agent.json",
                "expected": "expected.json",
                "provenance": "provenance.json",
            },
            "deterministic_file_sha256": artifact_digests,
        },
        "source": source,
        "source_oracle": {
            "truth_constructor": {
                "path": "src/tau2/domains/business_interview/scenario.py",
                "symbol": "quotation_truth",
                "meaning": "the artifact truth_graph is the equivalent deterministic legacy payload; canonical boundary elements are rebuilt by the target model contract",
            },
            "evaluator_entry_point": "tau2.domains.business_interview.evaluation.evaluate",
            "result_type": "PrimaryEvaluationResult",
            "source_package_version": "1.0.1",
            "execution": "offline deterministic recomputation; no LLM, provider, network, or simulator call",
            "comparison_scope": "primary Agent-to-Truth fields only; stakeholder reference scores and diagnostics are excluded",
        },
        "generation": {
            "method": "migration/scripts/build_seed9004_fixture.py",
            "input_selection": "only existing seed 9004 public/private/diagnostics artifacts are considered; the private sidecar is read for source oracle recomputation and never copied",
            "generated_at": generated_at,
            "target_phase2_checkpoint": PHASE2_CHECKPOINT,
        },
        "generated_fields": {
            "truth.json": {
                "source": "run_00_seed9004.json:truth_graph",
                "oracle_semantics": "quotation_truth() from scenario.py",
                "normalization": [
                    "copy Truth concept/node/edge semantic values mechanically",
                    "drop legacy serializer-only fields such as is_valid, validation_errors, terminology_agreements, display_label, and mentions",
                    "use legacy start_node_id/end_node_ids as explicit entry/exit inputs to canonicalize_truth_graph()",
                    "add only target-owned protected SOURCE/SINK nodes and unconditional boundary edges",
                ],
            },
            "agent.json": {
                "source": "run_00_seed9004.json:final_graph",
                "normalization": [
                    "copy the episode-complete saved final Agent graph, not the transcript",
                    "map legacy Node/Edge shape to AgentNode/AgentEdge mechanically",
                    "map unset/absent/dont_know marker objects to explicit target four-state values without collapsing them",
                    "preserve concept references, confidence, evidence, endpoints, and evidence quotes",
                ],
            },
            "expected.json": {
                "recomputed_source": "offline source evaluator PrimaryEvaluationResult fields",
                "legacy_comparison": "run_00_seed9004.json:evaluator_metrics",
                "selection_rule": "adopt recomputed primary fields; record every stored-vs-recomputed discrepancy instead of silently choosing one",
            },
        },
        "intentionally_omitted": [
            {
                "source_paths": ["conversation", "db_messages_ledger", "observations"],
                "reason": "full conversation/evidence ledger is not needed for the graph-semantic parity fixture and would expand the public artifact surface; evidence metrics remain an oracle snapshot",
            },
            {
                "source_paths": [
                    "run_00_seed9004.private.json:annotations_by_turn",
                    "alignments_by_turn",
                    "terminology_by_turn",
                ],
                "reason": "private semantic annotations are not primary Agent-to-Truth inputs",
            },
            {
                "source_paths": ["run_00_seed9004.private.json:knowledge"],
                "reason": "stakeholder-local IDs, hidden Truth mappings, and private knowledge are not required for this Agent/Truth fixture and are not copied",
            },
            {
                "source_paths": [
                    "agent_model",
                    "user_model",
                    "llm_args",
                    "elapsed_seconds",
                    "llm_call_metrics",
                    "reward_info",
                    "provider_errors",
                ],
                "reason": "runtime/provider metadata is not a primary evaluator oracle",
            },
            {
                "source_paths": [
                    "run_00_seed9004.diagnostics.json:evaluation",
                    "metrics",
                    "root_cause_attributions",
                    "joint_concept_disagreement_audit",
                ],
                "reason": "diagnostic-only traces are provenance material, not expected primary metrics",
            },
        ],
        "public_repository_hygiene": {
            "raw_public_artifact_copied": False,
            "raw_private_artifact_copied": False,
            "credentials_or_provider_secrets_copied": False,
            "normalized_files_contain_serialized_python_class_paths": False,
        },
        "phase4_entry": {
            "minimum_input": ["truth.json", "agent.json", "expected.json"],
            "first_component": "deterministic AgentGraph-to-TruthGraph alignment/comparison against the primary oracle fields",
            "not_started": [
                "comparison.py port",
                "evaluation.py port",
                "matching/scoring implementation",
                "stakeholder reference evaluation",
                "evidence/diagnostics replay",
            ],
        },
    }


def _timestamp(value: str | None) -> str:
    if value is None:
        return (
            datetime.now(timezone.utc)
            .replace(microsecond=0)
            .isoformat()
            .replace("+00:00", "Z")
        )
    parsed = datetime.fromisoformat(value.replace("Z", "+00:00"))
    if parsed.tzinfo is None:
        raise ValueError("--generated-at must include a timezone")
    return value


def build_fixture(
    *,
    source_root: Path,
    output_root: Path,
    generated_at: str | None = None,
) -> Path:
    project_root = Path(__file__).resolve().parents[2]
    source_root = source_root.resolve()
    output_root = _safe_output_root(project_root, output_root)
    source = _source_context(project_root, source_root)
    public_relative = SOURCE_ARTIFACTS[0][0]
    private_relative = SOURCE_ARTIFACTS[1][0]
    public_path = _source_artifact_path(source_root, public_relative)
    private_path = _source_artifact_path(source_root, private_relative)
    if public_path is None:
        raise FileNotFoundError(
            f"required public artifact is missing: {public_relative}"
        )
    public = _read_json(public_path)
    if public.get("task_id") != "quotation_workflow_1" or public.get("seed") != 9004:
        raise ValueError("public artifact is not seed 9004 quotation_workflow_1")
    truth = _normalize_truth(public)
    agent = _normalize_agent(public)
    recomputed = _recompute_primary(source_root, public_path, private_path, agent)
    expected = _expected_payload(public, recomputed)

    _write_json(output_root / "truth.json", truth.model_dump(mode="json"))
    _write_json(output_root / "agent.json", agent.model_dump(mode="json"))
    _write_json(output_root / "expected.json", expected)
    _write_json(
        output_root / "provenance.json",
        _provenance(source, output_root, _timestamp(generated_at)),
    )
    return output_root


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
    parser.add_argument(
        "--generated-at",
        help="optional timezone-aware ISO timestamp for reproducible provenance",
    )
    args = parser.parse_args(argv)
    try:
        output = build_fixture(
            source_root=args.source_root,
            output_root=args.output,
            generated_at=args.generated_at,
        )
    except (OSError, RuntimeError, ValueError, subprocess.SubprocessError) as exc:
        print(f"seed9004 fixture generation failed: {exc}", file=sys.stderr)
        return 1
    print(f"wrote normalized seed9004 fixture to {output}")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
