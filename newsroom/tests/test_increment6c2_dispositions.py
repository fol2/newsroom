from __future__ import annotations

import itertools
import json
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from collections.abc import Iterator, Mapping
from dataclasses import fields, replace

import pytest

from newsroom.authority.auth import AuthenticationProof, StaticAuthenticator, StaticPrincipal
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.triage_disposition_migrations import (
    TRIAGE_DISPOSITION_MIGRATION_STATEMENTS,
)
from newsroom.increment5.retrieval_context import RETRIEVAL_CONTEXT_CONTRACT_DIGEST
from newsroom.increment6 import dispositions as dispositions_module
from newsroom.increment6.dispositions import (
    DISPOSITION_AUTHORITY,
    MAX_DISPOSITION_CANONICAL_BYTES,
    PROPOSAL_DISPOSITION,
    PROPOSAL_DISPOSITION_SCHEMA_VERSION,
    PROPOSAL_VALIDATION_FINDING,
    PROPOSAL_VALIDATION_FINDING_SCHEMA_VERSION,
    VALIDATED_PROPOSAL_LEAD_DISPOSITION_BINDING,
    DispositionAuthority,
    DispositionContractError,
    DispositionJudgement,
    LeadDispositionHeadBinding,
    ProposalDisposition,
    ProposalDispositionStore,
    ProposalValidationFinding,
    ValidatorInputBinding,
    build_pending_dispositions,
    validate_proposal,
)
from newsroom.increment6.work_items import (
    ContextLeadBinding,
    RetrievalContextAuthority,
    RetrievalInputBinding,
    TriageWorkItem,
)
from newsroom.tests import test_increment5d1_hybrid_composer as composer_helpers
from newsroom.tests import test_increment5d2_retrieval_context as retrieval_helpers
from newsroom.tests import test_increment6a2_work_items as work_item_helpers
from newsroom.increment6.outcomes import (
    CanonicalNextAction,
    CanonicalOutcome,
    DecisionTerminality,
    NextAction,
    ReasonBasisClass,
    ReasonCode,
    ReasonReference,
    StructuredReason,
    OutcomeSelection,
)
from newsroom.increment6.proposals import (
    CandidateManifest,
    InputCitation,
    LeadRecommendation,
    MAX_CONTEXT_LEADS,
    MAX_DECISION_LEADS,
    MAX_INPUT_CITATIONS,
    MAX_LIST_ITEMS,
    MAX_RATIONALE_BYTES,
    MAX_TEXT_BYTES,
    PROPOSAL_SCHEMA_VERSION,
    ProposalRoute,
    TriageProposal,
)


DIGEST_A = "sha256:" + "a" * 64
DIGEST_B = "sha256:" + "b" * 64
DIGEST_C = "sha256:" + "c" * 64
DIGEST_D = "sha256:" + "d" * 64
LEAD_A = "11111111-1111-4111-8111-111111111111"
LEAD_B = "22222222-2222-4222-8222-222222222222"


def _recommendation(lead_id: str, route: str = "NEW_EVENT_CANDIDATE") -> dict[str, object]:
    value: dict[str, object] = {
        "decision_lead_id": lead_id,
        "route": route,
        "confidence": {"decimal": "0.750000", "millionths": 750_000},
        "uncertainty": {"decimal": "0.125000", "millionths": 125_000},
        "input_citations": [{
            "citation_id": f"citation:{lead_id[:4]}", "source_kind": "DECISION_LEAD",
            "source_id": lead_id, "source_digest": DIGEST_B, "field_path": "lead.summary",
            "byte_start": 0, "byte_end": 18, "quote_digest": DIGEST_D,
            "target_hypothesis_id": None,
        }, {
            "citation_id": f"retrieval:{lead_id[:4]}", "source_kind": "RETRIEVAL_MATCH",
            "source_id": f"passage:{lead_id[:4]}", "source_digest": DIGEST_C,
            "field_path": "passage.text", "byte_start": 0, "byte_end": 18,
            "quote_digest": DIGEST_D, "target_hypothesis_id": None,
        }],
        "likely_new_information": "A material new state may have occurred.",
        "materiality_basis": "The possible change may affect readers.",
        "missing_context": [], "retrieval_incompleteness": [],
        "hypothesis": None, "watch_action": None, "supplemental_action": None,
        "operational_action": None, "candidate_manifest": None,
    }
    if route == "WATCH_DEFER":
        value["watch_action"] = {"condition_kind": "SOURCE_UPDATE", "condition": "Resume when the named source changes.", "next_action": "REENTER_DISCOVERY"}
    elif route == "SUPPLEMENTAL_DISCOVERY":
        value["supplemental_action"] = {"action_kind": "CHECK_NAMED_SOURCE", "scope": "The primary organisation newsroom", "maximum_attempts": 1, "requires_approval": True}
    elif route == "OPERATIONAL_HOLD":
        value["operational_action"] = {"action_kind": "RETRY_RETRIEVAL", "owner_id": None, "dependency": None, "retry_condition": "Retry after service recovery.", "review_condition": None, "expiry_condition": None}
    elif route == "ASSOCIATE_WITHOUT_CANDIDATE":
        target = "44444444-4444-4444-8444-444444444444"
        value["hypothesis"] = {"proposal_local_id": f"hypothesis:{lead_id[:4]}", "summary": "The lead concerns a prior state.", "relationship_kind": "SAME_STATE", "target_hypothesis_id": target}
        value["input_citations"][1]["target_hypothesis_id"] = target
    elif route.endswith("_CANDIDATE"):
        kind, relationship, target = {
            "NEW_EVENT_CANDIDATE": ("NEW_EVENT", "NO_ADEQUATE_PRIOR_MATCH", None),
            "DEVELOPMENT_CANDIDATE": ("DEVELOPMENT", "DEVELOPMENT_OF", "44444444-4444-4444-8444-444444444444"),
            "CORRECTION_CANDIDATE": ("CORRECTION", "CORRECTION_REVERSAL_OF", "44444444-4444-4444-8444-444444444444"),
        }[route]
        value["hypothesis"] = {"proposal_local_id": f"hypothesis:{lead_id[:4]}", "summary": "A proposed event relationship.", "relationship_kind": relationship, "target_hypothesis_id": target}
        if target is not None:
            value["input_citations"][1]["target_hypothesis_id"] = target
        value["candidate_manifest"] = {"manifest_kind": kind, "contributing_lead_ids": [lead_id], "proposed_geography": "GB", "proposed_category": "UK_NEWS", "urgency": "ROUTINE", "likely_new_information": value["likely_new_information"], "reader_utility_basis": "Readers need the change.", "uncertainties": ["Unverified"], "evidence_objectives": ["Confirm independently"], "governing_versions": ["candidate-policy-v1"]}
    return value


def _proposal_bytes(routes: tuple[str, ...] = ("NEW_EVENT_CANDIDATE",)) -> bytes:
    available_leads = (
        (LEAD_A, LEAD_B)
        if len(routes) <= 2
        else tuple(
            f"00000000-0000-4000-8000-{index:012d}"
            for index in range(1, 33)
        )
    )
    leads = available_leads[:len(routes)]
    proposal: dict[str, object] = {
        "proposal_id": "84d0ae8c-1378-4b76-8792-1bb805ab6a91",
        "work_item_binding": {"work_item_id": "4d3b1b83-205e-4f77-a46b-ffbf5509d254", "work_item_version_id": "c37c30fd-cfab-4a57-ab69-a72515ebaa31", "work_item_version_digest": DIGEST_D},
        "retrieval_context_binding": {"context_id": "3d2f3791-c365-47f6-b543-65ecfd6b0eba", "context_digest": DIGEST_A, "contract_digest": RETRIEVAL_CONTEXT_CONTRACT_DIGEST},
        "worker_attempt_binding": {"attempt_id": "attempt:fixture:0001", "attempt_digest": DIGEST_C, "worker_kind": "FAKE", "worker_version": "fixture-worker-v1", "input_digest": DIGEST_B, "work_item_version_digest": DIGEST_D, "retrieval_context_digest": DIGEST_A},
        "decision_lead_ids": list(leads), "context_lead_ids": [],
        "recommendations": [_recommendation(lead, route) for lead, route in zip(leads, routes, strict=True)],
        "rationale": "A bounded triage recommendation.",
        "authority": {"effect": "NONE", "creates_hypothesis": False, "creates_candidate": False, "mutates_editorial_state": False, "publication_authority": False, "evidence_authority": False, "operational_authority": False},
    }
    identity = {"schema_version": PROPOSAL_SCHEMA_VERSION, "proposal": proposal}
    return canonical_json_bytes({**identity, "content_identity": digest_bytes(canonical_json_bytes(identity))})


def _resign(document: dict[str, object]) -> bytes:
    identity = {"schema_version": PROPOSAL_SCHEMA_VERSION, "proposal": document["proposal"]}
    document["content_identity"] = digest_bytes(canonical_json_bytes(identity))
    return canonical_json_bytes(document)


def _reviewed_large_producer_payload() -> bytes:
    """Reproduce the reviewed legal eight-Lead #356 payload's exact size."""

    raw = _proposal_bytes(("EDITORIAL_REJECT",) * 8)
    document = json.loads(raw)
    recommendations = document["proposal"]["recommendations"]
    for recommendation in recommendations:
        lead_id = recommendation["decision_lead_id"]
        recommendation["input_citations"] = [
            {
                "citation_id": f"citation:{index:03d}:" + "c" * 230,
                "source_kind": "DECISION_LEAD" if index == 0 else "RETRIEVAL_MATCH",
                "source_id": lead_id if index == 0 else f"passage:{index:03d}:" + "p" * 230,
                "source_digest": DIGEST_B,
                "field_path": f"passage:{index:03d}." + "f" * 230,
                "byte_start": index * 20,
                "byte_end": index * 20 + 18,
                "quote_digest": DIGEST_D,
                "target_hypothesis_id": None,
            }
            for index in range(64)
        ]
        recommendation["likely_new_information"] = "n" * 1_024
        recommendation["materiality_basis"] = "m" * 1_024
        recommendation["missing_context"] = [
            f"{index:02d}:" + "x" * 1_020 for index in range(32)
        ]
        recommendation["retrieval_incompleteness"] = [
            f"{index:02d}:" + "y" * 1_020 for index in range(32)
        ]
    document["proposal"]["rationale"] = "r" * 4_096

    target_size = 1_103_922
    deficit = target_size - len(_resign(document))
    for recommendation in recommendations:
        for citation in recommendation["input_citations"]:
            for field, fill in (("field_path", "f"), ("citation_id", "c"), ("source_id", "p")):
                if field == "source_id" and citation["source_kind"] == "DECISION_LEAD":
                    continue
                available = 256 - len(citation[field].encode("utf-8"))
                addition = min(deficit, available)
                citation[field] += fill * addition
                deficit -= addition
                if deficit == 0:
                    raw = _resign(document)
                    assert len(raw) == target_size
                    return raw
    raise AssertionError("reviewed producer payload could not reach its exact size")


def _validator(raw: bytes | None = None) -> ValidatorInputBinding:
    return ValidatorInputBinding.for_proposal(
        proposal_bytes=_proposal_bytes() if raw is None else raw,
        validator_id="validator:fixture", validator_version="1",
        authenticated_context_identity=DIGEST_A,
        retrieval_request_id="request:001", retrieval_request_digest=DIGEST_B,
        retrieval_receipt_id="receipt:001", retrieval_receipt_digest=DIGEST_C,
        ruleset_id="triage-rules", ruleset_version="1", ruleset_digest=DIGEST_D,
    )


def _selection(outcome: CanonicalOutcome, action: CanonicalNextAction, reason: ReasonCode, terminality: DecisionTerminality = DecisionTerminality.TERMINAL_EXACT_VERSION) -> OutcomeSelection:
    return OutcomeSelection(
        outcome=outcome, terminality=terminality,
        primary_reason=StructuredReason(code=reason, basis=ReasonBasisClass.DETERMINISTIC_POLICY, references=(ReasonReference("proposal", "proposal:1", DIGEST_A),), explanation="Exact proposal route policy."),
        supporting_reasons=(),
        next_action=NextAction(action.kind, action, "condition:1" if action.kind.value in {"RETRY", "REVIEW", "WAIT_DEPENDENCY", "RESUME_ON_WATCH", "REQUEST_SUPPLEMENTAL_DISCOVERY"} else None),
    )


def _persistable_proposal(version: object, decision: object, receipt: object) -> bytes:
    document = json.loads(_proposal_bytes())
    proposal = document["proposal"]
    proposal["work_item_binding"] = {
        "work_item_id": version.work_item_id,
        "work_item_version_id": version.version_id,
        "work_item_version_digest": version.canonical_digest,
    }
    proposal["retrieval_context_binding"] = {
        "context_id": str(receipt.context_id),
        "context_digest": receipt.receipt_digest,
        "contract_digest": RETRIEVAL_CONTEXT_CONTRACT_DIGEST,
    }
    proposal["worker_attempt_binding"]["work_item_version_digest"] = (
        version.canonical_digest
    )
    proposal["worker_attempt_binding"]["retrieval_context_digest"] = (
        receipt.receipt_digest
    )
    proposal["decision_lead_ids"] = [decision.lead_id]
    recommendation = proposal["recommendations"][0]
    recommendation["decision_lead_id"] = decision.lead_id
    recommendation["input_citations"][0]["source_id"] = decision.lead_id
    recommendation["input_citations"][0]["source_digest"] = decision.lead_digest
    item = receipt.items[0]
    text = item.text.encode("utf-8")
    recommendation["input_citations"][1].update({
        "source_id": item.passage.passage_id,
        "source_digest": item.passage.text_digest,
        "byte_start": 0,
        "byte_end": len(text),
        "quote_digest": digest_bytes(text),
    })
    proposal["context_lead_ids"] = [lead.lead_id for lead in version.context_leads]
    recommendation["input_citations"].extend({
        "citation_id": f"context:{lead.lead_id[:4]}",
        "source_kind": "CONTEXT_LEAD",
        "source_id": lead.lead_id,
        "source_digest": lead.lead_digest,
        "field_path": "lead.summary",
        "byte_start": 0,
        "byte_end": 18,
        "quote_digest": DIGEST_D,
        "target_hypothesis_id": None,
    } for lead in version.context_leads)
    recommendation["input_citations"].sort(key=lambda citation: citation["citation_id"])
    recommendation["candidate_manifest"]["contributing_lead_ids"] = [
        decision.lead_id
    ]
    return _resign(document)


def test_v19_store_exact_success_replay_restart_and_use_time_currentness(tmp_path) -> None:
    inputs = composer_helpers.branch_inputs.__wrapped__(tmp_path)
    (
        builder,
        _composer,
        _cas_root,
        _journal,
        _journal_path,
        request,
        receipt,
        _content,
    ) = retrieval_helpers._retained_complete_context(
        tmp_path, inputs, name="disposition-authority"
    )
    authority = RetrievalContextAuthority(
        builder.journal.path, {request.request_digest: (request, receipt)}
    )
    decision, context_source = (
        work_item_helpers._decision(1), work_item_helpers._decision(2)
    )
    connection, work_store = work_item_helpers._store(
        (decision, context_source), retrieval_authority=authority
    )
    item = TriageWorkItem.create((decision,))
    version = replace(
        work_item_helpers._version(item),
        context_leads=(ContextLeadBinding(
            context_source.lead_id, context_source.lead_digest,
            context_source.lead_event_id, context_source.lead_aggregate_version,
            context_source.gate_decision_id, context_source.definition_id,
            context_source.definition_version_id,
        ),),
        retrieval=RetrievalInputBinding.from_receipt(request, receipt),
    )
    work_store.create_or_replay(item, version)
    for statement in TRIAGE_DISPOSITION_MIGRATION_STATEMENTS:
        connection.execute(statement)
    authenticator = StaticAuthenticator(
        credentials={"credential": StaticPrincipal("editor")},
        authority_domain="newsroom.dispositions",
    )
    proof = AuthenticationProof(method="STATIC_TOKEN", credential="credential")
    store = ProposalDispositionStore(connection, authority, authenticator)
    proposal = _persistable_proposal(version, decision, receipt)
    context_mismatch = json.loads(proposal)
    context_mismatch["proposal"]["context_lead_ids"] = []
    context_mismatch["proposal"]["recommendations"][0]["input_citations"] = [
        citation for citation in context_mismatch["proposal"]["recommendations"][0]["input_citations"]
        if citation["source_kind"] != "CONTEXT_LEAD"
    ]
    with pytest.raises(DispositionContractError, match="exact current Work Item"):
        store.persist(_resign(context_mismatch), {}, proof=proof)
    assert connection.in_transaction is False
    for mutator in (
        lambda citation: citation.update(source_digest=DIGEST_A),
        lambda citation: citation.update(source_id="invented-passage"),
        lambda citation: citation.update(byte_end=citation["byte_end"] - 1),
        lambda citation: citation.update(quote_digest=DIGEST_A),
    ):
        mismatched = json.loads(proposal)
        retrieval_citation = next(
            citation for citation in mismatched["proposal"]["recommendations"][0]["input_citations"]
            if citation["source_kind"] == "RETRIEVAL_MATCH"
        )
        mutator(retrieval_citation)
        with pytest.raises(DispositionContractError, match="citation"):
            store.persist(_resign(mismatched), {}, proof=proof)
        assert connection.execute(
            "SELECT COUNT(*) FROM triage_proposal_validation_findings"
        ).fetchone() == (0,)
        assert connection.execute(
            "SELECT COUNT(*) FROM triage_proposal_dispositions"
        ).fetchone() == (0,)
    for source_kind in ("DECISION_LEAD", "CONTEXT_LEAD"):
        mismatched = json.loads(proposal)
        citation = next(
            citation for citation in mismatched["proposal"]["recommendations"][0]["input_citations"]
            if citation["source_kind"] == source_kind
        )
        citation["source_digest"] = DIGEST_A
        with pytest.raises(DispositionContractError, match="citation"):
            store.persist(_resign(mismatched), {}, proof=proof)
        assert connection.execute(
            "SELECT COUNT(*) FROM triage_proposal_validation_findings"
        ).fetchone() == (0,)
    selection = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )
    competing_document = json.loads(proposal)
    competing_document["proposal"]["proposal_id"] = (
        "00000000-0000-4000-8000-000000009998"
    )
    competing = _resign(competing_document)

    race_database = tmp_path / "empty-race-dispositions.sqlite3"
    race_target = sqlite3.connect(race_database, isolation_level=None)
    connection.backup(race_target)
    race_target.close()
    race_connections = tuple(
        sqlite3.connect(
            race_database,
            isolation_level=None,
            timeout=10,
            check_same_thread=False,
        )
        for _ in range(2)
    )
    race_stores = tuple(
        ProposalDispositionStore(candidate, authority, authenticator)
        for candidate in race_connections
    )
    barrier = threading.Barrier(2)

    def competing_first_write(
        candidate_store: ProposalDispositionStore, candidate: bytes
    ) -> tuple[ProposalDisposition, ...] | str:
        barrier.wait()
        try:
            return candidate_store.persist(
                candidate, {decision.lead_id: selection}, proof=proof
            )
        except DispositionContractError as exc:
            return str(exc)

    with ThreadPoolExecutor(max_workers=2) as executor:
        race_results = tuple(
            future.result()
            for future in (
                executor.submit(competing_first_write, race_stores[0], proposal),
                executor.submit(competing_first_write, race_stores[1], competing),
            )
        )
    winners = tuple(result for result in race_results if type(result) is tuple)
    losers = tuple(result for result in race_results if type(result) is str)
    assert len(winners) == len(losers) == 1
    assert "finding replay diverges" in losers[0]
    assert race_connections[0].execute(
        "SELECT COUNT(*) FROM triage_proposal_validation_findings"
    ).fetchone() == (1,)
    assert race_connections[0].execute(
        "SELECT COUNT(*) FROM triage_proposal_dispositions"
    ).fetchone() == (1,)
    winner_id = winners[0][0].proposal_id
    winner_proposal = (
        proposal
        if winner_id == json.loads(proposal)["proposal"]["proposal_id"]
        else competing
    )
    for race_connection in race_connections:
        race_connection.close()
    reopened_race_connection = sqlite3.connect(
        race_database, isolation_level=None, timeout=10
    )
    reopened_race = ProposalDispositionStore(
        reopened_race_connection, authority, authenticator
    )
    assert reopened_race.persist(
        winner_proposal, {decision.lead_id: selection}, proof=proof
    ) == winners[0]
    reopened_race_connection.close()

    first = store.persist(proposal, {decision.lead_id: selection}, proof=proof)
    assert len(first) == 1
    assert first[0].authority is DispositionAuthority.NONE
    assert store.persist(proposal, {decision.lead_id: selection}, proof=proof) == first
    assert store.require_current(first[0].disposition_id, proof=proof) == first[0]
    assert connection.execute(
        "SELECT COUNT(*) FROM triage_proposal_validation_findings"
    ).fetchone() == (1,)
    assert connection.execute(
        "SELECT COUNT(*) FROM triage_proposal_dispositions"
    ).fetchone() == (1,)
    divergent = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.REL_NO_ADEQUATE_PRIOR_MATCH,
    )
    with pytest.raises(DispositionContractError, match="replay diverges"):
        store.persist(proposal, {decision.lead_id: divergent}, proof=proof)
    assert connection.execute(
        "SELECT COUNT(*) FROM triage_proposal_dispositions"
    ).fetchone() == (1,)

    with pytest.raises(DispositionContractError, match="replay diverges"):
        store.persist(competing, {decision.lead_id: selection}, proof=proof)
    assert connection.execute(
        "SELECT COUNT(*) FROM triage_proposal_validation_findings"
    ).fetchone() == (1,)
    assert connection.execute(
        "SELECT COUNT(*) FROM triage_proposal_dispositions"
    ).fetchone() == (1,)

    interrupted = proposal
    store._persist_dispositions = lambda *_args: (_ for _ in ()).throw(  # type: ignore[method-assign]
        GeneratorExit()
    )
    with pytest.raises(GeneratorExit):
        store.persist(interrupted, {decision.lead_id: selection}, proof=proof)
    del store._persist_dispositions
    assert connection.execute(
        "SELECT COUNT(*) FROM triage_proposal_validation_findings"
    ).fetchone() == (1,)
    assert connection.in_transaction is False
    with pytest.raises(DispositionContractError, match="authentication"):
        store.require_current(
            first[0].disposition_id,
            proof=AuthenticationProof(method="STATIC_TOKEN", credential="wrong"),
        )

    database = tmp_path / "restarted-dispositions.sqlite3"
    target = sqlite3.connect(database, isolation_level=None)
    connection.backup(target)
    target.close()
    first_connection = sqlite3.connect(database, isolation_level=None, timeout=10)
    second_connection = sqlite3.connect(database, isolation_level=None, timeout=10)
    first_restarted = ProposalDispositionStore(
        first_connection, authority, authenticator
    )
    second_restarted = ProposalDispositionStore(
        second_connection, authority, authenticator
    )
    assert first_restarted.persist(
        proposal, {decision.lead_id: selection}, proof=proof
    ) == first
    assert second_restarted.persist(
        proposal, {decision.lead_id: selection}, proof=proof
    ) == first
    first_connection.close()
    second_connection.close()


def test_v19_reopen_rejects_self_consistent_finding_route_cross_link(tmp_path) -> None:
    inputs = composer_helpers.branch_inputs.__wrapped__(tmp_path)
    builder, _, _, _, _, request, receipt, _ = retrieval_helpers._retained_complete_context(
        tmp_path, inputs, name="disposition-cross-link"
    )
    authority = RetrievalContextAuthority(
        builder.journal.path, {request.request_digest: (request, receipt)}
    )
    decision = work_item_helpers._decision(1)
    connection, work_store = work_item_helpers._store(
        (decision,), retrieval_authority=authority
    )
    item = TriageWorkItem.create((decision,))
    version = replace(
        work_item_helpers._version(item),
        retrieval=RetrievalInputBinding.from_receipt(request, receipt),
    )
    work_store.create_or_replay(item, version)
    for statement in TRIAGE_DISPOSITION_MIGRATION_STATEMENTS:
        connection.execute(statement)
    authenticator = StaticAuthenticator(
        credentials={"credential": StaticPrincipal("editor")},
        authority_domain="newsroom.dispositions",
    )
    proof = AuthenticationProof(method="STATIC_TOKEN", credential="credential")
    store = ProposalDispositionStore(connection, authority, authenticator)
    stored = store.persist(
        _persistable_proposal(version, decision, receipt),
        {decision.lead_id: _selection(
            CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
            CanonicalNextAction.HANDOFF_FOR_EVALUATION,
            ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
        )},
        proof=proof,
    )[0]
    finding_raw = connection.execute(
        "SELECT canonical_bytes FROM triage_proposal_validation_findings"
    ).fetchone()[0]
    finding_doc = json.loads(bytes(finding_raw))
    finding_doc["finding"]["evidence_reference_digest"] = DIGEST_A
    finding_identity = dict(finding_doc["finding"])
    finding_identity.pop("finding_id")
    new_finding_id = digest_bytes(canonical_json_bytes(finding_identity))
    finding_doc["finding"]["finding_id"] = new_finding_id
    new_finding_raw = canonical_json_bytes(finding_doc)
    new_finding_set = digest_bytes(canonical_json_bytes({
        "schema_version": "newsroom.increment6.triage-proposal-finding-set.v1",
        "proposal_content_identity": stored.proposal_content_identity,
        "validator_input_binding": stored.validator_input.canonical_value(),
        "finding_ids": [new_finding_id],
        "authority": "NONE",
    }))
    disposition_doc = json.loads(stored.canonical_bytes)
    disposition_doc["disposition"]["finding_set_digest"] = new_finding_set
    disposition_identity = dict(disposition_doc["disposition"])
    disposition_identity.pop("disposition_id")
    new_disposition_id = digest_bytes(canonical_json_bytes(disposition_identity))
    disposition_doc["disposition"]["disposition_id"] = new_disposition_id
    new_disposition_raw = canonical_json_bytes(disposition_doc)

    connection.execute("DROP TRIGGER immutable_triage_proposal_findings_update")
    connection.execute("DROP TRIGGER immutable_triage_proposal_dispositions_update")
    connection.execute("PRAGMA foreign_keys=OFF")
    connection.execute(
        "UPDATE triage_proposal_validation_findings SET finding_id=?,finding_set_digest=?,"
        "canonical_bytes=?,canonical_digest=?",
        (new_finding_id, new_finding_set, new_finding_raw, digest_bytes(new_finding_raw)),
    )
    connection.execute(
        "UPDATE triage_proposal_dispositions SET disposition_id=?,finding_set_digest=?,"
        "finding_id=?,canonical_bytes=?,canonical_digest=?",
        (new_disposition_id, new_finding_set, new_finding_id, new_disposition_raw,
         digest_bytes(new_disposition_raw)),
    )
    connection.execute("PRAGMA foreign_keys=ON")

    with pytest.raises(DispositionContractError, match="finding linkage"):
        ProposalDispositionStore(connection, authority, authenticator)
    assert connection.in_transaction is False


def test_public_allocation_and_no_authority_are_exact() -> None:
    assert PROPOSAL_VALIDATION_FINDING == PROPOSAL_VALIDATION_FINDING_SCHEMA_VERSION == "newsroom.increment6.triage-proposal-finding.v1"
    assert PROPOSAL_DISPOSITION == PROPOSAL_DISPOSITION_SCHEMA_VERSION == "newsroom.increment6.triage-proposal-disposition.v1"
    assert DISPOSITION_AUTHORITY is DispositionAuthority
    assert VALIDATED_PROPOSAL_LEAD_DISPOSITION_BINDING == "EXACT_PROPOSAL_FINDING_SET_AND_CURRENT_LEAD_HEAD"
    assert set(DispositionAuthority) == {DispositionAuthority.NONE, DispositionAuthority.PENDING}


def test_validation_findings_are_canonical_deterministic_and_permutation_invariant() -> None:
    raw = _proposal_bytes(("NEW_EVENT_CANDIDATE", "NEW_EVENT_CANDIDATE"))
    first = validate_proposal(raw, _validator(raw))
    second = validate_proposal(raw, _validator(raw))
    assert first.canonical_bytes == second.canonical_bytes
    assert first.finding_set_digest == second.finding_set_digest
    assert len(first.findings) == 2
    assert tuple(item.finding_id for item in first.findings) == tuple(sorted(item.finding_id for item in first.findings))
    parsed = ProposalValidationFinding.from_canonical_bytes(first.findings[0].canonical_bytes)
    assert parsed == first.findings[0]
    assert parsed.authority is DispositionAuthority.NONE
    assert parsed.authorises_persistence is False


@pytest.mark.parametrize("mutation", ["unknown", "tamper", "duplicate", "depth", "size"])
def test_validation_input_fails_closed_for_noncanonical_or_unbounded_json(mutation: str) -> None:
    raw = _proposal_bytes()
    if mutation == "unknown":
        value = json.loads(raw); value["unknown"] = True; raw = canonical_json_bytes(value)
    elif mutation == "tamper":
        value = json.loads(raw); value["proposal"]["rationale"] = "Changed"; raw = canonical_json_bytes(value)
    elif mutation == "duplicate":
        raw = raw[:-1] + b',"schema_version":"newsroom.increment6.triage-proposal.v1"}'
    elif mutation == "depth":
        raw = b'[' * 70 + b'0' + b']' * 70
    else:
        raw = b" " * 1_100_000
    with pytest.raises(DispositionContractError, match="integrity"):
        validate_proposal(raw, _validator())


def test_validator_identity_ruleset_receipt_and_input_are_all_bound() -> None:
    result = validate_proposal(_proposal_bytes(), _validator())
    value = result.findings[0].canonical_value()["finding"]
    assert value["validator_input_binding"] == _validator().canonical_value()
    assert _validator().authority is DispositionAuthority.PENDING
    assert _validator().authorises_persistence is False
    for field in ("authenticated_context_identity", "ruleset_digest", "input_digest", "retrieval_receipt_digest"):
        with pytest.raises(DispositionContractError):
            replace(_validator(), **{field: "forged"})
    mismatched = replace(_validator(), input_digest=DIGEST_B)
    with pytest.raises(DispositionContractError, match="validation envelope"):
        validate_proposal(_proposal_bytes(), mismatched)


ROUTE_MATRIX = {
    ProposalRoute.EDITORIAL_REJECT: (DispositionJudgement.REJECT, CanonicalOutcome.LEAD_EDITORIAL_REJECT, CanonicalNextAction.CLOSE_DECISION, ReasonCode.NOVELTY_EXACT_DUPLICATE, DecisionTerminality.TERMINAL_EXACT_VERSION),
    ProposalRoute.WATCH_DEFER: (DispositionJudgement.HOLD, CanonicalOutcome.LEAD_WATCH_DEFER, CanonicalNextAction.AWAIT_WATCH_CONDITION, ReasonCode.TIME_WATCH_REVIEW, DecisionTerminality.PENDING_CONDITION),
    ProposalRoute.ASSOCIATE_WITHOUT_CANDIDATE: (DispositionJudgement.ACCEPT, CanonicalOutcome.LEAD_ASSOCIATE_WITHOUT_CANDIDATE, CanonicalNextAction.CLOSE_DECISION, ReasonCode.REL_SAME_STATE, DecisionTerminality.TERMINAL_EXACT_VERSION),
    ProposalRoute.SUPPLEMENTAL_DISCOVERY: (DispositionJudgement.ESCALATE, CanonicalOutcome.LEAD_SUPPLEMENTAL_DISCOVERY, CanonicalNextAction.REQUEST_SUPPLEMENTAL_DISCOVERY, ReasonCode.SEARCH_PARTIAL_RESULTS, DecisionTerminality.PENDING_CONDITION),
    ProposalRoute.OPERATIONAL_HOLD: (DispositionJudgement.HOLD, CanonicalOutcome.LEAD_OPERATIONAL_HOLD, CanonicalNextAction.WAIT_FOR_DEPENDENCY, ReasonCode.OPS_RETRIEVAL, DecisionTerminality.PENDING_CONDITION),
    ProposalRoute.NEW_EVENT_CANDIDATE: (DispositionJudgement.ACCEPT, CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE, CanonicalNextAction.HANDOFF_FOR_EVALUATION, ReasonCode.NOVELTY_LIKELY_NEW_EVENT, DecisionTerminality.TERMINAL_EXACT_VERSION),
    ProposalRoute.DEVELOPMENT_CANDIDATE: (DispositionJudgement.ACCEPT, CanonicalOutcome.LEAD_ADMIT_DEVELOPMENT_CANDIDATE, CanonicalNextAction.HANDOFF_FOR_EVALUATION, ReasonCode.NOVELTY_LIKELY_DEVELOPMENT, DecisionTerminality.TERMINAL_EXACT_VERSION),
    ProposalRoute.CORRECTION_CANDIDATE: (DispositionJudgement.ACCEPT, CanonicalOutcome.LEAD_ADMIT_CORRECTION_CANDIDATE, CanonicalNextAction.HANDOFF_FOR_EVALUATION, ReasonCode.REL_CORRECTION_REVERSAL, DecisionTerminality.TERMINAL_EXACT_VERSION),
}


def test_exact_route_outcome_reason_action_matrix_and_cross_route_rejection() -> None:
    assert set(ROUTE_MATRIX) == set(ProposalRoute)
    # Proposal parsing already proves all route-specific action seams; exercise the
    # disposition matrix on the minimal new-event fixture and inspect all policies.
    result = validate_proposal(_proposal_bytes(), _validator())
    for route, (_, outcome, action, reason, terminality) in ROUTE_MATRIX.items():
        route_raw = _proposal_bytes((route.value,))
        route_result = validate_proposal(route_raw, _validator(route_raw))
        assert route_result.proposal.recommendations[0].route is route
        ProposalDisposition.validate_route_selection(route, _selection(outcome, action, reason, terminality))
        other_route = next(item for item in ProposalRoute if item is not route)
        _, wrong_outcome, wrong_action, wrong_reason, wrong_terminality = ROUTE_MATRIX[other_route]
        with pytest.raises(DispositionContractError, match="route matrix"):
            ProposalDisposition.validate_route_selection(route, _selection(wrong_outcome, wrong_action, wrong_reason, wrong_terminality))
    assert result.findings


def test_multi_lead_manifest_is_complete_and_dispositions_remain_pending() -> None:
    raw = _proposal_bytes(("NEW_EVENT_CANDIDATE", "NEW_EVENT_CANDIDATE"))
    validation = validate_proposal(raw, _validator(raw))
    heads = {
        LEAD_A: LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A),
        LEAD_B: LeadDispositionHeadBinding(LEAD_B, DIGEST_B, "head:b", DIGEST_B),
    }
    selections = {lead: _selection(CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE, CanonicalNextAction.HANDOFF_FOR_EVALUATION, ReasonCode.NOVELTY_LIKELY_NEW_EVENT) for lead in heads}
    dispositions = build_pending_dispositions(validation, heads, selections)
    assert tuple(item.decision_lead_id for item in dispositions) == (LEAD_A, LEAD_B)
    assert all(item.authority is DispositionAuthority.NONE for item in dispositions)
    assert all(not item.authorises_persistence and not item.authorises_external_effect for item in dispositions)
    assert ProposalDisposition.from_canonical_bytes(dispositions[0].canonical_bytes) == dispositions[0]
    canonical = dispositions[0].canonical_bytes
    unknown = json.loads(canonical)
    unknown["unknown"] = True
    tampered = json.loads(canonical)
    tampered["disposition"]["proposal_content_identity"] = DIGEST_B
    malformed = (
        canonical[:-1]
        + b',"schema_version":"newsroom.increment6.triage-proposal-disposition.v1"}'
    )
    for invalid in (
        canonical_json_bytes(unknown),
        canonical_json_bytes(tampered),
        malformed,
        b"[" * 70 + b"0" + b"]" * 70,
        b" " * 1_100_000,
    ):
        with pytest.raises(DispositionContractError):
            ProposalDisposition.from_canonical_bytes(invalid)
    with pytest.raises(DispositionContractError, match="complete"):
        build_pending_dispositions(validation, {LEAD_A: heads[LEAD_A]}, {LEAD_A: selections[LEAD_A]})


@pytest.mark.parametrize(
    ("route", "outcome", "action", "reason"),
    (
        (ProposalRoute.WATCH_DEFER, CanonicalOutcome.LEAD_WATCH_DEFER, CanonicalNextAction.AWAIT_WATCH_CONDITION, ReasonCode.TIME_WATCH_REVIEW),
        (ProposalRoute.SUPPLEMENTAL_DISCOVERY, CanonicalOutcome.LEAD_SUPPLEMENTAL_DISCOVERY, CanonicalNextAction.REQUEST_SUPPLEMENTAL_DISCOVERY, ReasonCode.SEARCH_PARTIAL_RESULTS),
        (ProposalRoute.OPERATIONAL_HOLD, CanonicalOutcome.LEAD_OPERATIONAL_HOLD, CanonicalNextAction.RETRY_SAME_REQUEST, ReasonCode.OPS_RETRIEVAL),
    ),
)
def test_conditional_routes_bind_the_exact_proposal_action_seam(
    route: ProposalRoute,
    outcome: CanonicalOutcome,
    action: CanonicalNextAction,
    reason: ReasonCode,
) -> None:
    raw = _proposal_bytes((route.value,))
    validation = validate_proposal(raw, _validator(raw))
    recommendation = validation.proposal.recommendations[0]
    route_digest = digest_bytes(canonical_json_bytes(recommendation.canonical_value()))
    terminality = DecisionTerminality.PENDING_CONDITION
    selection = _selection(outcome, action, reason, terminality)
    assert selection.next_action is not None
    exact = replace(
        selection,
        next_action=replace(selection.next_action, condition_reference=route_digest),
    )
    head = LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A)
    assert build_pending_dispositions(validation, {LEAD_A: head}, {LEAD_A: exact})
    with pytest.raises(DispositionContractError, match="exact route-specific"):
        build_pending_dispositions(validation, {LEAD_A: head}, {LEAD_A: selection})


def test_validator_rechecks_cross_lead_and_retrieval_citation_coherence() -> None:
    cross_lead = json.loads(_proposal_bytes(("NEW_EVENT_CANDIDATE", "NEW_EVENT_CANDIDATE")))
    first_manifest = cross_lead["proposal"]["recommendations"][0]["candidate_manifest"]
    first_manifest["contributing_lead_ids"] = [LEAD_A, LEAD_B]
    identity = {"schema_version": PROPOSAL_SCHEMA_VERSION, "proposal": cross_lead["proposal"]}
    cross_lead["content_identity"] = digest_bytes(canonical_json_bytes(identity))
    raw_cross = canonical_json_bytes(cross_lead)
    with pytest.raises(DispositionContractError, match="integrity"):
        validate_proposal(raw_cross, _validator(raw_cross))

    citation = json.loads(_proposal_bytes(("DEVELOPMENT_CANDIDATE",)))
    citation["proposal"]["recommendations"][0]["input_citations"][1]["target_hypothesis_id"] = "55555555-5555-4555-8555-555555555555"
    identity = {"schema_version": PROPOSAL_SCHEMA_VERSION, "proposal": citation["proposal"]}
    citation["content_identity"] = digest_bytes(canonical_json_bytes(identity))
    raw_citation = canonical_json_bytes(citation)
    with pytest.raises(DispositionContractError, match="integrity"):
        validate_proposal(raw_citation, _validator(raw_citation))


def test_operational_owner_mapping_and_ambiguous_action_are_inspectable() -> None:
    owner_only = json.loads(_proposal_bytes(("OPERATIONAL_HOLD",)))
    action = owner_only["proposal"]["recommendations"][0]["operational_action"]
    action.update({
        "action_kind": "REQUEST_REVIEW",
        "owner_id": "owner:newsroom",
        "dependency": None,
        "retry_condition": None,
        "review_condition": None,
    })
    raw_owner = _resign(owner_only)
    validation = validate_proposal(raw_owner, _validator(raw_owner))
    assert validation.findings[0].severity.value == "INFO"
    recommendation = validation.proposal.recommendations[0]
    route_digest = digest_bytes(canonical_json_bytes(recommendation.canonical_value()))
    selection = _selection(
        CanonicalOutcome.LEAD_OPERATIONAL_HOLD,
        CanonicalNextAction.REQUEST_REVIEW,
        ReasonCode.OPS_PARTIAL,
        DecisionTerminality.PENDING_CONDITION,
    )
    assert selection.next_action is not None
    selection = replace(selection, next_action=replace(selection.next_action, condition_reference=route_digest))
    head = LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A)
    assert build_pending_dispositions(validation, {LEAD_A: head}, {LEAD_A: selection})

    unsupported = json.loads(_proposal_bytes(("OPERATIONAL_HOLD",)))
    unsupported["proposal"]["recommendations"][0]["operational_action"].update({
        "action_kind": "DO_SOMETHING",
        "review_condition": "Review this condition.",
    })
    raw_unsupported = _resign(unsupported)
    invalid = validate_proposal(raw_unsupported, _validator(raw_unsupported))
    assert invalid.findings[0].code.value == "OPERATIONAL_ACTION_UNSUPPORTED"
    assert invalid.findings[0].severity.value == "ERROR"
    with pytest.raises(DispositionContractError, match="validation errors"):
        build_pending_dispositions(invalid, {LEAD_A: head}, {LEAD_A: selection})
    editorial_reject = _selection(
        CanonicalOutcome.LEAD_EDITORIAL_REJECT,
        CanonicalNextAction.CLOSE_DECISION,
        ReasonCode.NOVELTY_EXACT_DUPLICATE,
    )
    with pytest.raises(DispositionContractError, match="validation errors"):
        build_pending_dispositions(
            invalid, {LEAD_A: head}, {LEAD_A: editorial_reject}
        )


def test_integrity_failures_are_not_editorial_rejections_and_no_effect_type_is_reachable() -> None:
    with pytest.raises(DispositionContractError) as caught:
        validate_proposal(b"not-json", _validator())
    assert "EDITORIAL_REJECT" not in str(caught.value)
    assert "REJECT" not in str(caught.value)
    assert not hasattr(caught.value, "outcome")
    assert all(member.value in {"NONE", "PENDING"} for member in DispositionAuthority)


def test_lead_digest_mismatch_and_oversized_constructed_disposition_fail_closed(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    raw = _proposal_bytes()
    validation = validate_proposal(raw, _validator(raw))
    selection = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )
    wrong_head = LeadDispositionHeadBinding(LEAD_A, DIGEST_C, "head:a", DIGEST_A)
    with pytest.raises(DispositionContractError, match="Lead head digest"):
        build_pending_dispositions(
            validation, {LEAD_A: wrong_head}, {LEAD_A: selection}
        )

    exact_head = LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A)
    disposition = build_pending_dispositions(
        validation, {LEAD_A: exact_head}, {LEAD_A: selection}
    )[0]
    monkeypatch.setattr(
        dispositions_module,
        "MAX_DISPOSITION_CANONICAL_BYTES",
        len(disposition.canonical_bytes) - 1,
    )
    with pytest.raises(DispositionContractError, match="canonical byte bound"):
        build_pending_dispositions(
            validation, {LEAD_A: exact_head}, {LEAD_A: selection}
        )


def test_every_legal_producer_envelope_fits_the_public_consumer_bound(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    reviewed = _reviewed_large_producer_payload()
    assert len(reviewed) == 1_103_922
    assert TriageProposal.from_canonical_bytes(reviewed).canonical_bytes == reviewed
    reviewed_validation = validate_proposal(reviewed, _validator(reviewed))
    assert len(reviewed_validation.findings) == 8

    # #356 permits control bytes in bounded text. Canonical JSON therefore has
    # a worst-case six-byte escape expansion, not an ordinary UTF-8 1:1 ratio.
    escape_ratio = len(canonical_json_bytes("\x01" * MAX_TEXT_BYTES)) - 2
    assert escape_ratio == 6 * MAX_TEXT_BYTES
    assert (
        MAX_DECISION_LEADS,
        MAX_INPUT_CITATIONS,
        MAX_LIST_ITEMS,
    ) == (32, 64, 32)

    # One citation's bounded strings, digests, UUID and integers total less than
    # MAX_TEXT_BYTES. The actual 32-Lead Candidate skeleton accounts for every
    # schema key, delimiter, fixed value and collection boundary. The named slot
    # counts below cover every dominant closed #356 field: citation values;
    # common texts and both 32-item lists; Hypothesis; Candidate contributors,
    # tokens, texts, both 32-item text lists and its 32-item version-token list.
    # Counting every remaining value byte at the worst JSON escape ratio is
    # deliberately conservative.
    skeleton_bytes = len(_proposal_bytes(("NEW_EVENT_CANDIDATE",) * MAX_DECISION_LEADS))
    citation_value_slots = MAX_INPUT_CITATIONS
    common_value_slots = 3 + (2 * MAX_LIST_ITEMS)
    candidate_route_value_slots = 2 + 2 + 1 + 2 + (2 * MAX_LIST_ITEMS) + 8 + 3
    recommendation_value_bytes = MAX_TEXT_BYTES * (
        citation_value_slots + common_value_slots + candidate_route_value_slots
    )
    top_level_value_bytes = (
        MAX_DECISION_LEADS + MAX_CONTEXT_LEADS + 16
    ) * MAX_TEXT_BYTES + MAX_RATIONALE_BYTES
    analytical_maximum = skeleton_bytes + 6 * (
        MAX_DECISION_LEADS * recommendation_value_bytes
        + top_level_value_bytes
    )
    assert analytical_maximum < MAX_DISPOSITION_CANONICAL_BYTES

    monkeypatch.setattr(
        dispositions_module, "MAX_DISPOSITION_CANONICAL_BYTES", 128
    )
    oversized = b" " * 129
    with pytest.raises(DispositionContractError, match="bounded bytes"):
        ValidatorInputBinding.for_proposal(
            proposal_bytes=oversized,
            validator_id="validator:fixture",
            validator_version="1",
            authenticated_context_identity=DIGEST_A,
            retrieval_request_id="request:001",
            retrieval_request_digest=DIGEST_B,
            retrieval_receipt_id="receipt:001",
            retrieval_receipt_digest=DIGEST_C,
            ruleset_id="triage-rules",
            ruleset_version="1",
            ruleset_digest=DIGEST_D,
        )


def test_large_integer_json_errors_are_normalised_at_public_parse_boundaries() -> None:
    raw = b'{"x":' + b"9" * 5_000 + b"}"
    with pytest.raises(DispositionContractError):
        validate_proposal(raw, _validator())
    with pytest.raises(DispositionContractError):
        ProposalDisposition.from_canonical_bytes(raw)
    with pytest.raises(DispositionContractError):
        ProposalValidationFinding.from_canonical_bytes(raw)
    with pytest.raises(DispositionContractError):
        ValidatorInputBinding.for_proposal(
            proposal_bytes=raw,
            validator_id="validator:fixture",
            validator_version="1",
            authenticated_context_identity=DIGEST_A,
            retrieval_request_id="request:001",
            retrieval_request_digest=DIGEST_B,
            retrieval_receipt_id="receipt:001",
            retrieval_receipt_digest=DIGEST_C,
            ruleset_id="triage-rules",
            ruleset_version="1",
            ruleset_digest=DIGEST_D,
        )


def test_constructed_nested_canonicalisation_errors_are_normalised() -> None:
    raw = _proposal_bytes()
    validation = validate_proposal(raw, _validator(raw))
    head = LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A)
    selection = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )
    disposition = build_pending_dispositions(
        validation, {LEAD_A: head}, {LEAD_A: selection}
    )[0]

    bad_recommendation = replace(
        disposition.route_binding, likely_new_information=1.0
    )
    with pytest.raises(DispositionContractError, match="canonical JSON"):
        replace(disposition, route_binding=bad_recommendation)

    bad_proposal = replace(
        validation.proposal, recommendations=(bad_recommendation,)
    )
    with pytest.raises(DispositionContractError, match="canonical JSON"):
        replace(validation, proposal=bad_proposal)

    cycle: list[object] = []
    cycle.append(cycle)
    assert selection.next_action is not None
    object.__setattr__(selection.next_action, "instructions", cycle)
    with pytest.raises(DispositionContractError, match="canonical JSON"):
        build_pending_dispositions(
            validation, {LEAD_A: head}, {LEAD_A: selection}
        )

    wrong_typed_recommendation = replace(
        disposition.route_binding, input_citations=(object(),)
    )
    with pytest.raises(DispositionContractError, match="canonical JSON"):
        replace(disposition, route_binding=wrong_typed_recommendation)
    with pytest.raises(DispositionContractError, match="canonical JSON"):
        replace(
            validation,
            proposal=replace(
                validation.proposal,
                recommendations=(wrong_typed_recommendation,),
            ),
        )

    wrong_typed_selection = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )
    object.__setattr__(wrong_typed_selection, "primary_reason", object())
    with pytest.raises(DispositionContractError, match="canonical JSON"):
        build_pending_dispositions(
            validation,
            {LEAD_A: head},
            {LEAD_A: wrong_typed_selection},
        )
    with pytest.raises(DispositionContractError, match="head binding"):
        build_pending_dispositions(
            validation,
            {LEAD_A: object()},
            {
                LEAD_A: _selection(
                    CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
                    CanonicalNextAction.HANDOFF_FOR_EVALUATION,
                    ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
                )
            },
        )

    property_disposition = build_pending_dispositions(
        validation,
        {LEAD_A: head},
        {
            LEAD_A: _selection(
                CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
                CanonicalNextAction.HANDOFF_FOR_EVALUATION,
                ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
            )
        },
    )[0]
    object.__setattr__(
        property_disposition.route_binding, "candidate_manifest", object()
    )
    with pytest.raises(DispositionContractError, match="canonical JSON"):
        _ = property_disposition.canonical_bytes

    property_validation = validate_proposal(raw, _validator(raw))
    object.__setattr__(property_validation, "validator_input", object())
    with pytest.raises(DispositionContractError, match="canonical JSON"):
        _ = property_validation.canonical_bytes

    property_finding = validate_proposal(raw, _validator(raw)).findings[0]
    object.__setattr__(property_finding, "validator_input", object())
    with pytest.raises(DispositionContractError, match="canonical JSON"):
        _ = property_finding.canonical_bytes


def test_operational_action_selector_exhaustively_rejects_competing_seams() -> None:
    action_codes = {
        "RETRY_RETRIEVAL": (
            CanonicalNextAction.RETRY_SAME_REQUEST,
            ReasonCode.OPS_RETRIEVAL,
        ),
        "REQUEST_REVIEW": (
            CanonicalNextAction.REQUEST_REVIEW,
            ReasonCode.OPS_PARTIAL,
        ),
        "WAIT_FOR_DEPENDENCY": (
            CanonicalNextAction.WAIT_FOR_DEPENDENCY,
            ReasonCode.OPS_RETRIEVAL,
        ),
    }
    head = LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A)
    for action_kind, presence in itertools.product(action_codes, itertools.product((False, True), repeat=5)):
        owner, retry, review, expiry, dependency = presence
        document = json.loads(_proposal_bytes(("OPERATIONAL_HOLD",)))
        action = document["proposal"]["recommendations"][0]["operational_action"]
        action.update({
            "action_kind": action_kind,
            "owner_id": "owner:newsroom" if owner else None,
            "retry_condition": "Retry when healthy." if retry else None,
            "review_condition": "Review with owner." if review else None,
            "expiry_condition": "Review at expiry." if expiry else None,
            "dependency": "retrieval-service" if dependency else None,
        })
        # #356 requires at least one inspectable seam. Its only all-empty case is
        # correctly a Proposal integrity failure before the 6C2 matrix.
        raw = _resign(document)
        if not any(presence):
            with pytest.raises(DispositionContractError, match="integrity"):
                validate_proposal(raw, _validator(raw))
            continue
        validation = validate_proposal(raw, _validator(raw))
        expected_valid = {
            "RETRY_RETRIEVAL": retry and not any((owner, review, expiry, dependency)),
            "REQUEST_REVIEW": (owner or review or expiry) and not any((retry, dependency)),
            "WAIT_FOR_DEPENDENCY": dependency and not any((owner, retry, review, expiry)),
        }[action_kind]
        assert (validation.findings[0].severity.value == "INFO") is expected_valid
        recommendation = validation.proposal.recommendations[0]
        route_digest = digest_bytes(canonical_json_bytes(recommendation.canonical_value()))
        action_code, reason = action_codes[action_kind]
        selection = _selection(
            CanonicalOutcome.LEAD_OPERATIONAL_HOLD,
            action_code,
            reason,
            DecisionTerminality.PENDING_CONDITION,
        )
        assert selection.next_action is not None
        selection = replace(
            selection,
            next_action=replace(selection.next_action, condition_reference=route_digest),
        )
        if expected_valid:
            assert build_pending_dispositions(validation, {LEAD_A: head}, {LEAD_A: selection})
        else:
            with pytest.raises(DispositionContractError, match="validation errors"):
                build_pending_dispositions(validation, {LEAD_A: head}, {LEAD_A: selection})


def _typed_subclass(value: object, subclass: type[object]) -> object:
    impostor = object.__new__(subclass)
    for field in fields(value):  # type: ignore[arg-type]
        object.__setattr__(impostor, field.name, getattr(value, field.name))
    return impostor


class _KeyErrorItemsMapping(Mapping[str, object]):
    def __getitem__(self, key: str) -> object:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(("value",))

    def __len__(self) -> int:
        return 1

    def items(self) -> object:
        raise KeyError("items")


class _RaisingItemsMapping(Mapping[str, object]):
    def __init__(self, error_type: type[BaseException]) -> None:
        self.error_type = error_type

    def __getitem__(self, key: str) -> object:
        raise KeyError(key)

    def __iter__(self) -> Iterator[str]:
        return iter(("value",))

    def __len__(self) -> int:
        return 1

    def items(self) -> object:
        raise self.error_type("items")


def test_key_errors_from_typed_nested_impostors_and_builder_inputs_are_normalised() -> None:
    raw = _proposal_bytes()
    validation = validate_proposal(raw, _validator(raw))
    head = LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A)
    selection = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )
    disposition = build_pending_dispositions(
        validation, {LEAD_A: head}, {LEAD_A: selection}
    )[0]

    class BadHead(LeadDispositionHeadBinding):
        def canonical_value(self) -> dict[str, object]:
            raise KeyError("head")

    class BadValidator(ValidatorInputBinding):
        def canonical_value(self) -> dict[str, object]:
            raise KeyError("validator")

    class BadRecommendation(LeadRecommendation):
        def canonical_value(self) -> dict[str, object]:
            raise KeyError("recommendation")

    class BadProposal(TriageProposal):
        def canonical_value(self) -> dict[str, object]:
            raise KeyError("proposal")

    class BadSelection(OutcomeSelection):
        def canonical_value(self) -> dict[str, object]:
            raise KeyError("selection")

    bad_head = _typed_subclass(head, BadHead)
    bad_validator = _typed_subclass(validation.validator_input, BadValidator)
    bad_recommendation = _typed_subclass(
        disposition.route_binding, BadRecommendation
    )
    bad_proposal = _typed_subclass(validation.proposal, BadProposal)
    bad_selection = _typed_subclass(selection, BadSelection)

    public_calls = (
        lambda: replace(disposition, lead_head=bad_head),
        lambda: replace(disposition, validator_input=bad_validator),
        lambda: replace(disposition, route_binding=bad_recommendation),
        lambda: replace(validation, proposal=bad_proposal),
        lambda: validate_proposal(raw, bad_validator),
        lambda: build_pending_dispositions(
            validation, {LEAD_A: head}, {LEAD_A: bad_selection}
        ),
        lambda: build_pending_dispositions(
            validation, {LEAD_A: bad_head}, {LEAD_A: selection}
        ),
        lambda: build_pending_dispositions(
            replace(validation, validator_input=bad_validator),
            {LEAD_A: head},
            {LEAD_A: selection},
        ),
    )
    for call in public_calls:
        with pytest.raises(DispositionContractError):
            call()

    with pytest.raises(DispositionContractError, match="head binding"):
        build_pending_dispositions(
            validation, {LEAD_A: object()}, {LEAD_A: selection}
        )
    wrong_validator_validation = validate_proposal(raw, _validator(raw))
    object.__setattr__(wrong_validator_validation, "validator_input", object())
    with pytest.raises(DispositionContractError, match="validator"):
        build_pending_dispositions(
            wrong_validator_validation,
            {LEAD_A: head},
            {LEAD_A: selection},
        )


def test_key_errors_from_mapping_properties_and_subclass_parser_replay_are_normalised() -> None:
    raw = _proposal_bytes()
    validation = validate_proposal(raw, _validator(raw))
    head = LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A)
    selection = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )
    disposition = build_pending_dispositions(
        validation, {LEAD_A: head}, {LEAD_A: selection}
    )[0]

    class MappingSelection(OutcomeSelection):
        def canonical_value(self) -> object:
            return _KeyErrorItemsMapping()

    with pytest.raises(DispositionContractError):
        build_pending_dispositions(
            validation,
            {LEAD_A: head},
            {LEAD_A: _typed_subclass(selection, MappingSelection)},
        )

    class ReplayFinding(ProposalValidationFinding):
        def canonical_value(self) -> dict[str, object]:
            calls = getattr(self, "_canonical_calls", 0) + 1
            object.__setattr__(self, "_canonical_calls", calls)
            if calls > 1:
                raise KeyError("finding replay")
            return super().canonical_value()

    class ReplayDisposition(ProposalDisposition):
        def canonical_value(self) -> dict[str, object]:
            calls = getattr(self, "_canonical_calls", 0) + 1
            object.__setattr__(self, "_canonical_calls", calls)
            if calls > 1:
                raise KeyError("disposition replay")
            return super().canonical_value()

    with pytest.raises(DispositionContractError):
        ReplayFinding.from_canonical_bytes(validation.findings[0].canonical_bytes)
    with pytest.raises(DispositionContractError):
        ReplayDisposition.from_canonical_bytes(disposition.canonical_bytes)

    bad_head = _typed_subclass(head, type(
        "PropertyHead",
        (LeadDispositionHeadBinding,),
        {"canonical_value": lambda self: (_ for _ in ()).throw(KeyError("head"))},
    ))
    bad_validator = _typed_subclass(validation.validator_input, type(
        "PropertyValidator",
        (ValidatorInputBinding,),
        {"canonical_value": lambda self: (_ for _ in ()).throw(KeyError("validator"))},
    ))
    object.__setattr__(disposition, "lead_head", bad_head)
    object.__setattr__(validation, "validator_input", bad_validator)
    finding = validate_proposal(raw, _validator(raw)).findings[0]
    object.__setattr__(finding, "validator_input", bad_validator)
    for value in (disposition, validation, finding):
        with pytest.raises(DispositionContractError):
            _ = value.canonical_bytes


def test_route_validator_uses_replayed_selection_not_a_canonical_facade() -> None:
    selection = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )

    class ConcealedSelection(OutcomeSelection):
        def canonical_value(self) -> dict[str, object]:
            return selection.canonical_value()

    concealed = _typed_subclass(selection, ConcealedSelection)
    object.__setattr__(concealed, "primary_reason", object())
    with pytest.raises(DispositionContractError):
        ProposalDisposition.validate_route_selection(
            ProposalRoute.NEW_EVENT_CANDIDATE, concealed
        )


def test_validation_result_uses_replayed_proposal_before_set_operations() -> None:
    validation = validate_proposal(_proposal_bytes(), _validator())
    proposal = validation.proposal

    class ConcealedProposal(TriageProposal):
        def canonical_value(self) -> dict[str, object]:
            return proposal.canonical_value()

    concealed = _typed_subclass(proposal, ConcealedProposal)
    object.__setattr__(concealed, "decision_lead_ids", ([],))
    with pytest.raises(DispositionContractError):
        replace(validation, proposal=concealed)


def test_validator_factory_does_not_dispatch_to_subclass_digest_helper() -> None:
    class ConcealedValidator(ValidatorInputBinding):
        def expected_input_digest(self, proposal_canonical_digest: str) -> str:
            raise KeyError(proposal_canonical_digest)

    with pytest.raises(DispositionContractError):
        ConcealedValidator.for_proposal(
            proposal_bytes=_proposal_bytes(),
            validator_id="validator:fixture",
            validator_version="1",
            authenticated_context_identity=DIGEST_A,
            retrieval_request_id="request:001",
            retrieval_request_digest=DIGEST_B,
            retrieval_receipt_id="receipt:001",
            retrieval_receipt_digest=DIGEST_C,
            ruleset_id="triage-rules",
            ruleset_version="1",
            ruleset_digest=DIGEST_D,
        )


def test_builder_replays_findings_before_hashing_manifest_members() -> None:
    raw = _proposal_bytes()
    validation = validate_proposal(raw, _validator(raw))
    object.__setattr__(
        validation.findings[0], "evidence_reference_id", [LEAD_A]
    )
    head = LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A)
    selection = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )
    with pytest.raises(DispositionContractError):
        build_pending_dispositions(
            validation, {LEAD_A: head}, {LEAD_A: selection}
        )


def test_nested_exact_base_contracts_normalise_mapping_traversal_failures() -> None:
    raw = _proposal_bytes()
    validation = validate_proposal(raw, _validator(raw))
    head = LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A)
    selection = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )
    disposition = build_pending_dispositions(
        validation, {LEAD_A: head}, {LEAD_A: selection}
    )[0]

    class BadReason(StructuredReason):
        def canonical_value(self) -> object:
            return _RaisingItemsMapping(AttributeError)

    class BadNextAction(NextAction):
        def canonical_value(self) -> object:
            return _RaisingItemsMapping(AttributeError)

    class BadInputCitation(InputCitation):
        def canonical_value(self) -> object:
            return _RaisingItemsMapping(AttributeError)

    class BadCandidateManifest(CandidateManifest):
        def canonical_value(self) -> object:
            return _RaisingItemsMapping(AttributeError)

    reason_selection = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )
    object.__setattr__(
        reason_selection,
        "primary_reason",
        _typed_subclass(reason_selection.primary_reason, BadReason),
    )
    action_selection = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )
    assert action_selection.next_action is not None
    object.__setattr__(
        action_selection,
        "next_action",
        _typed_subclass(action_selection.next_action, BadNextAction),
    )

    citation_route = replace(
        disposition.route_binding,
        input_citations=(
            _typed_subclass(
                disposition.route_binding.input_citations[0], BadInputCitation
            ),
            *disposition.route_binding.input_citations[1:],
        ),
    )
    assert disposition.route_binding.candidate_manifest is not None
    candidate_route = replace(
        disposition.route_binding,
        candidate_manifest=_typed_subclass(
            disposition.route_binding.candidate_manifest, BadCandidateManifest
        ),
    )

    calls = (
        lambda: ProposalDisposition.validate_route_selection(
            ProposalRoute.NEW_EVENT_CANDIDATE, reason_selection
        ),
        lambda: ProposalDisposition.validate_route_selection(
            ProposalRoute.NEW_EVENT_CANDIDATE, action_selection
        ),
        lambda: replace(disposition, route_binding=citation_route),
        lambda: replace(disposition, route_binding=candidate_route),
    )
    for call in calls:
        with pytest.raises(DispositionContractError):
            call()


@pytest.mark.parametrize(
    "error_type", (AttributeError, IndexError, RuntimeError, KeyError)
)
def test_mapping_iteration_ordinary_exceptions_are_totalised(
    error_type: type[Exception],
) -> None:
    selection = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )

    class BadReason(StructuredReason):
        def canonical_value(self) -> object:
            return _RaisingItemsMapping(error_type)

    object.__setattr__(
        selection,
        "primary_reason",
        _typed_subclass(selection.primary_reason, BadReason),
    )
    with pytest.raises(DispositionContractError):
        ProposalDisposition.validate_route_selection(
            ProposalRoute.NEW_EVENT_CANDIDATE, selection
        )


@pytest.mark.parametrize("error_type", (KeyboardInterrupt, SystemExit))
def test_mapping_iteration_does_not_capture_base_exceptions(
    error_type: type[BaseException],
) -> None:
    selection = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )

    class BadReason(StructuredReason):
        def canonical_value(self) -> object:
            return _RaisingItemsMapping(error_type)

    object.__setattr__(
        selection,
        "primary_reason",
        _typed_subclass(selection.primary_reason, BadReason),
    )
    with pytest.raises(error_type):
        ProposalDisposition.validate_route_selection(
            ProposalRoute.NEW_EVENT_CANDIDATE, selection
        )


class _ExplodingFindingsTuple(tuple[object, ...]):
    def __iter__(self) -> Iterator[object]:
        raise RuntimeError("findings iteration")


def test_findings_require_an_exact_tuple_before_all_public_iteration_paths() -> None:
    raw = _proposal_bytes()

    constructor_validation = validate_proposal(raw, _validator(raw))
    with pytest.raises(DispositionContractError):
        replace(
            constructor_validation,
            findings=_ExplodingFindingsTuple(constructor_validation.findings),
        )

    property_validation = validate_proposal(raw, _validator(raw))
    object.__setattr__(
        property_validation,
        "findings",
        _ExplodingFindingsTuple(property_validation.findings),
    )
    with pytest.raises(DispositionContractError):
        _ = property_validation.canonical_bytes

    builder_validation = validate_proposal(raw, _validator(raw))
    object.__setattr__(
        builder_validation,
        "findings",
        _ExplodingFindingsTuple(builder_validation.findings),
    )
    head = LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A)
    selection = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )
    with pytest.raises(DispositionContractError):
        build_pending_dispositions(
            builder_validation, {LEAD_A: head}, {LEAD_A: selection}
        )


class _ExplodingBytes(bytes):
    def __len__(self) -> int:
        raise RuntimeError("bytes length")

    def __iter__(self) -> Iterator[int]:
        raise RuntimeError("bytes iteration")


def test_wire_parsers_require_exact_bytes_before_length_or_iteration() -> None:
    raw = _proposal_bytes()
    validation = validate_proposal(raw, _validator(raw))
    head = LeadDispositionHeadBinding(LEAD_A, DIGEST_B, "head:a", DIGEST_A)
    selection = _selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )
    disposition = build_pending_dispositions(
        validation, {LEAD_A: head}, {LEAD_A: selection}
    )[0]
    wire_values = (
        (lambda value: validate_proposal(value, _validator(raw)), raw),
        (ProposalDisposition.from_canonical_bytes, disposition.canonical_bytes),
        (
            ProposalValidationFinding.from_canonical_bytes,
            validation.findings[0].canonical_bytes,
        ),
        (
            lambda value: ValidatorInputBinding.for_proposal(
                proposal_bytes=value,
                validator_id="validator:fixture",
                validator_version="1",
                authenticated_context_identity=DIGEST_A,
                retrieval_request_id="request:001",
                retrieval_request_digest=DIGEST_B,
                retrieval_receipt_id="receipt:001",
                retrieval_receipt_digest=DIGEST_C,
                ruleset_id="triage-rules",
                ruleset_version="1",
                ruleset_digest=DIGEST_D,
            ),
            raw,
        ),
    )
    for call, value in wire_values:
        with pytest.raises(DispositionContractError):
            call(_ExplodingBytes(value))


class _ExplodingDigestStr(str):
    def strip(self, chars: str | None = None) -> str:
        raise RuntimeError("digest strip")


def test_digest_constructor_requires_exact_string_before_string_methods() -> None:
    with pytest.raises(DispositionContractError):
        replace(
            _validator(),
            authenticated_context_identity=_ExplodingDigestStr(DIGEST_A),
        )


class _ExplodingComparisonDigest(str):
    def __ne__(self, other: object) -> bool:
        raise RuntimeError("digest comparison")


def test_finding_set_digest_is_rehydrated_before_comparison() -> None:
    raw = _proposal_bytes()
    validation = validate_proposal(raw, _validator(raw))

    with pytest.raises(DispositionContractError):
        replace(
            validation,
            finding_set_digest=_ExplodingComparisonDigest(
                validation.finding_set_digest
            ),
        )


def test_uninitialised_validation_result_is_normalised_at_public_entries() -> None:
    validation = object.__new__(dispositions_module.ProposalValidationResult)

    with pytest.raises(DispositionContractError):
        _ = validation.canonical_bytes
    with pytest.raises(DispositionContractError):
        build_pending_dispositions(validation, {}, {})


def test_uninitialised_disposition_lead_property_is_normalised() -> None:
    disposition = object.__new__(ProposalDisposition)

    with pytest.raises(DispositionContractError):
        _ = disposition.decision_lead_id
