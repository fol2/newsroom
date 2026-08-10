from __future__ import annotations

import json
import os
import sqlite3
import threading
from concurrent.futures import ThreadPoolExecutor
from copy import deepcopy
from dataclasses import replace

import pytest

from newsroom.authority.auth import (
    AuthenticationProof,
    StaticAuthenticator,
    StaticPrincipal,
)
from newsroom.authority.event_hypothesis_migrations import (
    EVENT_HYPOTHESIS_MIGRATION_STATEMENTS,
)
from newsroom.authority.migrations import apply_pending_migrations
from newsroom.authority.triage_disposition_migrations import (
    TRIAGE_DISPOSITION_MIGRATION_STATEMENTS,
)
from newsroom.authority.types import UtcTimestamp
from newsroom.increment6._hypothesis_store import (
    EventHypothesisAuthority as PrivateAuthority,
)
from newsroom.increment6._hypothesis_store import (
    _HypothesisStore,
)
from newsroom.increment6.dispositions import ProposalDispositionStore
from newsroom.increment6.hypotheses import (
    EventHypothesisAuthority,
    HypothesisContractError,
    open_event_hypothesis_authority,
)
from newsroom.increment6.outcomes import (
    CanonicalNextAction,
    CanonicalOutcome,
    ReasonCode,
)
from newsroom.increment6.work_items import (
    RetrievalContextAuthority,
    RetrievalInputBinding,
    TriageWorkItem,
)
from newsroom.tests import test_increment5d1_hybrid_composer as composer_helpers
from newsroom.tests import test_increment5d2_retrieval_context as retrieval_helpers
from newsroom.tests import test_increment6a2_work_items as work_item_helpers
from newsroom.tests import test_increment6c2_dispositions as disposition_helpers


def _authority_fixture(tmp_path, *, persist_sources: bool = True):
    inputs = composer_helpers.branch_inputs.__wrapped__(tmp_path)
    builder, _, _, _, _, request, receipt, _ = (
        retrieval_helpers._retained_complete_context(
            tmp_path, inputs, name="hypothesis-authority"
        )
    )
    retrieval = RetrievalContextAuthority(
        builder.journal.path, {request.request_digest: (request, receipt)}
    )
    decisions = tuple(work_item_helpers._decision(index) for index in range(1, 17))
    decision = decisions[0]
    connection, work_store = work_item_helpers._store(
        decisions, retrieval_authority=retrieval
    )
    item = TriageWorkItem.create((decision,))
    version = replace(
        work_item_helpers._version(item),
        retrieval=RetrievalInputBinding.from_receipt(request, receipt),
    )
    work_store.create_or_replay(item, version)
    proposal_sources = []
    for candidate in decisions[1:]:
        candidate_item = TriageWorkItem.create((candidate,))
        candidate_version = replace(
            work_item_helpers._version(candidate_item),
            retrieval=RetrievalInputBinding.from_receipt(request, receipt),
        )
        if persist_sources:
            work_store.create_or_replay(candidate_item, candidate_version)
        proposal_sources.append((candidate_version, candidate))
    for statement in (
        *TRIAGE_DISPOSITION_MIGRATION_STATEMENTS,
        *EVENT_HYPOTHESIS_MIGRATION_STATEMENTS,
    ):
        connection.execute(statement)
    authenticator = StaticAuthenticator(
        credentials={
            "credential": StaticPrincipal("editor"),
            "other": StaticPrincipal("other"),
        },
        authority_domain="newsroom.dispositions",
    )
    proof = AuthenticationProof(method="STATIC_TOKEN", credential="credential")
    proposal = disposition_helpers._persistable_proposal(version, decision, receipt)
    dispositions = ProposalDispositionStore(
        connection, retrieval, authenticator
    ).persist(
        proposal,
        {
            decision.lead_id: disposition_helpers._selection(
                CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
                CanonicalNextAction.HANDOFF_FOR_EVALUATION,
                ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
            )
        },
        proof=proof,
    )
    return (
        connection,
        retrieval,
        authenticator,
        proof,
        proposal,
        dispositions,
        work_store,
        item,
        version,
        decision,
        receipt,
        proposal_sources,
    )


def _open(fixture):
    connection, retrieval, authenticator, *_ = fixture
    store = _HypothesisStore(
        connection,
        retrieval,
        authenticator,
        lambda: UtcTimestamp.parse("2042-01-01T00:00:00.000000Z"),
    )
    return EventHypothesisAuthority(PrivateAuthority(store, lambda: None))


def _selection_for(relationship: str):
    return {
        "RELATED_DISTINCT": disposition_helpers._selection(
            CanonicalOutcome.LEAD_ASSOCIATE_WITHOUT_CANDIDATE,
            CanonicalNextAction.CLOSE_DECISION,
            ReasonCode.REL_RELATED_DISTINCT,
        ),
        "UNCERTAIN": disposition_helpers._selection(
            CanonicalOutcome.LEAD_ASSOCIATE_WITHOUT_CANDIDATE,
            CanonicalNextAction.CLOSE_DECISION,
            ReasonCode.REL_UNCERTAIN,
        ),
        "SAME_STATE": disposition_helpers._selection(
            CanonicalOutcome.LEAD_ASSOCIATE_WITHOUT_CANDIDATE,
            CanonicalNextAction.CLOSE_DECISION,
            ReasonCode.REL_SAME_STATE,
        ),
        "DEVELOPMENT_OF": disposition_helpers._selection(
            CanonicalOutcome.LEAD_ADMIT_DEVELOPMENT_CANDIDATE,
            CanonicalNextAction.HANDOFF_FOR_EVALUATION,
            ReasonCode.REL_DEVELOPMENT,
        ),
    }[relationship]


def _targeted_proposal(
    fixture, *, proposal_id: str, local_id: str, relationship: str, target: str
) -> tuple[bytes, tuple]:
    connection, retrieval, authenticator, proof, _, _, _, _, _, _, receipt, sources = (
        fixture
    )
    version, decision = sources.pop(0)
    base = disposition_helpers._persistable_proposal(version, decision, receipt)
    document = json.loads(base)
    proposal = document["proposal"]
    proposal["proposal_id"] = proposal_id
    recommendation = proposal["recommendations"][0]
    route = (
        "DEVELOPMENT_CANDIDATE"
        if relationship == "DEVELOPMENT_OF"
        else "ASSOCIATE_WITHOUT_CANDIDATE"
    )
    recommendation["route"] = route
    recommendation["hypothesis"] = {
        "proposal_local_id": local_id,
        "summary": f"A retained {relationship.lower()} relationship.",
        "relationship_kind": relationship,
        "target_hypothesis_id": target,
    }
    for citation in recommendation["input_citations"]:
        citation["target_hypothesis_id"] = (
            target if citation["source_kind"] == "RETRIEVAL_MATCH" else None
        )
    if route == "ASSOCIATE_WITHOUT_CANDIDATE":
        recommendation["candidate_manifest"] = None
    else:
        recommendation["candidate_manifest"]["manifest_kind"] = "DEVELOPMENT"
    raw = disposition_helpers._resign(document)
    dispositions = ProposalDispositionStore(
        connection, retrieval, authenticator
    ).persist(raw, {decision.lead_id: _selection_for(relationship)}, proof=proof)
    return raw, dispositions


def _reopen_copy(fixture, authority):
    connection, retrieval, authenticator, *rest = fixture
    authority.close()
    reopened = sqlite3.connect(":memory:", isolation_level=None)
    connection.backup(reopened)
    return _open((reopened, retrieval, authenticator, *rest)), reopened


def test_real_store_create_replay_current_history_and_reopen(tmp_path) -> None:
    fixture = _authority_fixture(tmp_path)
    _, _, _, proof, proposal, dispositions, *_ = fixture
    authority = _open(fixture)
    try:
        first = authority.retain(proposal, dispositions, proof=proof)
        assert authority.retain(proposal, dispositions, proof=proof) == first
        assert authority.current(first.hypothesis_id, proof=proof) == first
        assert authority.load_version(first.version_id) == first
        assert (
            authority.load_hypothesis(first.hypothesis_id).hypothesis_id
            == first.hypothesis_id
        )
        assert authority.versions(first.hypothesis_id) == (first,)
        assert (
            first.actor_identity_digest
            == dispositions[0].validator_input.authenticated_context_identity
        )
        assert first.recorded_at == "2042-01-01T00:00:00.000000Z"
    finally:
        authority.close()
    connection, retrieval, authenticator, *_ = fixture
    reopened_connection = sqlite3.connect(":memory:", isolation_level=None)
    connection.backup(reopened_connection)
    reopened_fixture = (reopened_connection, retrieval, authenticator, *fixture[3:])
    assert _open(reopened_fixture).current(first.hypothesis_id, proof=proof) == first


def test_wrong_proof_partial_or_unretained_inputs_write_nothing(tmp_path) -> None:
    fixture = _authority_fixture(tmp_path)
    connection, _, _, proof, proposal, dispositions, *_ = fixture
    other = AuthenticationProof(method="STATIC_TOKEN", credential="other")
    authority = _open(fixture)
    try:
        with pytest.raises(HypothesisContractError):
            authority.retain(proposal, dispositions, proof=other)
        with pytest.raises(HypothesisContractError):
            authority.retain(proposal, (), proof=proof)
    finally:
        authority.close()
    assert connection.execute(
        "SELECT count(*) FROM event_hypothesis_versions_v2"
    ).fetchone() == (0,)


def test_complete_two_lead_proposal_group_retains_once_and_partial_writes_zero(
    tmp_path,
) -> None:
    fixture = _authority_fixture(tmp_path, persist_sources=False)
    connection, retrieval, authenticator, proof, _, _, _, _, _, _, receipt, sources = (
        fixture
    )
    first_version, first_decision = sources.pop(0)
    _second_version, second_decision = sources.pop(0)
    # Re-persist both Leads in one real Work Item/Version authority boundary.
    item = TriageWorkItem.create((first_decision, second_decision))
    version = replace(
        work_item_helpers._version(item),
        retrieval=first_version.retrieval,
    )
    fixture[6].create_or_replay(item, version)
    document = json.loads(
        disposition_helpers._persistable_proposal(version, first_decision, receipt)
    )
    proposal = document["proposal"]
    first = proposal["recommendations"][0]
    second = deepcopy(first)
    second["decision_lead_id"] = second_decision.lead_id
    second["input_citations"][0]["source_id"] = second_decision.lead_id
    second["input_citations"][0]["source_digest"] = second_decision.lead_digest
    second["candidate_manifest"]["contributing_lead_ids"] = [second_decision.lead_id]
    proposal["decision_lead_ids"] = sorted(
        (first_decision.lead_id, second_decision.lead_id)
    )
    proposal["recommendations"] = sorted(
        (first, second), key=lambda recommendation: recommendation["decision_lead_id"]
    )
    raw = disposition_helpers._resign(document)
    selection = disposition_helpers._selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )
    retained = ProposalDispositionStore(connection, retrieval, authenticator).persist(
        raw,
        {first_decision.lead_id: selection, second_decision.lead_id: selection},
        proof=proof,
    )
    authority = _open(fixture)
    with pytest.raises(HypothesisContractError):
        authority.retain(raw, retained[:1], proof=proof)
    assert connection.execute(
        "SELECT count(*) FROM event_hypothesis_versions_v2"
    ).fetchone() == (0,)
    value = authority.retain(raw, retained, proof=proof)
    assert tuple(
        binding.decision_lead_id for binding in value.source_bindings
    ) == tuple(sorted((first_decision.lead_id, second_decision.lead_id)))
    assert authority.retain(raw, retained, proof=proof) == value
    assert connection.execute(
        "SELECT count(*) FROM event_hypothesis_versions_v2"
    ).fetchone() == (1,)


def test_legal_large_producer_envelope_round_trips_without_inflating_public_version(
    tmp_path,
) -> None:
    fixture = _authority_fixture(tmp_path, persist_sources=False)
    connection, retrieval, authenticator, proof, _, _, _, _, _, _, receipt, sources = (
        fixture
    )
    selected = sources[:8]
    decisions = tuple(decision for _, decision in selected)
    item = TriageWorkItem.create(decisions)
    version = replace(
        work_item_helpers._version(item), retrieval=selected[0][0].retrieval
    )
    fixture[6].create_or_replay(item, version)
    legal_proposal = json.loads(
        disposition_helpers._persistable_proposal(version, decisions[0], receipt)
    )["proposal"]
    legal = legal_proposal["recommendations"][0]
    document = json.loads(disposition_helpers._reviewed_large_producer_payload())
    proposal = document["proposal"]
    proposal["work_item_binding"] = {
        "work_item_id": version.work_item_id,
        "work_item_version_id": version.version_id,
        "work_item_version_digest": version.canonical_digest,
    }
    proposal["retrieval_context_binding"] = {
        "context_id": receipt.context_id,
        "context_digest": receipt.receipt_digest,
        "contract_digest": legal_proposal["retrieval_context_binding"][
            "contract_digest"
        ],
    }
    proposal["worker_attempt_binding"]["work_item_version_digest"] = (
        version.canonical_digest
    )
    proposal["worker_attempt_binding"]["retrieval_context_digest"] = (
        receipt.receipt_digest
    )
    ordered = tuple(sorted(decisions, key=lambda decision: decision.lead_id))
    proposal["decision_lead_ids"] = [decision.lead_id for decision in ordered]
    manifest = deepcopy(legal["candidate_manifest"])
    manifest["contributing_lead_ids"] = [decision.lead_id for decision in ordered]
    manifest["likely_new_information"] = "n" * 1_024
    manifest["reader_utility_basis"] = "u" * 1_024
    manifest["uncertainties"] = [f"{index:02d}:" + "x" * 1_021 for index in range(32)]
    manifest["evidence_objectives"] = [
        f"{index:02d}:" + "y" * 1_021 for index in range(32)
    ]
    passage = receipt.items[0].passage
    text = receipt.items[0].text.encode("utf-8")
    for recommendation, decision in zip(
        proposal["recommendations"], ordered, strict=True
    ):
        recommendation["decision_lead_id"] = decision.lead_id
        recommendation["route"] = "NEW_EVENT_CANDIDATE"
        recommendation["hypothesis"] = deepcopy(legal["hypothesis"])
        recommendation["candidate_manifest"] = deepcopy(manifest)
        for index, citation in enumerate(recommendation["input_citations"]):
            if index == 0:
                citation.update(
                    source_kind="DECISION_LEAD",
                    source_id=decision.lead_id,
                    source_digest=decision.lead_digest,
                    byte_start=0,
                    byte_end=18,
                )
            else:
                citation.update(
                    source_kind="RETRIEVAL_MATCH",
                    source_id=passage.passage_id,
                    source_digest=passage.text_digest,
                    byte_start=0,
                    byte_end=len(text),
                    quote_digest=disposition_helpers.digest_bytes(text),
                    field_path="passage.text",
                )
            citation["target_hypothesis_id"] = None
    raw = disposition_helpers._resign(document)
    assert len(raw) > 1_100_000
    selection = disposition_helpers._selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )
    retained = ProposalDispositionStore(connection, retrieval, authenticator).persist(
        raw, {decision.lead_id: selection for decision in ordered}, proof=proof
    )
    value = _open(fixture).retain(raw, retained, proof=proof)
    stored = connection.execute(
        "SELECT proposal_canonical_bytes FROM event_hypothesis_versions_v2"
    ).fetchone()[0]
    assert bytes(stored) == raw
    assert len(value.canonical_bytes) <= 1_048_576


def test_second_opener_and_unsafe_modes_fail_closed(tmp_path) -> None:
    fixture = _authority_fixture(tmp_path)
    _, retrieval, authenticator, *_ = fixture
    database = tmp_path / "secure" / "authority.sqlite3"
    database.parent.mkdir(mode=0o700)
    seed = sqlite3.connect(database, isolation_level=None)
    seed.execute("PRAGMA foreign_keys=ON")
    apply_pending_migrations(seed, applied_at="2042-01-01T00:00:00.000000Z")
    seed.close()
    os.chmod(database, 0o600)

    def opened():
        return open_event_hypothesis_authority(
            database, retrieval_authority=retrieval, authenticator=authenticator
        )

    first = opened()
    try:
        with pytest.raises(HypothesisContractError, match="writer"):
            opened()
    finally:
        first.close()
    os.chmod(database, 0o640)
    with pytest.raises(HypothesisContractError):
        open_event_hypothesis_authority(
            database, retrieval_authority=retrieval, authenticator=authenticator
        )


def test_direct_scalar_tamper_is_detected_by_current_and_reopen(tmp_path) -> None:
    fixture = _authority_fixture(tmp_path)
    connection, _, _, proof, proposal, dispositions, *_ = fixture
    authority = _open(fixture)
    try:
        authority.retain(proposal, dispositions, proof=proof)
    finally:
        authority.close()
    connection.execute("DROP TRIGGER immutable_event_hypothesis_version_update")
    connection.execute(
        "UPDATE event_hypothesis_versions_v2 SET actor_identity_digest=?",
        ("sha256:" + "f" * 64,),
    )
    with pytest.raises(HypothesisContractError):
        _open(fixture)


@pytest.mark.parametrize("relationship", ("RELATED_DISTINCT", "UNCERTAIN"))
def test_target_bearing_create_pins_current_target_and_reopens(
    tmp_path, relationship: str
) -> None:
    fixture = _authority_fixture(tmp_path)
    _, _, _, proof, proposal, dispositions, *_ = fixture
    authority = _open(fixture)
    target = authority.retain(proposal, dispositions, proof=proof)
    raw, source = _targeted_proposal(
        fixture,
        proposal_id=f"00000000-0000-4000-8000-000000000{101 if relationship == 'RELATED_DISTINCT' else 102}",
        local_id=f"hypothesis:{relationship.lower()}",
        relationship=relationship,
        target=target.hypothesis_id,
    )
    created = authority.retain(raw, source, proof=proof, expected_target_version=target)
    assert created.ordinal == 1
    assert created.hypothesis_id != target.hypothesis_id
    assert created.proposed_target_hypothesis_id == target.hypothesis_id
    assert (created.target_version_id, created.target_version_digest) == (
        target.version_id,
        target.canonical_digest,
    )
    reopened, connection = _reopen_copy(fixture, authority)
    try:
        assert reopened.versions(created.hypothesis_id) == (created,)
        assert reopened.current(created.hypothesis_id, proof=proof) == created
    finally:
        reopened.close()
        connection.close()


def test_target_comparators_reject_arbitrary_wrong_and_stale_heads_without_rows(
    tmp_path,
) -> None:
    fixture = _authority_fixture(tmp_path)
    connection, _, _, proof, proposal, dispositions, *_ = fixture
    authority = _open(fixture)
    target = authority.retain(proposal, dispositions, proof=proof)
    second_raw, second_source = _targeted_proposal(
        fixture,
        proposal_id="00000000-0000-4000-8000-000000000111",
        local_id="hypothesis:second-target",
        relationship="RELATED_DISTINCT",
        target=target.hypothesis_id,
    )
    second = authority.retain(
        second_raw, second_source, proof=proof, expected_target_version=target
    )
    before = connection.execute(
        "SELECT count(*) FROM event_hypothesis_versions_v2"
    ).fetchone()

    arbitrary_raw, arbitrary_source = _targeted_proposal(
        fixture,
        proposal_id="00000000-0000-4000-8000-000000000112",
        local_id="hypothesis:arbitrary",
        relationship="RELATED_DISTINCT",
        target="44444444-4444-4444-8444-444444444444",
    )
    with pytest.raises(HypothesisContractError):
        authority.retain(
            arbitrary_raw,
            arbitrary_source,
            proof=proof,
            expected_target_version=target,
        )
    wrong_raw, wrong_source = _targeted_proposal(
        fixture,
        proposal_id="00000000-0000-4000-8000-000000000113",
        local_id="hypothesis:wrong-version",
        relationship="RELATED_DISTINCT",
        target=target.hypothesis_id,
    )
    with pytest.raises(HypothesisContractError):
        authority.retain(
            wrong_raw,
            wrong_source,
            proof=proof,
            expected_target_version=second,
        )
    append_raw, append_source = _targeted_proposal(
        fixture,
        proposal_id="00000000-0000-4000-8000-000000000114",
        local_id="hypothesis:advance",
        relationship="SAME_STATE",
        target=target.hypothesis_id,
    )
    advanced = authority.retain(
        append_raw, append_source, proof=proof, expected_target_version=target
    )
    stale_raw, stale_source = _targeted_proposal(
        fixture,
        proposal_id="00000000-0000-4000-8000-000000000115",
        local_id="hypothesis:stale",
        relationship="UNCERTAIN",
        target=target.hypothesis_id,
    )
    with pytest.raises(HypothesisContractError):
        authority.retain(
            stale_raw,
            stale_source,
            proof=proof,
            expected_target_version=target,
        )
    assert connection.execute(
        "SELECT count(*) FROM event_hypothesis_versions_v2"
    ).fetchone() == (before[0] + 1,)
    reopened, reopened_connection = _reopen_copy(fixture, authority)
    try:
        assert reopened.versions(target.hypothesis_id) == (target, advanced)
        assert reopened.current(target.hypothesis_id, proof=proof) == advanced
    finally:
        reopened.close()
        reopened_connection.close()


@pytest.mark.parametrize("relationship", ("SAME_STATE", "DEVELOPMENT_OF"))
def test_append_replay_stale_cas_and_reopen_exact_chain(
    tmp_path, relationship: str
) -> None:
    fixture = _authority_fixture(tmp_path)
    connection, _, _, proof, proposal, dispositions, *_ = fixture
    authority = _open(fixture)
    first = authority.retain(proposal, dispositions, proof=proof)
    raw, source = _targeted_proposal(
        fixture,
        proposal_id=f"00000000-0000-4000-8000-000000000{121 if relationship == 'SAME_STATE' else 122}",
        local_id=f"hypothesis:append-{relationship.lower()}",
        relationship=relationship,
        target=first.hypothesis_id,
    )
    second = authority.retain(raw, source, proof=proof, expected_target_version=first)
    assert second.hypothesis_id == first.hypothesis_id
    assert second.ordinal == 2
    assert (second.previous_version_id, second.previous_version_digest) == (
        first.version_id,
        first.canonical_digest,
    )
    assert (second.target_version_id, second.target_version_digest) == (
        first.version_id,
        first.canonical_digest,
    )
    assert (
        authority.load_version(first.version_id).canonical_bytes
        == first.canonical_bytes
    )
    assert authority.current(first.hypothesis_id, proof=proof) == second
    assert (
        authority.retain(raw, source, proof=proof, expected_target_version=first)
        == second
    )
    assert connection.execute(
        "SELECT count(*) FROM event_hypothesis_versions_v2 WHERE hypothesis_id=?",
        (first.hypothesis_id,),
    ).fetchone() == (2,)
    divergent_raw, divergent_source = _targeted_proposal(
        fixture,
        proposal_id="00000000-0000-4000-8000-000000000123",
        local_id="hypothesis:stale-append",
        relationship=relationship,
        target=first.hypothesis_id,
    )
    with pytest.raises(HypothesisContractError):
        authority.retain(
            divergent_raw,
            divergent_source,
            proof=proof,
            expected_target_version=first,
        )
    reopened, reopened_connection = _reopen_copy(fixture, authority)
    try:
        assert reopened.versions(first.hypothesis_id) == (first, second)
        assert reopened.current(first.hypothesis_id, proof=proof) == second
    finally:
        reopened.close()
        reopened_connection.close()


def test_upstream_advance_invalidates_current_but_not_history_or_replay(
    tmp_path,
) -> None:
    fixture = _authority_fixture(tmp_path)
    (
        connection,
        _,
        _,
        proof,
        proposal,
        dispositions,
        work_store,
        item,
        first_work,
        *_,
    ) = fixture
    authority = _open(fixture)
    first = authority.retain(proposal, dispositions, proof=proof)
    second_work = replace(
        work_item_helpers._version(item, 2), retrieval=first_work.retrieval
    )
    work_store.append_version(
        first_work.version_id, first_work.canonical_digest, second_work
    )
    for operation in (authority.current, authority.require_current):
        with pytest.raises(HypothesisContractError):
            operation(first.hypothesis_id, proof=proof)
    assert authority.load_version(first.version_id) == first
    assert authority.retain(proposal, dispositions, proof=proof) == first
    assert connection.execute(
        "SELECT count(*) FROM event_hypothesis_versions_v2"
    ).fetchone() == (1,)
    reopened, reopened_connection = _reopen_copy(fixture, authority)
    try:
        assert reopened.load_version(first.version_id) == first
        assert reopened.versions(first.hypothesis_id) == (first,)
        with pytest.raises(HypothesisContractError):
            reopened.current(first.hypothesis_id, proof=proof)
    finally:
        reopened.close()
        reopened_connection.close()


def _copied_race_stores(tmp_path, fixture, name: str):
    database = tmp_path / f"{name}.sqlite3"
    target = sqlite3.connect(database, isolation_level=None)
    fixture[0].backup(target)
    target.close()
    connections = tuple(
        sqlite3.connect(
            database, isolation_level=None, timeout=10, check_same_thread=False
        )
        for _ in range(2)
    )
    stores = tuple(
        _HypothesisStore(
            connection,
            fixture[1],
            fixture[2],
            lambda: UtcTimestamp.parse("2042-01-01T00:00:00.000000Z"),
        )
        for connection in connections
    )
    return database, connections, stores


def test_two_connection_equivalent_create_converges_and_reopens(tmp_path) -> None:
    fixture = _authority_fixture(tmp_path)
    _, _, _, proof, proposal, dispositions, *_ = fixture
    database, connections, stores = _copied_race_stores(
        tmp_path, fixture, "equivalent-create-race"
    )
    barrier = threading.Barrier(2)

    def retain(store):
        barrier.wait()
        return store.retain(proposal, dispositions, proof=proof)

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(executor.submit(retain, store) for store in stores)
        results = tuple(future.result() for future in futures)
    assert results[0] == results[1]
    assert connections[0].execute(
        "SELECT count(*) FROM event_hypothesis_versions_v2"
    ).fetchone() == (1,)
    for connection in connections:
        connection.close()
    reopened_connection = sqlite3.connect(database, isolation_level=None)
    reopened = _HypothesisStore(
        reopened_connection,
        fixture[1],
        fixture[2],
        lambda: UtcTimestamp.parse("2042-01-01T00:00:00.000000Z"),
    )
    assert reopened.versions(results[0].hypothesis_id) == (results[0],)
    assert reopened.current(results[0].hypothesis_id, proof=proof) == results[0]
    reopened_connection.close()


def test_two_connection_stale_appends_have_one_winner_and_exact_reopen(
    tmp_path,
) -> None:
    fixture = _authority_fixture(tmp_path)
    _, _, _, proof, proposal, dispositions, *_ = fixture
    seed_authority = _open(fixture)
    first = seed_authority.retain(proposal, dispositions, proof=proof)
    proposals = tuple(
        _targeted_proposal(
            fixture,
            proposal_id=f"00000000-0000-4000-8000-00000000013{index}",
            local_id=f"hypothesis:race-append-{index}",
            relationship="SAME_STATE",
            target=first.hypothesis_id,
        )
        for index in (1, 2)
    )
    seed_authority.close()
    database, connections, stores = _copied_race_stores(
        tmp_path, fixture, "stale-append-race"
    )
    barrier = threading.Barrier(2)

    def append(store, values):
        barrier.wait()
        try:
            return store.retain(
                values[0], values[1], proof=proof, expected_target_version=first
            )
        except HypothesisContractError as exc:
            return exc

    with ThreadPoolExecutor(max_workers=2) as executor:
        futures = tuple(
            executor.submit(append, stores[index], proposals[index])
            for index in range(2)
        )
        results = tuple(future.result() for future in futures)
    winners = tuple(value for value in results if not isinstance(value, Exception))
    losers = tuple(
        value for value in results if isinstance(value, HypothesisContractError)
    )
    assert len(winners) == len(losers) == 1
    assert connections[0].execute(
        "SELECT count(*) FROM event_hypothesis_versions_v2 WHERE hypothesis_id=?",
        (first.hypothesis_id,),
    ).fetchone() == (2,)
    for connection in connections:
        connection.close()
    reopened_connection = sqlite3.connect(database, isolation_level=None)
    reopened = _HypothesisStore(
        reopened_connection,
        fixture[1],
        fixture[2],
        lambda: UtcTimestamp.parse("2042-01-01T00:00:00.000000Z"),
    )
    assert reopened.versions(first.hypothesis_id) == (first, winners[0])
    assert reopened.current(first.hypothesis_id, proof=proof) == winners[0]
    reopened_connection.close()


def test_transaction_owner_lock_isolates_failure_from_replay_and_current(
    tmp_path, monkeypatch
) -> None:
    fixture = _authority_fixture(tmp_path)
    _, _, _, proof, proposal, dispositions, *_ = fixture
    database = tmp_path / "shared-connection.sqlite3"
    copied = sqlite3.connect(database, isolation_level=None)
    fixture[0].backup(copied)
    copied.close()
    connection = sqlite3.connect(
        database, isolation_level=None, check_same_thread=False
    )
    store = _HypothesisStore(
        connection,
        fixture[1],
        fixture[2],
        lambda: UtcTimestamp.parse("2042-01-01T00:00:00.000000Z"),
    )
    first = store.retain(proposal, dispositions, proof=proof)
    original_verify = _HypothesisStore._verify
    failure_started = threading.Event()
    release_failure = threading.Event()
    reader_started = threading.Event()
    injected = False

    def verify(candidate):
        nonlocal injected
        if not injected:
            injected = True
            failure_started.set()
            assert release_failure.wait(5)
            raise RuntimeError("ordinary injected failure")
        return original_verify(candidate)

    monkeypatch.setattr(_HypothesisStore, "_verify", verify)

    def fail():
        with pytest.raises(HypothesisContractError):
            store.retain(proposal, dispositions, proof=proof)

    def read():
        reader_started.set()
        return store.current(first.hypothesis_id, proof=proof)

    with ThreadPoolExecutor(max_workers=2) as executor:
        failing = executor.submit(fail)
        assert failure_started.wait(5)
        reading = executor.submit(read)
        assert reader_started.wait(5)
        assert reading.done() is False
        release_failure.set()
        failing.result()
        assert reading.result() == first
    assert store.retain(proposal, dispositions, proof=proof) == first
    assert connection.in_transaction is False
    assert store.versions(first.hypothesis_id) == (first,)


def _retained_file_fixture(tmp_path, fixture, *, append: bool = False):
    """Copy a genuinely persisted authority so corruption is externally observable."""
    _, _, _, proof, proposal, dispositions, *_ = fixture
    seed = _open(fixture)
    first = seed.retain(proposal, dispositions, proof=proof)
    last = first
    if append:
        raw, source = _targeted_proposal(
            fixture,
            proposal_id="00000000-0000-4000-8000-000000000991",
            local_id="hypothesis:integrity-append",
            relationship="SAME_STATE",
            target=first.hypothesis_id,
        )
        last = seed.retain(raw, source, proof=proof, expected_target_version=first)
    seed.close()
    database = tmp_path / ("retained-chain.sqlite3" if append else "retained.sqlite3")
    copied = sqlite3.connect(database, isolation_level=None)
    fixture[0].backup(copied)
    copied.close()
    reader_connection = sqlite3.connect(database, isolation_level=None)
    reader = _HypothesisStore(
        reader_connection,
        fixture[1],
        fixture[2],
        lambda: UtcTimestamp.parse("2042-01-01T00:00:00.000000Z"),
    )
    mutator = sqlite3.connect(database, isolation_level=None)
    mutator.execute("PRAGMA foreign_keys=OFF")
    return database, reader, reader_connection, mutator, first, last


_D2 = "sha256:" + "e" * 64


_SINGLE_INTEGRITY_MUTATIONS = (
    (
        "immutable_event_hypothesis_update",
        "UPDATE event_hypotheses_v2 SET canonical_bytes=?",
        (b"{}",),
    ),
    (
        "immutable_event_hypothesis_update",
        "UPDATE event_hypotheses_v2 SET canonical_digest=?",
        (_D2,),
    ),
    (
        "immutable_event_hypothesis_update",
        "UPDATE event_hypotheses_v2 SET actor_identity_digest=?",
        (_D2,),
    ),
    (
        "immutable_event_hypothesis_update",
        "UPDATE event_hypotheses_v2 SET authority_event_id=?",
        ("retargeted:event",),
    ),
    (
        "immutable_event_hypothesis_update",
        "UPDATE event_hypotheses_v2 SET recorded_at=?",
        ("2043-01-01T00:00:00.000000Z",),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET proposal_id=?",
        ("00000000-0000-4000-8000-000000000998",),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET version_id=?",
        ("00000000-0000-4000-8000-000000000998",),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET hypothesis_id=?",
        ("00000000-0000-4000-8000-000000000998",),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET proposal_local_id=?",
        ("hypothesis:retargeted",),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET proposal_content_identity=?",
        (_D2,),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET proposal_canonical_digest=?",
        (_D2,),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET proposal_canonical_bytes=?",
        (b"{}",),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET work_item_id=?",
        ("00000000-0000-4000-8000-000000000998",),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET work_item_version_digest=?",
        (_D2,),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET work_item_version_id=?",
        ("00000000-0000-4000-8000-000000000998",),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET retrieval_context_digest=?",
        (_D2,),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET retrieval_context_id=?",
        ("00000000-0000-4000-8000-000000000998",),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET actor_identity_digest=?",
        (_D2,),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET authority_event_id=?",
        ("retargeted:event",),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET recorded_at=?",
        ("2043-01-01T00:00:00.000000Z",),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET canonical_bytes=?",
        (b"{}",),
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET canonical_digest=?",
        (_D2,),
    ),
    (
        "immutable_triage_proposal_dispositions_update",
        "UPDATE triage_proposal_dispositions SET work_item_version_digest=?",
        (_D2,),
    ),
    ("retained_event_hypothesis_delete", "DELETE FROM event_hypotheses_v2", ()),
    (
        "retained_event_hypothesis_version_delete",
        "DELETE FROM event_hypothesis_versions_v2",
        (),
    ),
    (
        "retained_event_hypothesis_head_delete",
        "DELETE FROM event_hypothesis_heads_v2",
        (),
    ),
    (
        "event_hypothesis_head_update_guard",
        "UPDATE event_hypothesis_heads_v2 SET updated_at=?",
        ("2043-01-01T00:00:00.000000Z",),
    ),
)


def test_retained_single_version_integrity_mutations_fail_current_and_reopen(
    tmp_path,
) -> None:
    fixture = _authority_fixture(tmp_path)
    seed = _open(fixture)
    first = seed.retain(fixture[4], fixture[5], proof=fixture[3])
    seed.close()
    for index, (trigger, statement, parameters) in enumerate(
        _SINGLE_INTEGRITY_MUTATIONS
    ):
        database = tmp_path / f"retained-{index}.sqlite3"
        copied = sqlite3.connect(database, isolation_level=None)
        fixture[0].backup(copied)
        copied.close()
        reader_connection = sqlite3.connect(database, isolation_level=None)
        reader = _HypothesisStore(
            reader_connection, fixture[1], fixture[2], UtcTimestamp.now
        )
        mutator = sqlite3.connect(database, isolation_level=None)
        mutator.execute("PRAGMA foreign_keys=OFF")
        try:
            mutator.execute(f"DROP TRIGGER {trigger}")
            mutator.execute(statement, parameters)
            with pytest.raises(HypothesisContractError):
                reader.current(first.hypothesis_id, proof=fixture[3])
            reopen_connection = sqlite3.connect(database, isolation_level=None)
            try:
                with pytest.raises(HypothesisContractError):
                    _HypothesisStore(
                        reopen_connection, fixture[1], fixture[2], UtcTimestamp.now
                    )
            finally:
                reopen_connection.close()
        finally:
            mutator.close()
            reader_connection.close()


_CHAIN_INTEGRITY_MUTATIONS = (
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET previous_version_digest='sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee' WHERE ordinal=2",
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET previous_version_id=version_id WHERE ordinal=2",
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET ordinal=3 WHERE ordinal=2",
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET proposed_target_hypothesis_id='00000000-0000-4000-8000-000000000998' WHERE ordinal=2",
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET target_version_id=version_id WHERE ordinal=2",
    ),
    (
        "immutable_event_hypothesis_version_update",
        "UPDATE event_hypothesis_versions_v2 SET target_version_digest='sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee' WHERE ordinal=2",
    ),
    (
        "retained_event_hypothesis_version_delete",
        "DELETE FROM event_hypothesis_versions_v2 WHERE ordinal=1",
    ),
    (
        "retained_event_hypothesis_version_delete",
        "DELETE FROM event_hypothesis_versions_v2 WHERE ordinal=2",
    ),
    ("retained_event_hypothesis_head_delete", "DELETE FROM event_hypothesis_heads_v2"),
    (
        "event_hypothesis_head_update_guard",
        "UPDATE event_hypothesis_heads_v2 SET version_id=(SELECT version_id FROM event_hypothesis_versions_v2 WHERE ordinal=1),ordinal=1,version_digest=(SELECT canonical_digest FROM event_hypothesis_versions_v2 WHERE ordinal=1)",
    ),
    (
        "event_hypothesis_head_insert_guard",
        "INSERT INTO event_hypothesis_heads_v2 VALUES('00000000-0000-4000-8000-000000000997','00000000-0000-4000-8000-000000000996',1,'sha256:eeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeeee','2042-01-01T00:00:00.000000Z')",
    ),
)


def test_retained_chain_gaps_and_noncontiguous_links_fail_closed(
    tmp_path,
) -> None:
    fixture = _authority_fixture(tmp_path)
    seed = _open(fixture)
    first = seed.retain(fixture[4], fixture[5], proof=fixture[3])
    raw, source = _targeted_proposal(
        fixture,
        proposal_id="00000000-0000-4000-8000-000000000991",
        local_id="hypothesis:integrity-append",
        relationship="SAME_STATE",
        target=first.hypothesis_id,
    )
    last = seed.retain(raw, source, proof=fixture[3], expected_target_version=first)
    seed.close()
    for index, (trigger, statement) in enumerate(_CHAIN_INTEGRITY_MUTATIONS):
        database = tmp_path / f"chain-{index}.sqlite3"
        copied = sqlite3.connect(database, isolation_level=None)
        fixture[0].backup(copied)
        copied.close()
        reader_connection = sqlite3.connect(database, isolation_level=None)
        reader = _HypothesisStore(
            reader_connection, fixture[1], fixture[2], UtcTimestamp.now
        )
        mutator = sqlite3.connect(database, isolation_level=None)
        mutator.execute("PRAGMA foreign_keys=OFF")
        try:
            mutator.execute(f"DROP TRIGGER {trigger}")
            mutator.execute(statement)
            with pytest.raises(HypothesisContractError):
                reader.current(last.hypothesis_id, proof=fixture[3])
            reopen_connection = sqlite3.connect(database, isolation_level=None)
            try:
                with pytest.raises(HypothesisContractError):
                    _HypothesisStore(
                        reopen_connection, fixture[1], fixture[2], UtcTimestamp.now
                    )
            finally:
                reopen_connection.close()
        finally:
            mutator.close()
            reader_connection.close()
