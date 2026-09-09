"""Deterministic, provider-free production triage proposal worker."""

from __future__ import annotations

import json
import uuid

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.discovery import NewsLead
from newsroom.increment5.retrieval_context import RETRIEVAL_CONTEXT_CONTRACT_DIGEST
from newsroom.increment6.execution import WorkerAttempt
from newsroom.increment6.dispositions import CurrentCandidateCitation
from newsroom.increment6.proposals import (
    HypothesisRelationship,
    PROPOSAL_SCHEMA_VERSION,
    TriageProposal,
    WorkerKind,
)
from newsroom.increment6.work_items import RetrievalBindingState, TriageWorkItemVersion


AUTONOMOUS_WORKER_VERSION = "newsroom-autonomous-triage-v2"
AUTONOMOUS_TRIAGE_POLICY_VERSION = "deterministic-source-revision-no-match-v1"
AUTONOMOUS_NATIVE_TRIAGE_POLICY_VERSION = (
    "deterministic-source-revision-current-candidate-collision-v3"
)


class AutonomousWorkerError(ValueError):
    """The worker inputs do not form one exact, truthful proposal request."""


def _policy_version(retrieval: object) -> str:
    try:
        request = json.loads(retrieval.request_bytes)
    except (AttributeError, TypeError, UnicodeError, json.JSONDecodeError):
        return AUTONOMOUS_TRIAGE_POLICY_VERSION
    if (
        type(request) is dict
        and request.get("schema_identity")
        == "newsroom.increment5.native-retrieval-context-request.v1"
    ):
        return AUTONOMOUS_NATIVE_TRIAGE_POLICY_VERSION
    return AUTONOMOUS_TRIAGE_POLICY_VERSION


def _exact_inputs(
    work_item_version: TriageWorkItemVersion,
    decision_leads: tuple[NewsLead, ...],
) -> tuple[TriageWorkItemVersion, tuple[NewsLead, ...]]:
    if type(work_item_version) is not TriageWorkItemVersion:
        raise AutonomousWorkerError("work item version must be exact typed")
    version = TriageWorkItemVersion.from_canonical_bytes(
        work_item_version.canonical_bytes
    )
    if type(decision_leads) is not tuple or any(
        type(lead) is not NewsLead for lead in decision_leads
    ):
        raise AutonomousWorkerError("decision Leads must be exact committed records")
    by_id = {str(lead.request.lead_id): lead for lead in decision_leads}
    if len(by_id) != len(decision_leads) or tuple(sorted(by_id)) != tuple(
        binding.lead_id for binding in version.decision_leads
    ):
        raise AutonomousWorkerError("decision Leads differ from the Work Item")
    for binding in version.decision_leads:
        lead = by_id[binding.lead_id]
        if (
            lead.canonical_digest != binding.lead_digest
            or str(lead.event_id) != binding.lead_event_id
            or lead.aggregate_version != binding.lead_aggregate_version
            or str(lead.request.definition_id) != binding.definition_id
            or str(lead.request.definition_version_id)
            != binding.definition_version_id
        ):
            raise AutonomousWorkerError(
                "decision Lead authority differs from the Work Item"
            )
    return version, tuple(by_id[key] for key in sorted(by_id))


def autonomous_worker_input_digest(
    work_item_version: TriageWorkItemVersion,
    decision_leads: tuple[NewsLead, ...],
    *,
    current_candidate: CurrentCandidateCitation | None = None,
    revision_relationship: HypothesisRelationship | None = None,
) -> str:
    """Digest the exact native inputs before creating the Worker Attempt."""

    version, leads = _exact_inputs(work_item_version, decision_leads)
    if (current_candidate is None) != (revision_relationship is None):
        raise AutonomousWorkerError("Candidate citation and relationship are inseparable")
    if current_candidate is not None and type(current_candidate) is not CurrentCandidateCitation:
        raise AutonomousWorkerError("current Candidate citation must be exact typed")
    if revision_relationship not in {
        None,
        HypothesisRelationship.DEVELOPMENT_OF,
        HypothesisRelationship.SAME_STATE,
    }:
        raise AutonomousWorkerError("native revision relationship is unsupported")
    return digest_bytes(
        canonical_json_bytes(
            {
                "worker_version": AUTONOMOUS_WORKER_VERSION,
                "policy_version": _policy_version(version.retrieval),
                "work_item_version_digest": version.canonical_digest,
                "decision_leads": [
                    {
                        "lead_id": str(lead.request.lead_id),
                        "lead_digest": lead.canonical_digest,
                    }
                    for lead in leads
                ],
                "current_candidate_citation_digest": (
                    None if current_candidate is None else current_candidate.canonical_digest
                ),
                "revision_relationship": (
                    None if revision_relationship is None else revision_relationship.value
                ),
            }
        )
    )


def _operational_hold(retrieval: object) -> tuple[str, str]:
    state = getattr(retrieval, "state", None)
    outcome = getattr(retrieval, "outcome", None)
    no_match = getattr(retrieval, "no_match", False)
    if (
        state is RetrievalBindingState.RECEIPT
        and outcome == "COMPLETE"
        and no_match is False
    ):
        return (
            "WAIT_FOR_DEPENDENCY",
            "A governed retrieval match requires an exact prior-Hypothesis relationship.",
        )
    return (
        "RETRY_RETRIEVAL",
        "Resume after a complete governed Retrieval Context is retained.",
    )


def build_autonomous_proposal(
    *,
    work_item_version: TriageWorkItemVersion,
    attempt: WorkerAttempt,
    decision_leads: tuple[NewsLead, ...],
    current_candidate: CurrentCandidateCitation | None = None,
    revision_relationship: HypothesisRelationship | None = None,
) -> TriageProposal:
    """Build one deterministic untrusted proposal from exact native records."""

    version, leads = _exact_inputs(work_item_version, decision_leads)
    if type(attempt) is not WorkerAttempt:
        raise AutonomousWorkerError("worker attempt must be exact typed")
    attempt = WorkerAttempt.from_canonical_bytes(attempt.canonical_bytes)
    input_digest = autonomous_worker_input_digest(
        version,
        leads,
        current_candidate=current_candidate,
        revision_relationship=revision_relationship,
    )
    retrieval = version.retrieval
    expected_retrieval_digest = retrieval.context_digest or retrieval.request_digest
    if (
        attempt.worker_kind is not WorkerKind.AUTONOMOUS_DETERMINISTIC
        or attempt.worker_version != AUTONOMOUS_WORKER_VERSION
        or attempt.input_digest != input_digest
        or attempt.work_item_id != version.work_item_id
        or attempt.work_item_version_id != version.version_id
        or attempt.work_item_version_digest != version.canonical_digest
        or attempt.retrieval_context_digest != expected_retrieval_digest
    ):
        raise AutonomousWorkerError("worker attempt differs from the exact inputs")

    policy_version = _policy_version(retrieval)
    native_context = policy_version == AUTONOMOUS_NATIVE_TRIAGE_POLICY_VERSION
    is_successor = current_candidate is not None
    is_new = (
        retrieval.state is RetrievalBindingState.RECEIPT
        and retrieval.outcome == "COMPLETE"
        and (retrieval.no_match or native_context)
        and not is_successor
    )
    action_kind, hold_condition = _operational_hold(retrieval)
    lead_ids = [str(lead.request.lead_id) for lead in leads]
    shared_urgency = min(
        (lead.request.urgency.route for lead in leads),
        key=lambda value: ("URGENT", "TIME_SENSITIVE", "PLANNED", "ROUTINE").index(
            value.value
        ),
    ).value
    shared_governing_versions = sorted(
        {
            policy_version,
            *(lead.request.lead_policy.policy_version for lead in leads),
        }
    )
    recommendations: list[dict[str, object]] = []
    for lead in leads:
        lead_id = str(lead.request.lead_id)
        lead_bytes = lead.request.canonical_bytes
        if not lead_bytes or len(lead_bytes) > 262_144:
            raise AutonomousWorkerError("decision Lead exceeds the citation envelope")
        if revision_relationship is HypothesisRelationship.DEVELOPMENT_OF:
            route, manifest_kind, relationship = (
                "DEVELOPMENT_CANDIDATE", "DEVELOPMENT", "DEVELOPMENT_OF"
            )
            information = (
                "The directly retained maintained-source revision develops the current "
                "Candidate Hypothesis; independent evidence remains required."
            )
        elif revision_relationship is HypothesisRelationship.SAME_STATE:
            route, manifest_kind, relationship = (
                "ASSOCIATE_WITHOUT_CANDIDATE", None, "SAME_STATE"
            )
            information = (
                "The directly retained maintained-source revision preserves the current state."
            )
        else:
            route = "NEW_EVENT_CANDIDATE" if is_new else "OPERATIONAL_HOLD"
            manifest_kind = "NEW_EVENT" if is_new else None
            relationship = "NO_ADEQUATE_PRIOR_MATCH" if is_new else None
            information = (
                "The governed source revision is a provisional new-event candidate "
                "pending the current Story Candidate collision check."
                if native_context and not retrieval.no_match
                else (
                    "The governed source revision has no adequate prior retrieval match."
                    if is_new
                    else "The governed source revision requires further deterministic triage."
                )
            )
        citations: list[dict[str, object]] = [{
            "citation_id": f"citation:{lead_id}",
            "source_kind": "DECISION_LEAD",
            "source_id": lead_id,
            "source_digest": lead.canonical_digest,
            "field_path": "$",
            "byte_start": 0,
            "byte_end": len(lead_bytes),
            "quote_digest": digest_bytes(lead_bytes),
            "target_hypothesis_id": None,
        }]
        if current_candidate is not None:
            citations.append({
                "citation_id": current_candidate.citation_id,
                "source_kind": "CURRENT_CANDIDATE",
                "source_id": current_candidate.citation_id,
                "source_digest": current_candidate.canonical_digest,
                "field_path": "$",
                "byte_start": 0,
                "byte_end": len(current_candidate.canonical_bytes),
                "quote_digest": digest_bytes(current_candidate.canonical_bytes),
                "target_hypothesis_id": current_candidate.hypothesis_id,
            })
        citations.sort(key=lambda value: str(value["citation_id"]))
        recommendation: dict[str, object] = {
            "decision_lead_id": lead_id,
            "route": route,
            "confidence": {"decimal": "0.500000", "millionths": 500_000},
            "uncertainty": {"decimal": "0.500000", "millionths": 500_000},
            "input_citations": citations,
            "likely_new_information": information,
            "materiality_basis": (
                "The retained deterministic Gate promoted this source revision to a Lead."
            ),
            "missing_context": (
                ["Independent evidence has not yet been acquired"]
                if is_new or manifest_kind is not None else []
            ),
            "retrieval_incompleteness": (
                [] if is_new or is_successor else [hold_condition]
            ),
            "hypothesis": (
                {
                    "proposal_local_id": f"hypothesis:{version.work_item_id}",
                    "summary": (
                        "The governed source revision may describe a distinct new event; "
                        "current Candidate collision remains authoritative."
                        if native_context
                        else "The governed source revision may describe a distinct new event."
                    ),
                    "relationship_kind": relationship,
                    "target_hypothesis_id": (
                        None if current_candidate is None else current_candidate.hypothesis_id
                    ),
                }
                if is_new or is_successor
                else None
            ),
            "watch_action": None,
            "supplemental_action": None,
            "operational_action": (
                None
                if is_new or is_successor
                else {
                    "action_kind": action_kind,
                    "owner_id": None,
                    "dependency": (
                        "relationship-classification-policy"
                        if action_kind == "WAIT_FOR_DEPENDENCY"
                        else None
                    ),
                    "retry_condition": (
                        hold_condition if action_kind == "RETRY_RETRIEVAL" else None
                    ),
                    "review_condition": None,
                    "expiry_condition": None,
                }
            ),
            "candidate_manifest": (
                {
                    "manifest_kind": manifest_kind,
                    "contributing_lead_ids": lead_ids,
                    "proposed_geography": "SOURCE_DEFINED",
                    "proposed_category": "UNCLASSIFIED",
                    "urgency": shared_urgency,
                    "likely_new_information": information,
                    "reader_utility_basis": (
                        "Independent evidence should determine whether the governed transition warrants a story."
                    ),
                    "uncertainties": ["Independent evidence has not yet been acquired"],
                    "evidence_objectives": [
                        "Acquire independent evidence for the governed source transition"
                    ],
                    "governing_versions": shared_governing_versions,
                }
                if manifest_kind is not None
                else None
            ),
        }
        recommendations.append(recommendation)

    proposal = {
        "proposal_id": str(
            uuid.uuid5(
                uuid.NAMESPACE_URL,
                f"{AUTONOMOUS_WORKER_VERSION}|{attempt.attempt_id}|{input_digest}",
            )
        ),
        "work_item_binding": {
            "work_item_id": version.work_item_id,
            "work_item_version_id": version.version_id,
            "work_item_version_digest": version.canonical_digest,
        },
        "retrieval_context_binding": {
            "context_id": retrieval.context_id or retrieval.request_id,
            "context_digest": expected_retrieval_digest,
            "contract_digest": RETRIEVAL_CONTEXT_CONTRACT_DIGEST,
        },
        "worker_attempt_binding": attempt.proposal_binding.canonical_value(),
        "decision_lead_ids": lead_ids,
        "context_lead_ids": [lead.lead_id for lead in version.context_leads],
        "recommendations": recommendations,
        "rationale": (
            "A deterministic provider-free worker applied the retained retrieval outcome; "
            "the proposal remains untrusted and requires native disposition authority."
        ),
        "authority": {
            "effect": "NONE",
            "creates_hypothesis": False,
            "creates_candidate": False,
            "mutates_editorial_state": False,
            "publication_authority": False,
            "evidence_authority": False,
            "operational_authority": False,
        },
    }
    document = {
        "schema_version": PROPOSAL_SCHEMA_VERSION,
        "content_identity": digest_bytes(
            canonical_json_bytes(
                {"schema_version": PROPOSAL_SCHEMA_VERSION, "proposal": proposal}
            )
        ),
        "proposal": proposal,
    }
    return TriageProposal.from_canonical_bytes(canonical_json_bytes(document))


__all__ = [
    "AUTONOMOUS_NATIVE_TRIAGE_POLICY_VERSION",
    "AUTONOMOUS_TRIAGE_POLICY_VERSION",
    "AUTONOMOUS_WORKER_VERSION",
    "AutonomousWorkerError",
    "autonomous_worker_input_digest",
    "build_autonomous_proposal",
]
