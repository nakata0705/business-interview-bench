"""Deterministic maximum-weight bipartite assignment helpers."""

from __future__ import annotations

from collections.abc import Mapping, Sequence
from typing import Any


def max_weight_assignment(
    weights: Mapping[tuple[str, str], float],
    left: Sequence[str],
    right: Sequence[str],
    *,
    threshold: float,
) -> dict[str, str]:
    """Return a deterministic thresholded one-to-one maximum-weight mapping.

    The implementation is the Kuhn-Munkres/Hungarian assignment used by the
    source comparison core.  Real rows and columns are padded with dummy
    counterparts, so low-scoring or forbidden pairs remain unmatched.  IDs
    are sorted internally; dictionary insertion order therefore cannot affect
    the result.
    """
    left_ids = sorted(set(left))
    right_ids = sorted(set(right))
    n, m = len(left_ids), len(right_ids)
    if n == 0 or m == 0:
        return {}

    size = n + m
    big = 1e15
    # cost[column][row], with one-based real and dummy row/column indices.
    cost = [[0.0] * (size + 1) for _ in range(size + 1)]
    row_index = {item: index for index, item in enumerate(left_ids, start=1)}
    column_index = {item: index for index, item in enumerate(right_ids, start=1)}
    allowed: set[tuple[int, int]] = set()
    for (left_id, right_id), weight in weights.items():
        if weight >= threshold and left_id in row_index and right_id in column_index:
            row = row_index[left_id]
            column = column_index[right_id]
            cost[column][row] = -weight
            allowed.add((row, column))

    for row in range(1, n + 1):
        for column in range(1, m + 1):
            if (row, column) not in allowed:
                cost[column][row] = big

    u = [0.0] * (size + 1)
    v = [0.0] * (size + 1)
    matched_row_for_column = [0] * (size + 1)
    previous_column = [0] * (size + 1)

    for row in range(1, size + 1):
        matched_row_for_column[0] = row
        current_column = 0
        minimum = [1e18] * (size + 1)
        used = [False] * (size + 1)
        while True:
            used[current_column] = True
            matched_row = matched_row_for_column[current_column]
            delta = 1e18
            next_column = 0
            for column in range(1, size + 1):
                if used[column]:
                    continue
                current = cost[column][matched_row] - u[matched_row] - v[column]
                if current < minimum[column]:
                    minimum[column] = current
                    previous_column[column] = current_column
                if minimum[column] < delta:
                    delta = minimum[column]
                    next_column = column
            for column in range(size + 1):
                if used[column]:
                    u[matched_row_for_column[column]] += delta
                    v[column] -= delta
                else:
                    minimum[column] -= delta
            current_column = next_column
            if matched_row_for_column[current_column] == 0:
                break

        while True:
            next_column = previous_column[current_column]
            matched_row_for_column[current_column] = matched_row_for_column[next_column]
            current_column = next_column
            if current_column == 0:
                break

    assignment: dict[str, str] = {}
    for column in range(1, m + 1):
        row = matched_row_for_column[column]
        if 1 <= row <= n and (row, column) in allowed:
            assignment[left_ids[row - 1]] = right_ids[column - 1]
    return assignment


def bipartite_components(
    weights: Mapping[tuple[str, str], Any],
) -> list[tuple[list[str], list[str]]]:
    """Split a bipartite candidate graph into independent components."""
    left_neighbors: dict[str, set[str]] = {}
    right_neighbors: dict[str, set[str]] = {}
    for left, right in weights:
        left_neighbors.setdefault(left, set()).add(right)
        right_neighbors.setdefault(right, set()).add(left)

    remaining = set(left_neighbors)
    components: list[tuple[list[str], list[str]]] = []
    while remaining:
        start = min(remaining)
        left_component = {start}
        right_component: set[str] = set()
        queue = [start]
        while queue:
            left = queue.pop()
            for right in sorted(left_neighbors[left]):
                if right in right_component:
                    continue
                right_component.add(right)
                for neighbor in sorted(right_neighbors[right]):
                    if neighbor not in left_component:
                        left_component.add(neighbor)
                        queue.append(neighbor)
        remaining -= left_component
        components.append((sorted(left_component), sorted(right_component)))
    return components


def assignment_score(
    assignment: Mapping[str, str],
    weights: Mapping[tuple[str, str], float],
) -> float:
    """Return the total weight of an assignment."""
    return sum(weights[(left, right)] for left, right in assignment.items())


__all__ = [
    "assignment_score",
    "bipartite_components",
    "max_weight_assignment",
]
