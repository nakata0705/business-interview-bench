"""Deterministic lexical concept identity alignment."""

# The project-level uv Pyright configuration resolves these local modules;
# this directive also quiets the workspace-level auxiliary resolver.
# pyright: reportMissingImports=false

from __future__ import annotations

import re
import unicodedata
from dataclasses import dataclass
from typing import Any

from business_interview.models import AgentGraph, ConceptRef

from .assignment import max_weight_assignment
from .projection import BusinessGraphView

_STOP_WORDS = frozenset(
    {
        "the",
        "a",
        "an",
        "and",
        "or",
        "of",
        "to",
        "in",
        "on",
        "for",
        "with",
        "at",
        "by",
        "is",
        "are",
        "was",
        "be",
        "it",
        "as",
        "that",
        "this",
        "we",
        "do",
        "does",
        "doesn",
        "don",
        "via",
        "into",
        "from",
        "then",
        "after",
        "before",
        "when",
        "if",
        "so",
        "also",
        "using",
        "use",
        "used",
        "has",
        "have",
        "had",
        "there",
        "their",
        "i",
        "my",
        "you",
        "your",
        "he",
        "she",
        "they",
        "who",
        "what",
        "all",
        "any",
        "some",
        "not",
        "no",
        "yes",
        "but",
        "same",
        "other",
        "about",
        "would",
        "will",
        "can",
        "could",
        "should",
        "just",
        "very",
        "much",
        "more",
        "most",
        "than",
        "up",
        "down",
        "out",
        "over",
        "again",
        "once",
        "day",
        "time",
        "things",
        "thing",
    }
)

_GENERIC_TOKENS = frozenset(
    {
        "system",
        "systems",
        "document",
        "documents",
        "information",
        "quotation",
        "quotations",
        "process",
        "processes",
        "data",
    }
)

_CJK_RE = re.compile(
    r"[\u3040-\u30ff\u3400-\u4dbf\u4e00-\u9fff"
    r"\uf900-\ufaff\U00020000-\U0002a6df\U0002b740-\U0002b81f]"
)
CONCEPT_MATCH_THRESHOLD = 0.4


@dataclass(frozen=True)
class ConceptAlignment:
    """Concept-local to Truth-local mapping and aggregate lexical scores."""

    concept_to_truth: dict[str, str]
    concept_recall: float
    concept_precision: float


def normalize_text(text: str | None) -> str:
    """NFKC-normalize and lowercase text without language-specific parsing."""
    if not text:
        return ""
    return unicodedata.normalize("NFKC", str(text)).lower()


def _split_runs(text: str):
    """Yield ``(is_cjk, chunk)`` runs over normalized text."""
    if not text:
        return
    current_is_cjk = bool(_CJK_RE.match(text[0]))
    start = 0
    for index, character in enumerate(text):
        is_cjk = bool(_CJK_RE.match(character))
        if is_cjk != current_is_cjk:
            yield current_is_cjk, text[start:index]
            start = index
            current_is_cjk = is_cjk
    yield current_is_cjk, text[start:]


def _char_bigrams(chunk: str) -> set[str]:
    """Return CJK character bigrams, or the single character for length one."""
    if len(chunk) == 1:
        return {chunk}
    return {chunk[index : index + 2] for index in range(len(chunk) - 1)}


def tokenize(text: str | None) -> set[str]:
    """Return the source-compatible Latin/CJK lexical signature."""
    normalized = normalize_text(text)
    if not normalized:
        return set()
    tokens: set[str] = set()
    for is_cjk, chunk in _split_runs(normalized):
        if is_cjk:
            tokens.update(_char_bigrams(chunk))
        else:
            for word in re.findall(r"[a-z0-9]+", chunk):
                if (
                    len(word) >= 2
                    and word not in _STOP_WORDS
                    and word not in _GENERIC_TOKENS
                ):
                    tokens.add(word)
    return tokens


def dice_similarity(left: set[str], right: set[str]) -> float:
    """Return the symmetric Dice coefficient, or zero for empty/disjoint sets."""
    if not left or not right:
        return 0.0
    intersection = left & right
    if not intersection:
        return 0.0
    return 2.0 * len(intersection) / (len(left) + len(right))


def _label_key(text: str | None) -> str:
    """Normalize a label for punctuation/spacing-insensitive exact matching."""
    return "".join(
        character for character in normalize_text(text) if character.isalnum()
    )


def _truth_label_tokens(
    concept: Any,
    extra_terms: tuple[str, ...] | list[str] | None = None,
) -> set[str]:
    tokens: set[str] = set()
    for term in concept.canonical_terms:
        tokens.update(tokenize(term))
    for term in extra_terms or ():
        tokens.update(tokenize(term))
    return tokens


def _truth_concept_tokens(
    concept: Any,
    extra_terms: tuple[str, ...] | list[str] | None = None,
) -> set[str]:
    return _truth_label_tokens(concept, extra_terms) | tokenize(concept.description)


def _has_exact_label_match(
    agent_concept: Any,
    truth_concept: Any,
    extra_terms: tuple[str, ...] | list[str] | None = None,
) -> bool:
    agent_key = _label_key(agent_concept.display_label)
    if not agent_key:
        return False
    candidates = list(truth_concept.canonical_terms) + list(extra_terms or ())
    return any(agent_key == _label_key(term) for term in candidates)


def concept_similarity(
    agent_concept: Any,
    truth_concept: Any,
    extra_terms: tuple[str, ...] | list[str] | None = None,
) -> float:
    """Return source-compatible exact-label/description Dice similarity."""
    if _has_exact_label_match(agent_concept, truth_concept, extra_terms):
        return 1.0
    agent_label = tokenize(agent_concept.display_label)
    agent_full = agent_label | tokenize(agent_concept.description)
    truth_label = _truth_label_tokens(truth_concept)
    truth_full = _truth_concept_tokens(truth_concept)
    truth_label_with_extras = _truth_label_tokens(truth_concept, extra_terms)
    truth_full_with_extras = _truth_concept_tokens(truth_concept, extra_terms)
    return max(
        dice_similarity(agent_label, truth_label),
        dice_similarity(agent_label, truth_label_with_extras),
        dice_similarity(agent_full, truth_full),
        dice_similarity(agent_full, truth_full_with_extras),
    )


def _truth_referenced_concept_ids(truth: BusinessGraphView) -> set[str]:
    concept_ids: set[str] = set()
    for node in truth.nodes.values():
        for property_name in (
            "activity",
            "actor",
            "system",
            "reads",
            "writes",
            "rationale",
        ):
            concept_ids.update(ref.concept_id for ref in node.refs(property_name))
    for edge in truth.edges.values():
        if isinstance(edge.condition, ConceptRef):
            concept_ids.add(edge.condition.concept_id)
    return concept_ids


def _agent_referenced_concept_ids(agent: AgentGraph) -> set[str]:
    concept_ids: set[str] = set()
    for node in agent.nodes.values():
        for property_name in (
            "activity",
            "actor",
            "system",
            "reads",
            "writes",
            "rationale",
        ):
            concept_ids.update(
                ref.concept_id for ref in node.refs(property_name) if ref.asserted
            )
    for edge in agent.edges.values():
        if isinstance(edge.condition, ConceptRef) and edge.condition.asserted:
            concept_ids.add(edge.condition.concept_id)
    return concept_ids


def align_concepts(
    agent: AgentGraph,
    truth: BusinessGraphView,
    terminology_terms: dict[str, list[str]] | None = None,
) -> ConceptAlignment:
    """Align referenced concepts by kind using deterministic lexical assignment."""
    expected = _truth_referenced_concept_ids(truth)
    attempted = _agent_referenced_concept_ids(agent)
    kinds = sorted(
        {concept.kind for concept in agent.concepts.values() if concept.id in attempted}
    )
    recognized: dict[str, str] = {}
    for kind in kinds:
        left = sorted(
            concept_id
            for concept_id in attempted
            if concept_id in agent.concepts and agent.concepts[concept_id].kind == kind
        )
        right = sorted(
            concept_id
            for concept_id in expected
            if concept_id in truth.concepts and truth.concepts[concept_id].kind == kind
        )
        weights: dict[tuple[str, str], float] = {}
        for agent_id in left:
            for truth_id in right:
                similarity = concept_similarity(
                    agent.concepts[agent_id],
                    truth.concepts[truth_id],
                    (terminology_terms or {}).get(truth_id),
                )
                if similarity >= CONCEPT_MATCH_THRESHOLD:
                    weights[(agent_id, truth_id)] = similarity
        recognized.update(
            max_weight_assignment(
                weights,
                left,
                right,
                threshold=CONCEPT_MATCH_THRESHOLD,
            )
        )

    recalled = set(recognized.values()) & expected
    concept_recall = len(recalled) / len(expected) if expected else 1.0
    concept_precision = len(recognized) / len(attempted) if attempted else 1.0
    concept_to_truth = {
        agent_id: truth_id
        for agent_id, truth_id in recognized.items()
        if truth_id in expected
    }
    return ConceptAlignment(
        concept_to_truth=concept_to_truth,
        concept_recall=concept_recall,
        concept_precision=concept_precision,
    )


__all__ = [
    "CONCEPT_MATCH_THRESHOLD",
    "ConceptAlignment",
    "align_concepts",
    "concept_similarity",
    "dice_similarity",
    "normalize_text",
    "tokenize",
]
