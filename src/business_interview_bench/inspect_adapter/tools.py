"""Thin Inspect ``@tool`` wrappers for the core interview operations.

These wrappers only read/write a mutable runtime reference. Mutation tools
return compact receipts and the explicit graph-read tool serializes the public
AgentGraph. They do not know Truth, stakeholder knowledge, or
the private semantic ledger, and they contain no graph mutation semantics.
"""

# The workspace-level auxiliary resolver may not see the Inspect dev group.
# Project-level ``uv run pyright`` is authoritative for this adapter.
# pyright: reportMissingImports=false

from __future__ import annotations

import json
from collections.abc import Callable
from typing import Any

from inspect_ai.tool import Tool, ToolError, tool

from business_interview.graph_mutations import (
    GraphMutationError,
    add_edge,
    add_node,
    attach_evidence,
    define_concept,
    remove_concept,
    remove_edge,
    remove_node,
    set_edge_condition,
    set_edge_condition_absent,
    set_edge_condition_dont_know,
    set_end_nodes,
    set_node_absent,
    set_node_dont_know,
    set_node_property,
    set_start_nodes,
    update_concept,
    update_edge,
    update_node,
)
from business_interview.runtime import (
    LiveInterviewStore,
    apply_agent_graph_mutation,
    mark_interview_complete,
)

PersistRuntime = Callable[[LiveInterviewStore], None]


def _graph_json(runtime: LiveInterviewStore) -> str:
    return json.dumps(
        runtime.agent_graph.model_dump(mode="json"),
        ensure_ascii=False,
        sort_keys=True,
    )


def _mutation_result(operation: str, target: str) -> str:
    """Return a stable small result; the full graph is an explicit read."""
    return json.dumps(
        {"ok": True, "operation": operation, "target": target},
        ensure_ascii=False,
        sort_keys=True,
    )


def build_interview_tools(
    runtime_ref: list[LiveInterviewStore],
    *,
    persist: PersistRuntime | None = None,
    on_complete: Callable[[], None] | None = None,
) -> list[Tool]:
    """Build one set of candidate tools bound to a live-state reference.

    ``runtime_ref`` is a one-element list so tool executions can replace the
    immutable-by-operation runtime value and the solver can observe it.  The
    optional ``persist`` callback is the sole adapter Store integration point.
    """
    if len(runtime_ref) != 1:
        raise ValueError("runtime_ref must contain exactly one LiveInterviewStore")
    if not isinstance(runtime_ref[0], LiveInterviewStore):
        raise TypeError("runtime_ref must contain a LiveInterviewStore")

    def save(runtime: LiveInterviewStore) -> None:
        runtime_ref[0] = runtime
        if persist is not None:
            persist(runtime)

    def mutate(
        operation: Callable[..., Any],
        *,
        operation_name: str,
        result_target: str,
        **kwargs: Any,
    ) -> str:
        runtime = runtime_ref[0]
        try:
            updated = apply_agent_graph_mutation(
                runtime,
                lambda graph: operation(graph, **kwargs),
            )
        except (GraphMutationError, ValueError) as exc:
            # Inspect presents ToolError to the candidate as a regular tool
            # result, allowing it to correct an invalid graph operation.
            raise ToolError(str(exc)) from exc
        save(updated)
        return _mutation_result(operation_name, result_target)

    @tool(name="get_agent_graph")
    def get_agent_graph() -> Tool:
        """Read the current AgentGraph hypothesis.

        This returns only the candidate's graph, including its own node,
        edge, concept, endpoint, and public-observation evidence state.
        It never contains canonical Truth or stakeholder-private state.
        """

        async def execute() -> str:
            """Return the current candidate-owned AgentGraph as JSON."""
            return _graph_json(runtime_ref[0])

        return execute

    @tool(name="get_observations")
    def get_observations() -> Tool:
        """Read accepted public observations and their stable IDs as JSON.

        This exposes exact public text, turn, and observation ID only. It does
        not expose private semantic annotations, alignments, or terminology.
        """

        async def execute() -> str:
            """Return accepted public observation IDs, turns, and exact text."""
            return json.dumps(
                [
                    {
                        "id": observation.id,
                        "turn": observation.turn,
                        "text": observation.text,
                    }
                    for observation in runtime_ref[0].observations
                ],
                ensure_ascii=False,
                sort_keys=True,
            )

        return execute

    @tool(name="add_node")
    def add_node_tool() -> Tool:
        """Add a node to the AgentGraph; use set_node_property for its slots."""

        async def execute(node_id: str) -> str:
            """Add a node and return a compact mutation receipt as JSON.

            Args:
                node_id: New candidate-owned node ID.
            """
            return mutate(
                add_node,
                operation_name="add_node",
                result_target=f"node:{node_id}",
                node_id=node_id,
            )

        return execute

    @tool(name="update_node")
    def update_node_tool() -> Tool:
        """Update an existing AgentGraph node with a JSON updates object."""

        async def execute(node_id: str, updates: dict[str, Any]) -> str:
            """Apply a JSON patch and return a compact mutation receipt.

            Args:
                node_id: Existing node ID.
                updates: Node fields to update.
            """
            return mutate(
                update_node,
                operation_name="update_node",
                result_target=f"node:{node_id}",
                node_id=node_id,
                updates=updates,
            )

        return execute

    @tool(name="remove_node")
    def remove_node_tool() -> Tool:
        """Remove an AgentGraph node after its incident edges are removed."""

        async def execute(node_id: str) -> str:
            """Remove an existing node and return a compact mutation receipt.

            Args:
                node_id: Existing node ID.
            """
            return mutate(
                remove_node,
                operation_name="remove_node",
                result_target=f"node:{node_id}",
                node_id=node_id,
            )

        return execute

    @tool(name="add_edge")
    def add_edge_tool() -> Tool:
        """Add a directed edge between two existing AgentGraph nodes."""

        async def execute(edge_id: str, from_node: str, to_node: str) -> str:
            """Add an edge and return a compact mutation receipt.

            Args:
                edge_id: New candidate-owned edge ID.
                from_node: Source node ID.
                to_node: Destination node ID.
            """
            return mutate(
                add_edge,
                operation_name="add_edge",
                result_target=f"edge:{edge_id}",
                edge_id=edge_id,
                from_node=from_node,
                to_node=to_node,
            )

        return execute

    @tool(name="update_edge")
    def update_edge_tool() -> Tool:
        """Update an existing AgentGraph edge with a JSON updates object."""

        async def execute(edge_id: str, updates: dict[str, Any]) -> str:
            """Apply a JSON patch and return a compact mutation receipt.

            Args:
                edge_id: Existing edge ID.
                updates: Edge fields to update.
            """
            return mutate(
                update_edge,
                operation_name="update_edge",
                result_target=f"edge:{edge_id}",
                edge_id=edge_id,
                updates=updates,
            )

        return execute

    @tool(name="remove_edge")
    def remove_edge_tool() -> Tool:
        """Remove an existing AgentGraph edge."""

        async def execute(edge_id: str) -> str:
            """Remove an edge and return a compact mutation receipt.

            Args:
                edge_id: Existing edge ID.
            """
            return mutate(
                remove_edge,
                operation_name="remove_edge",
                result_target=f"edge:{edge_id}",
                edge_id=edge_id,
            )

        return execute

    @tool(name="define_concept")
    def define_concept_tool() -> Tool:
        """Define an AgentGraph glossary concept for later slot references."""

        async def execute(
            concept_id: str,
            kind: str,
            display_label: str,
            description: str = "",
        ) -> str:
            """Add a glossary concept and return a compact mutation receipt.

            Args:
                concept_id: New candidate-owned concept ID.
                kind: Concept kind such as activity, actor, data, or condition.
                display_label: Human-readable label.
                description: Optional candidate description.
            """
            return mutate(
                define_concept,
                operation_name="define_concept",
                result_target=f"concept:{concept_id}",
                concept_id=concept_id,
                kind=kind,
                display_label=display_label,
                description=description,
            )

        return execute

    @tool(name="update_concept")
    def update_concept_tool() -> Tool:
        """Update an existing AgentGraph glossary concept."""

        async def execute(concept_id: str, updates: dict[str, Any]) -> str:
            """Apply a JSON patch and return a compact mutation receipt.

            Args:
                concept_id: Existing concept ID.
                updates: Concept fields to update.
            """
            return mutate(
                update_concept,
                operation_name="update_concept",
                result_target=f"concept:{concept_id}",
                concept_id=concept_id,
                updates=updates,
            )

        return execute

    @tool(name="remove_concept")
    def remove_concept_tool() -> Tool:
        """Remove an unreferenced AgentGraph glossary concept."""

        async def execute(concept_id: str) -> str:
            """Remove a glossary concept and return a compact mutation receipt.

            Args:
                concept_id: Existing concept ID.
            """
            return mutate(
                remove_concept,
                operation_name="remove_concept",
                result_target=f"concept:{concept_id}",
                concept_id=concept_id,
            )

        return execute

    @tool(name="set_node_property")
    def set_node_property_tool() -> Tool:
        """Set activity, actor, system, reads, writes, or rationale.

        ``value`` is a concept ID string, a list of concept ID strings, or a
        JSON object with ``state`` equal to ``unset``, ``absent``, or
        ``dont_know`` and optional EvidenceRef objects.
        """

        async def execute(
            node_id: str,
            property_name: str,
            value: Any,
        ) -> str:
            """Set one node property to a concept value or explicit state.

            Args:
                node_id: Existing node ID.
                property_name: activity, actor, system, reads, writes, or rationale.
                value: Concept ID, list of concept IDs, or state object.
            """
            return mutate(
                set_node_property,
                operation_name="set_node_property",
                result_target=f"node:{node_id}:{property_name}",
                node_id=node_id,
                property_name=property_name,
                value=value,
            )

        return execute

    @tool(name="set_node_absent")
    def set_node_absent_tool() -> Tool:
        """Mark one AgentGraph node property explicitly ABSENT."""

        async def execute(
            node_id: str,
            property_name: str,
            evidence: list[dict[str, Any]] | None = None,
        ) -> str:
            """Set a node property to ABSENT and return a compact receipt.

            Args:
                node_id: Existing node ID.
                property_name: Node property to mark absent.
                evidence: Optional public EvidenceRef objects.
            """
            return mutate(
                set_node_absent,
                operation_name="set_node_absent",
                result_target=f"node:{node_id}:{property_name}",
                node_id=node_id,
                property_name=property_name,
                evidence=evidence or (),
            )

        return execute

    @tool(name="set_node_dont_know")
    def set_node_dont_know_tool() -> Tool:
        """Mark one AgentGraph node property explicitly DONT_KNOW."""

        async def execute(
            node_id: str,
            property_name: str,
            evidence: list[dict[str, Any]] | None = None,
        ) -> str:
            """Set a node property to explicit DONT_KNOW.

            Args:
                node_id: Existing node ID.
                property_name: Node property whose value is unknown.
                evidence: Optional public EvidenceRef objects.
            """
            return mutate(
                set_node_dont_know,
                operation_name="set_node_dont_know",
                result_target=f"node:{node_id}:{property_name}",
                node_id=node_id,
                property_name=property_name,
                evidence=evidence or (),
            )

        return execute

    @tool(name="set_edge_condition")
    def set_edge_condition_tool() -> Tool:
        """Set an edge condition to a concept ID or explicit state object."""

        async def execute(edge_id: str, value: Any) -> str:
            """Set an edge condition and return a compact mutation receipt.

            Args:
                edge_id: Existing edge ID.
                value: Concept ID or state object.
            """
            return mutate(
                set_edge_condition,
                operation_name="set_edge_condition",
                result_target=f"edge:{edge_id}:condition",
                edge_id=edge_id,
                value=value,
            )

        return execute

    @tool(name="set_edge_condition_absent")
    def set_edge_condition_absent_tool() -> Tool:
        """Mark an edge condition explicitly ABSENT."""

        async def execute(
            edge_id: str,
            evidence: list[dict[str, Any]] | None = None,
        ) -> str:
            """Set an edge condition to ABSENT and return a compact receipt.

            Args:
                edge_id: Existing edge ID.
                evidence: Optional public EvidenceRef objects.
            """
            return mutate(
                set_edge_condition_absent,
                operation_name="set_edge_condition_absent",
                result_target=f"edge:{edge_id}:condition",
                edge_id=edge_id,
                evidence=evidence or (),
            )

        return execute

    @tool(name="set_edge_condition_dont_know")
    def set_edge_condition_dont_know_tool() -> Tool:
        """Mark an edge condition explicitly DONT_KNOW."""

        async def execute(
            edge_id: str,
            evidence: list[dict[str, Any]] | None = None,
        ) -> str:
            """Set an edge condition to DONT_KNOW and return a compact receipt.

            Args:
                edge_id: Existing edge ID.
                evidence: Optional public EvidenceRef objects.
            """
            return mutate(
                set_edge_condition_dont_know,
                operation_name="set_edge_condition_dont_know",
                result_target=f"edge:{edge_id}:condition",
                edge_id=edge_id,
                evidence=evidence or (),
            )

        return execute

    @tool(name="attach_evidence")
    def attach_evidence_tool() -> Tool:
        """Attach a public Observation EvidenceRef to a graph target.

        Use targets such as ``node:n1:activity``,
        ``node:n1:reads:data_concept``, ``edge:e1``,
        ``edge:e1:condition``, or ``concept:c1``.  The observation ID must
        refer to an accepted public stakeholder response.
        """

        async def execute(
            target: str,
            observation_id: str,
            quote: str | None = None,
            occurrence: int = 0,
        ) -> str:
            """Attach evidence and return a compact mutation receipt.

            Args:
                target: Graph target such as node:n1:activity or edge:e1.
                observation_id: Accepted public observation ID.
                quote: Exact quoted text, when available.
                occurrence: Zero-based occurrence of quote.
            """
            return mutate(
                attach_evidence,
                operation_name="attach_evidence",
                result_target=target,
                target=target,
                observation_id=observation_id,
                quote=quote,
                occurrence=occurrence,
                observation_ids={
                    observation.id for observation in runtime_ref[0].observations
                },
                observation_texts={
                    observation.id: observation.text
                    for observation in runtime_ref[0].observations
                },
            )

        return execute

    @tool(name="set_start_nodes")
    def set_start_nodes_tool() -> Tool:
        """Set the AgentGraph start node IDs after they have been added."""

        async def execute(node_ids: list[str]) -> str:
            """Set graph starts and return a compact mutation receipt.

            Args:
                node_ids: Unique existing start node IDs.
            """
            return mutate(
                set_start_nodes,
                operation_name="set_start_nodes",
                result_target="agent_graph:start_node_ids",
                node_ids=node_ids,
            )

        return execute

    @tool(name="set_end_nodes")
    def set_end_nodes_tool() -> Tool:
        """Set the AgentGraph end node IDs after they have been added."""

        async def execute(node_ids: list[str]) -> str:
            """Set graph ends and return a compact mutation receipt.

            Args:
                node_ids: Unique existing end node IDs.
            """
            return mutate(
                set_end_nodes,
                operation_name="set_end_nodes",
                result_target="agent_graph:end_node_ids",
                node_ids=node_ids,
            )

        return execute

    @tool(name="complete_interview")
    def complete_interview_tool() -> Tool:
        """Explicitly declare that the Business Interview is complete.

        After this call no stakeholder response or graph mutation is allowed.
        """

        async def execute(reason: str = "agent_declared") -> str:
            """Declare the interview complete and stop all further mutations.

            Args:
                reason: Brief explicit completion reason.
            """
            try:
                updated = mark_interview_complete(runtime_ref[0], reason)
            except ValueError as exc:
                raise ToolError(str(exc)) from exc
            save(updated)
            if on_complete is not None:
                on_complete()
            return _mutation_result("complete_interview", "interview")

        return execute

    return [
        get_agent_graph(),
        get_observations(),
        add_node_tool(),
        update_node_tool(),
        remove_node_tool(),
        add_edge_tool(),
        update_edge_tool(),
        remove_edge_tool(),
        define_concept_tool(),
        update_concept_tool(),
        remove_concept_tool(),
        set_node_property_tool(),
        set_node_absent_tool(),
        set_node_dont_know_tool(),
        set_edge_condition_tool(),
        set_edge_condition_absent_tool(),
        set_edge_condition_dont_know_tool(),
        attach_evidence_tool(),
        set_start_nodes_tool(),
        set_end_nodes_tool(),
        complete_interview_tool(),
    ]


# Names used by callers that prefer the operation-oriented wording.
graph_mutation_tools = build_interview_tools
make_interview_tools = build_interview_tools


__all__ = ["build_interview_tools", "graph_mutation_tools", "make_interview_tools"]
