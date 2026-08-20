"""Map graphiti-core results into proposal drafts and durable receipts."""

from __future__ import annotations

import re
from datetime import datetime
from typing import Any

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.extraction.models import ProducedExtraction, ProposalDraft
from newsroom.extraction.types import (
    EvidenceRange,
    ExtractionFailureCode,
    ExtractionOutcome,
    ExtractionOutputValidation,
    ExtractionProposalKind,
    ExtractionUsage,
    ProposalPredicateHint,
)

from .models import GraphitiAttemptRequest

_SOURCE_REGISTRY_ID = re.compile(r"^[A-Z]{2,3}-\d{2}(?::.*)?$")
_PREDICATE_HINTS = {item.value: item for item in ProposalPredicateHint}


def is_source_registry_name(name: str) -> bool:
    return _SOURCE_REGISTRY_ID.match(name) is not None


def episode_body(attempt: GraphitiAttemptRequest) -> str:
    return "\n\n".join(
        passage.require_text()
        for passage in attempt.extraction_request.input_binding.passages
    )


def _evidence_for(
    name: str, attempt: GraphitiAttemptRequest
) -> EvidenceRange | None:
    needle = name.encode("utf-8")
    if not needle:
        return None
    for passage in attempt.extraction_request.input_binding.passages:
        data = passage.require_text().encode("utf-8")
        start = data.find(needle)
        if start < 0:
            continue
        end = start + len(needle)
        return EvidenceRange(
            passage_id=passage.passage_id,
            start_byte=start,
            end_byte=end,
            evidence_text_digest=digest_bytes(data[start:end]),
        )
    return None


def entity_proposals(
    result: Any, attempt: GraphitiAttemptRequest
) -> tuple[ProposalDraft, ...]:
    drafts: list[ProposalDraft] = []
    for index, node in enumerate(getattr(result, "nodes", ()) or (), start=1):
        raw_name = getattr(node, "name", None)
        if not isinstance(raw_name, str):
            continue
        name = " ".join(raw_name.split())
        if not name or is_source_registry_name(name):
            continue
        evidence = _evidence_for(name, attempt)
        if evidence is None:
            continue
        drafts.append(
            ProposalDraft(
                local_id=f"entity.{index:04d}",
                kind=ExtractionProposalKind.ENTITY_MENTION,
                subject_placeholder=name,
                object_placeholder=None,
                predicate_hint=None,
                confidence_basis_points=None,
                uncertainty_codes=(),
                rationale_codes=("GRAPHITI_EVALUATION_SPAN",),
                evidence=(evidence,),
            )
        )
    return tuple(sorted(drafts, key=lambda item: item.local_id))


def _predicate_hint(name: object) -> ProposalPredicateHint:
    if isinstance(name, str):
        hint = _PREDICATE_HINTS.get(name.strip().upper().replace(" ", "_"))
        if hint is not None:
            return hint
    return ProposalPredicateHint.ABOUT_EVENT


def _node_names(result: Any) -> dict[str, str]:
    names: dict[str, str] = {}
    for node in getattr(result, "nodes", ()) or ():
        uuid = getattr(node, "uuid", None)
        raw_name = getattr(node, "name", None)
        if uuid is None or not isinstance(raw_name, str):
            continue
        name = " ".join(raw_name.split())
        if name:
            names[str(uuid)] = name
    return names


def relation_proposals(
    result: Any, attempt: GraphitiAttemptRequest
) -> tuple[ProposalDraft, ...]:
    drafts: list[ProposalDraft] = []
    names = _node_names(result)
    for index, edge in enumerate(getattr(result, "edges", ()) or (), start=1):
        fact = getattr(edge, "fact", None)
        fact_text = " ".join(str(fact).split()) if fact else ""
        source_uuid = str(getattr(edge, "source_node_uuid", "") or "")
        target_uuid = str(getattr(edge, "target_node_uuid", "") or "")
        subject = names.get(source_uuid) or source_uuid
        obj = names.get(target_uuid) or target_uuid
        if not subject or not obj:
            continue
        if is_source_registry_name(subject) or is_source_registry_name(obj):
            continue
        evidence = (
            _evidence_for(fact_text, attempt) if fact_text else None
        ) or _evidence_for(subject, attempt)
        if evidence is None:
            continue
        drafts.append(
            ProposalDraft(
                local_id=f"relation.{index:04d}",
                kind=ExtractionProposalKind.RELATION,
                subject_placeholder=subject,
                object_placeholder=obj,
                predicate_hint=_predicate_hint(getattr(edge, "name", None)),
                confidence_basis_points=None,
                uncertainty_codes=("REQUIRES_RELATION_ADMISSION",),
                rationale_codes=("GRAPHITI_EVALUATION_SPAN",),
                evidence=(evidence,),
            )
        )
    return tuple(drafts)


def episode_uuid(result: Any) -> str:
    episode = getattr(result, "episode", None)
    uuid = None if episode is None else getattr(episode, "uuid", None)
    return "" if uuid is None else str(uuid)


def _iso(value: object) -> str | None:
    if value is None:
        return None
    if isinstance(value, datetime):
        return value.isoformat()
    return str(value)


def relation_receipts(result: Any) -> tuple[dict[str, object], ...]:
    return tuple(
        {
            "local_id": f"relation.{index:04d}",
            "uuid": getattr(edge, "uuid", None),
            "name": getattr(edge, "name", None),
            "fact": getattr(edge, "fact", None),
            "source_node_uuid": getattr(edge, "source_node_uuid", None),
            "target_node_uuid": getattr(edge, "target_node_uuid", None),
            "valid_at": _iso(getattr(edge, "valid_at", None)),
            "invalid_at": _iso(getattr(edge, "invalid_at", None)),
            "expired_at": _iso(getattr(edge, "expired_at", None)),
        }
        for index, edge in enumerate(getattr(result, "edges", ()) or (), start=1)
    )


def entity_receipts(result: Any) -> tuple[dict[str, object], ...]:
    receipts: list[dict[str, object]] = []
    for index, node in enumerate(getattr(result, "nodes", ()) or (), start=1):
        name = getattr(node, "name", None)
        receipts.append(
            {
                "local_id": f"entity.{index:04d}",
                "uuid": getattr(node, "uuid", None),
                "name": name,
                "summary": getattr(node, "summary", None),
                "source_registry_id": (
                    isinstance(name, str) and is_source_registry_name(name)
                ),
            }
        )
    return tuple(receipts)


def extraction_usage(
    attempt: GraphitiAttemptRequest,
    raw: dict[str, object] | None,
    proposals: tuple[ProposalDraft, ...],
    embedding_usage: dict[str, object] | None = None,
) -> ExtractionUsage:
    usage = embedding_usage or {}
    tokens = usage.get("embedding_tokens")
    cost = usage.get("cost_usd_microunits")
    return ExtractionUsage(
        elapsed_ms=0,
        input_bytes=attempt.extraction_request.input_binding.input_bytes,
        output_bytes=0 if raw is None else len(canonical_json_bytes(raw)),
        proposal_count=len(proposals),
        evidence_range_count=sum(len(item.evidence) for item in proposals),
        request_tokens=tokens if isinstance(tokens, int) else 0,
        response_tokens=0,
        cost_microunits=cost if isinstance(cost, int) else 0,
    )


def produced_extraction(
    attempt: GraphitiAttemptRequest,
    *,
    outcome: ExtractionOutcome,
    failure_code: ExtractionFailureCode,
    validation: ExtractionOutputValidation | None,
    raw: dict[str, object] | None,
    proposals: tuple[ProposalDraft, ...],
    embedding_usage: dict[str, object] | None = None,
) -> ProducedExtraction:
    return ProducedExtraction(
        outcome=outcome,
        failure_code=failure_code,
        validation=validation,
        raw_output_value=raw,
        proposals=proposals,
        usage=extraction_usage(attempt, raw, proposals, embedding_usage),
    )


def private_graph(
    produced: ProducedExtraction,
    relations: tuple[dict[str, object], ...],
) -> tuple[tuple[dict[str, object], ...], tuple[dict[str, object], ...]]:
    nodes = tuple(
        {
            "private_node_id": f"private-node-{index:04d}",
            "proposal_local_id": proposal.local_id,
            "proposal_kind": proposal.kind.value,
            "proposal_digest": proposal.digest,
        }
        for index, proposal in enumerate(produced.proposals, start=1)
    )
    private_relations = tuple(
        {
            "private_relation_id": f"private-relation-{index:04d}",
            "proposal_local_id": item["local_id"],
            "name": item.get("name"),
            "fact": item.get("fact"),
            "source_node_uuid": item.get("source_node_uuid"),
            "target_node_uuid": item.get("target_node_uuid"),
            "valid_at": item.get("valid_at"),
            "invalid_at": item.get("invalid_at"),
        }
        for index, item in enumerate(relations, start=1)
    )
    return nodes, private_relations


__all__ = [
    "entity_proposals",
    "entity_receipts",
    "episode_body",
    "episode_uuid",
    "is_source_registry_name",
    "private_graph",
    "produced_extraction",
    "relation_proposals",
    "relation_receipts",
]
