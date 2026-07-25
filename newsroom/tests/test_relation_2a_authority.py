from __future__ import annotations

from dataclasses import replace
from pathlib import Path
from threading import RLock

import pytest

from newsroom.authority import (
    AuthenticationError,
    AuthorizationDenied,
    IdempotencyIdentityConflict,
    UtcTimestamp,
)
import newsroom.authority._relation_store as relation_store_module
from newsroom.authority._relation_store import _RelationAuthorityStore
from newsroom.relations import (
    INTEGRATED_FIXTURE_V2,
    RelationAdmissionDecisionId,
    RelationAssertionId,
    RelationCurrentState,
    RelationDecisionAction,
    RelationPredicate,
    RelationProducer,
    RelationProducerKind,
    RelationProposalId,
    RelationSemanticCollision,
    RelationStaleDecision,
    RelationStateError,
)

from .relation_2a_helpers import (
    BINDING_ID,
    PROPOSAL_ID,
    RELATION_NOW,
    RelationClock,
    SECOND_PROPOSAL_ID,
    bind_fixture_and_propose,
    decision_request,
    open_relation_system,
    proof,
    scopes,
    seed_fixture_objects,
)


def test_exact_fixture_proposal_admission_exposes_only_admitted_assertion(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(database, object_root=tmp_path / "objects")
    proposal = bind_fixture_and_propose(database, seeded)

    with open_relation_system(database) as system:
        assert system.relations.admitted(
            valid_at=RELATION_NOW, proof=proof()
        ) == ()
        assert system.relations.projection_events_after(
            0, valid_at=RELATION_NOW, proof=proof()
        ) == ()

        result = system.relations.decide(
            decision_request(proposal, action=RelationDecisionAction.ADMIT),
            proof=proof(),
        )

        assert result.current_state is RelationCurrentState.ADMITTED
        assert result.assertion is not None
        assert result.assertion.predicate is RelationPredicate.DEVELOPMENT_OF
        assert result.assertion.trust_scope.value == "ADMITTED"
        assert result.assertion.statement == INTEGRATED_FIXTURE_V2.relation.statement
        assert result.assertion.evidence_passage_ids == (
            INTEGRATED_FIXTURE_V2.relation.evidence_passage_ids
        )
        assert len(result.assertion.evidence_objects) == 4

        admitted = system.relations.admitted(
            valid_at=RELATION_NOW, proof=proof()
        )
        assert admitted == (result.assertion,)
        projection = system.relations.projection_events_after(
            0, valid_at=RELATION_NOW, proof=proof()
        )
        assert len(projection) == 1
        assert projection[0].action.value == "UPSERT"
        assert projection[0].assertion == result.assertion


def test_admitted_surface_applies_relation_valid_time_without_rewriting_history(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    object_root = tmp_path / "objects"
    clock = RelationClock(
        UtcTimestamp.parse("2042-03-01T12:00:00.000000Z")
    )
    seeded = seed_fixture_objects(
        database, object_root=object_root, clock=clock
    )
    proposal = bind_fixture_and_propose(
        database, seeded, clock=clock
    )

    with open_relation_system(database, clock=clock) as system:
        admitted = system.relations.decide(
            decision_request(
                proposal,
                action=RelationDecisionAction.ADMIT,
                key="future-valid-relation",
            ),
            proof=proof(),
        )
        assert admitted.assertion is not None
        assert system.relations.admitted(
            valid_at=UtcTimestamp.parse("2042-03-11T23:59:59.000000Z"),
            proof=proof(),
        ) == ()
        assert system.relations.admitted(
            valid_at=UtcTimestamp.parse("2042-03-12T10:00:00.000000Z"),
            proof=proof(),
        ) == (admitted.assertion,)
        assert system.relations.decision(
            admitted.decision.decision_id, proof=proof()
        ) == admitted.decision


def test_admitted_limit_applies_after_current_authority_filtering(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (
        {"relation_key": "relation:a", "assertion": "invalid"},
        {"relation_key": "relation:b", "assertion": "valid"},
    )

    class _Cursor:
        def fetchall(self):
            return list(rows)

    class _Connection:
        def execute(self, sql: str, parameters: tuple[object, ...]):
            assert "ORDER BY a.relation_key LIMIT ?" in sql
            # The caller limit is one, but filtering happens after reading a
            # bounded batch so an invalid first row cannot starve a valid row.
            assert parameters == (64,)
            return _Cursor()

    store = object.__new__(_RelationAuthorityStore)
    store._lock = RLock()
    store._closed = False
    store._conn = _Connection()
    monkeypatch.setattr(
        _RelationAuthorityStore,
        "_assertion_from_row",
        classmethod(lambda cls, conn, row: row["assertion"]),
    )
    monkeypatch.setattr(
        _RelationAuthorityStore,
        "_assertion_object_state",
        classmethod(
            lambda cls, conn, assertion, now: (
                assertion == "valid",
                "OBJECT_CURRENT",
                None,
                (),
            )
        ),
    )
    monkeypatch.setattr(
        _RelationAuthorityStore,
        "_assertion_is_valid_at",
        staticmethod(lambda assertion, valid_at: True),
    )

    assert store.admitted_assertions(now=RELATION_NOW, limit=1) == ("valid",)


def test_current_relation_reads_fail_closed_when_internal_scan_bound_is_exceeded(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    rows = (
        {"relation_key": "relation:a"},
        {"relation_key": "relation:b"},
    )

    class _Cursor:
        def fetchall(self):
            return list(rows)

    class _Connection:
        def execute(self, sql: str, parameters: tuple[object, ...] = ()):
            assert parameters == (2,)
            return _Cursor()

    store = object.__new__(_RelationAuthorityStore)
    store._lock = RLock()
    store._closed = False
    store._conn = _Connection()
    monkeypatch.setattr(
        relation_store_module,
        "_MAX_RELATION_CURRENT_SCAN",
        1,
    )

    with pytest.raises(
        RelationStateError,
        match="admitted relation current-state scan exceeds its bound",
    ):
        store.admitted_assertions(now=RELATION_NOW, limit=1)

    with pytest.raises(
        RelationStateError,
        match="relation projection current-state scan exceeds its bound",
    ):
        store.projection_events_after(
            after_ledger_seq=0,
            now=RELATION_NOW,
            limit=1,
        )


def test_projection_rebuild_fails_closed_without_ordered_lifecycle_event(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(database, object_root=tmp_path / "objects")
    proposal = bind_fixture_and_propose(database, seeded)
    with open_relation_system(database) as system:
        result = system.relations.decide(
            decision_request(
                proposal,
                action=RelationDecisionAction.ADMIT,
                key="admit-before-missing-lifecycle-test",
            ),
            proof=proof(),
        )
    assertion = result.assertion
    assert assertion is not None

    class _Cursor:
        def __init__(self, *, rows=(), row=None):
            self._rows = tuple(rows)
            self._row = row

        def fetchall(self):
            return list(self._rows)

        def fetchone(self):
            return self._row

    class _Connection:
        def execute(self, sql: str, parameters: tuple[object, ...] = ()):
            if sql.startswith("SELECT * FROM relation_assertions"):
                return _Cursor(rows=({"assertion": assertion},))
            if "FROM relation_admission_decisions" in sql:
                assert parameters == (str(assertion.admission_decision_id),)
                return _Cursor(
                    row={
                        "authority_ledger_seq": 10,
                        "authority_event_id": str(result.decision.authority_event_id),
                    }
                )
            raise AssertionError(f"unexpected SQL: {sql}")

    store = object.__new__(_RelationAuthorityStore)
    store._lock = RLock()
    store._closed = False
    store._conn = _Connection()
    monkeypatch.setattr(
        _RelationAuthorityStore,
        "_assertion_from_row",
        classmethod(lambda cls, conn, row: row["assertion"]),
    )
    monkeypatch.setattr(
        _RelationAuthorityStore,
        "_current_decision_head",
        classmethod(
            lambda cls, conn, proposal_id: {
                "current_state": RelationCurrentState.ADMITTED.value,
                "authority_ledger_seq": 10,
                "authority_event_id": str(result.decision.authority_event_id),
            }
        ),
    )
    monkeypatch.setattr(
        _RelationAuthorityStore,
        "_assertion_object_state",
        classmethod(
            lambda cls, conn, current_assertion, now: (
                False,
                "OBJECT_RIGHTS_DENIED",
                None,
                (current_assertion.evidence_admission_ids[0],),
            )
        ),
    )

    with pytest.raises(
        RelationStateError,
        match="invalid admitted relation lacks an ordered lifecycle event",
    ):
        store.projection_events_after(
            after_ledger_seq=0,
            now=RELATION_NOW,
            limit=10,
        )


def test_projection_page_never_splits_one_ledger_sequence(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(database, object_root=tmp_path / "objects")
    proposal = bind_fixture_and_propose(database, seeded)
    with open_relation_system(database) as system:
        result = system.relations.decide(
            decision_request(
                proposal,
                action=RelationDecisionAction.ADMIT,
                key="admit-before-atomic-page-test",
            ),
            proof=proof(),
        )
    first = result.assertion
    assert first is not None
    second = replace(
        first,
        assertion_id=RelationAssertionId.parse(
            "00000000-0000-4000-8000-000000000491"
        ),
        proposal_id=RelationProposalId.parse(
            "00000000-0000-4000-8000-000000000492"
        ),
        admission_decision_id=RelationAdmissionDecisionId.parse(
            "00000000-0000-4000-8000-000000000493"
        ),
        relation_key="sha256:" + "0" * 64,
    )
    invalid_id = first.evidence_objects[0].admission_id
    lifecycle_event_id = result.decision.authority_event_id

    class _Cursor:
        def __init__(self, *, rows=(), row=None):
            self._rows = tuple(rows)
            self._row = row

        def fetchall(self):
            return list(self._rows)

        def fetchone(self):
            return self._row

    assertions = {
        str(first.assertion_id): first,
        str(second.assertion_id): second,
    }

    class _Connection:
        def execute(self, sql: str, parameters: tuple[object, ...] = ()):
            if sql.startswith("SELECT * FROM relation_assertions"):
                return _Cursor(
                    rows=tuple(
                        {"assertion_id": assertion_id}
                        for assertion_id in assertions
                    )
                )
            if "FROM relation_admission_decisions" in sql:
                decision_id = str(parameters[0])
                assert decision_id in {
                    str(first.admission_decision_id),
                    str(second.admission_decision_id),
                }
                return _Cursor(
                    row={
                        "authority_ledger_seq": 10,
                        "authority_event_id": str(lifecycle_event_id),
                    }
                )
            raise AssertionError(f"unexpected SQL: {sql}")

    store = object.__new__(_RelationAuthorityStore)
    store._lock = RLock()
    store._closed = False
    store._conn = _Connection()
    monkeypatch.setattr(
        _RelationAuthorityStore,
        "_assertion_from_row",
        classmethod(
            lambda cls, conn, row: assertions[str(row["assertion_id"])]
        ),
    )
    monkeypatch.setattr(
        _RelationAuthorityStore,
        "_current_decision_head",
        classmethod(
            lambda cls, conn, proposal_id: {
                "current_state": RelationCurrentState.ADMITTED.value,
                "authority_ledger_seq": 10,
                "authority_event_id": str(lifecycle_event_id),
            }
        ),
    )
    monkeypatch.setattr(
        _RelationAuthorityStore,
        "_assertion_object_state",
        classmethod(
            lambda cls, conn, assertion, now: (
                False,
                "OBJECT_ADMISSION_REVOKED",
                (99, lifecycle_event_id),
                (invalid_id,),
            )
        ),
    )

    with pytest.raises(
        RelationStateError,
        match="limit would split one ledger sequence",
    ):
        store.projection_events_after(
            after_ledger_seq=0,
            now=RELATION_NOW,
            limit=1,
        )

    page = store.projection_events_after(
        after_ledger_seq=0,
        now=RELATION_NOW,
        limit=2,
    )
    assert len(page) == 2
    assert {item.source_ledger_seq for item in page} == {99}
    assert {item.action.value for item in page} == {"REMOVE"}


def test_fixture_binding_records_exact_active_and_tombstoned_lifecycle_links(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(database, object_root=tmp_path / "objects")
    assert seeded.tombstone_event_id is not None

    with open_relation_system(database) as system:
        binding = system.relations.bind_fixture(
            seeded.binding_request, proof=proof()
        )

    links = {
        item.passage_id: item for item in binding.passage_lifecycle_links
    }
    assert set(links) == set(INTEGRATED_FIXTURE_V2.passage_by_id)
    tombstoned = links[INTEGRATED_FIXTURE_V2.tombstoned_negative_passage_id]
    assert tombstoned.expected_lifecycle == "TOMBSTONED"
    assert tombstoned.authority_event_id == seeded.tombstone_event_id
    assert all(
        item.expected_lifecycle == "ACTIVE"
        for passage_id, item in links.items()
        if passage_id != INTEGRATED_FIXTURE_V2.tombstoned_negative_passage_id
    )


def test_fixture_binding_rejects_metadata_only_tombstone_without_lifecycle_event(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(
        database,
        object_root=tmp_path / "objects",
        tombstone_negative=False,
    )

    with open_relation_system(database) as system:
        with pytest.raises(RelationStateError, match="governed TOMBSTONED"):
            system.relations.bind_fixture(
                seeded.binding_request, proof=proof()
            )


def test_binding_proposal_and_decision_replay_are_exact_and_idempotent(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(database, object_root=tmp_path / "objects")

    with open_relation_system(database) as system:
        first_binding = system.relations.bind_fixture(
            seeded.binding_request, proof=proof()
        )
        replay_binding = system.relations.bind_fixture(
            seeded.binding_request, proof=proof()
        )
        assert not first_binding.replayed
        assert replay_binding.replayed
        assert replay_binding.authority_event_id == first_binding.authority_event_id

        request = INTEGRATED_FIXTURE_V2.relation.request(
            proposal_id=PROPOSAL_ID,
            fixture_binding_id=BINDING_ID,
            idempotency_key="proposal-replay",
        )
        first_proposal = system.relations.propose(request, proof=proof())
        replay_proposal = system.relations.propose(request, proof=proof())
        assert not first_proposal.replayed
        assert replay_proposal.replayed
        assert replay_proposal.authority_event_id == first_proposal.authority_event_id

        decision = decision_request(
            first_proposal,
            action=RelationDecisionAction.ADMIT,
            key="decision-replay",
        )
        first_decision = system.relations.decide(decision, proof=proof())
        replay_decision = system.relations.decide(decision, proof=proof())
        assert not first_decision.decision.replayed
        assert replay_decision.decision.replayed
        assert replay_decision.decision.decision_id == first_decision.decision.decision_id
        assert replay_decision.assertion == first_decision.assertion


def test_same_idempotency_key_cannot_describe_different_relation_request(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(database, object_root=tmp_path / "objects")

    with open_relation_system(database) as system:
        system.relations.bind_fixture(seeded.binding_request, proof=proof())
        request = INTEGRATED_FIXTURE_V2.relation.request(
            proposal_id=PROPOSAL_ID,
            fixture_binding_id=BINDING_ID,
            idempotency_key="same-key",
        )
        system.relations.propose(request, proof=proof())
        changed = replace(
            request,
            proposal_id=SECOND_PROPOSAL_ID,
            statement="A different synthetic proposal occupies another identity.",
        )
        with pytest.raises(IdempotencyIdentityConflict):
            system.relations.propose(changed, proof=proof())


def test_exact_semantic_duplicate_with_new_identity_is_a_collision(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(database, object_root=tmp_path / "objects")
    proposal = bind_fixture_and_propose(database, seeded)

    duplicate = INTEGRATED_FIXTURE_V2.relation.request(
        proposal_id=SECOND_PROPOSAL_ID,
        fixture_binding_id=BINDING_ID,
        idempotency_key="duplicate-semantics",
    )
    with open_relation_system(database) as system:
        with pytest.raises(RelationSemanticCollision):
            system.relations.propose(duplicate, proof=proof())
        assert system.relations.proposal(proposal.proposal_id, proof=proof()) == proposal


def test_conflicting_same_slot_proposal_remains_proposal_only_and_cannot_admit(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(database, object_root=tmp_path / "objects")
    exact = bind_fixture_and_propose(database, seeded)
    conflict_request = replace(
        INTEGRATED_FIXTURE_V2.relation.request(
            proposal_id=SECOND_PROPOSAL_ID,
            fixture_binding_id=BINDING_ID,
            idempotency_key="conflicting-proposal",
        ),
        producer=RelationProducer(
            RelationProducerKind.AUTHORISED_OPERATOR,
            "fixture-reviewer",
            "fixture-reviewer-v1",
            "fixture-alternative-rule-v1",
        ),
        statement="An alternative proposal shares the axis but is not the fixture rule.",
    )

    with open_relation_system(database) as system:
        conflict = system.relations.propose(conflict_request, proof=proof())
        assert conflict.semantic_slot_digest == exact.semantic_slot_digest
        assert conflict.semantic_identity_digest != exact.semantic_identity_digest
        with pytest.raises(RelationStateError, match="exact governed fixture rule"):
            system.relations.decide(
                decision_request(
                    conflict,
                    action=RelationDecisionAction.ADMIT,
                    key="conflict-admit",
                ),
                proof=proof(),
            )
        assert system.relations.admitted(
            valid_at=RELATION_NOW, proof=proof()
        ) == ()
        assert system.relations.projection_events_after(
            0, valid_at=RELATION_NOW, proof=proof()
        ) == ()


def test_unadmitted_same_event_distractor_never_reaches_admitted_surface(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(database, object_root=tmp_path / "objects")
    exact = bind_fixture_and_propose(database, seeded)
    distractor_request = replace(
        INTEGRATED_FIXTURE_V2.relation.request(
            proposal_id=SECOND_PROPOSAL_ID,
            fixture_binding_id=BINDING_ID,
            idempotency_key="same-event-distractor",
        ),
        predicate=RelationPredicate.SAME_EVENT_AS,
        producer=RelationProducer(
            RelationProducerKind.AUTHORISED_OPERATOR,
            "fixture-reviewer",
            "fixture-reviewer-v1",
            "fixture-distractor-rule-v1",
        ),
        statement=(
            "This synthetic SAME_EVENT_AS proposal is retained only as an "
            "unadmitted distractor."
        ),
    )

    with open_relation_system(database) as system:
        distractor = system.relations.propose(
            distractor_request, proof=proof()
        )
        assert distractor.predicate is RelationPredicate.SAME_EVENT_AS
        admitted = system.relations.decide(
            decision_request(exact, action=RelationDecisionAction.ADMIT),
            proof=proof(),
        )
        assert admitted.assertion is not None
        assert system.relations.admitted(
            valid_at=RELATION_NOW, proof=proof()
        ) == (admitted.assertion,)
        events = system.relations.projection_events_after(
            0, valid_at=RELATION_NOW, proof=proof()
        )
        assert len(events) == 1
        assert events[0].assertion is not None
        assert events[0].assertion.predicate is RelationPredicate.DEVELOPMENT_OF
        assert all(
            event.assertion is not None
            and event.assertion.proposal_id != distractor.proposal_id
            for event in events
        )


def test_hold_then_admit_requires_exact_current_decision_head(tmp_path: Path) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(database, object_root=tmp_path / "objects")
    proposal = bind_fixture_and_propose(database, seeded)

    with open_relation_system(database) as system:
        held = system.relations.decide(
            decision_request(
                proposal,
                action=RelationDecisionAction.HOLD,
                key="hold-first",
            ),
            proof=proof(),
        )
        assert held.current_state is RelationCurrentState.HELD
        assert held.assertion is None

        with pytest.raises(RelationStaleDecision):
            system.relations.decide(
                decision_request(
                    proposal,
                    action=RelationDecisionAction.ADMIT,
                    expected_version=0,
                    key="stale-admit",
                ),
                proof=proof(),
            )

        admitted = system.relations.decide(
            decision_request(
                proposal,
                action=RelationDecisionAction.ADMIT,
                expected_version=1,
                previous_decision_id=held.decision.decision_id,
                key="admit-after-hold",
            ),
            proof=proof(),
        )
        assert admitted.current_state is RelationCurrentState.ADMITTED
        assert admitted.decision.decision_version == 2


def test_reject_and_invalidate_are_immutable_non_projection_routes(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(database, object_root=tmp_path / "objects")
    proposal = bind_fixture_and_propose(database, seeded)

    with open_relation_system(database) as system:
        rejected = system.relations.decide(
            decision_request(
                proposal,
                action=RelationDecisionAction.REJECT,
                key="reject",
            ),
            proof=proof(),
        )
        assert rejected.current_state is RelationCurrentState.REJECTED
        assert system.relations.projection_events_after(
            0, valid_at=RELATION_NOW, proof=proof()
        ) == ()

        invalidated = system.relations.decide(
            decision_request(
                proposal,
                action=RelationDecisionAction.INVALIDATE,
                expected_version=1,
                previous_decision_id=rejected.decision.decision_id,
                key="invalidate-rejected",
            ),
            proof=proof(),
        )
        assert invalidated.current_state is RelationCurrentState.INVALIDATED
        with pytest.raises(RelationStateError, match="invalid"):
            system.relations.decide(
                decision_request(
                    proposal,
                    action=RelationDecisionAction.ADMIT,
                    expected_version=2,
                    previous_decision_id=invalidated.decision.decision_id,
                    key="admit-invalidated",
                ),
                proof=proof(),
            )


def test_authentication_and_authorization_fail_before_relation_mutation(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(database, object_root=tmp_path / "objects")

    with open_relation_system(database) as system:
        with pytest.raises(AuthenticationError):
            system.relations.bind_fixture(
                seeded.binding_request, proof=proof(credential="wrong")
            )

    missing_bind = scopes() - {"authority.fixture.v2.bind"}
    with open_relation_system(database, granted_scopes=missing_bind) as system:
        with pytest.raises(AuthorizationDenied):
            system.relations.bind_fixture(seeded.binding_request, proof=proof())


def test_relation_metadata_and_projection_reads_require_distinct_scopes(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    seeded = seed_fixture_objects(database, object_root=tmp_path / "objects")
    proposal = bind_fixture_and_propose(database, seeded)
    with open_relation_system(database) as system:
        admitted = system.relations.decide(
            decision_request(
                proposal,
                action=RelationDecisionAction.ADMIT,
                key="admit-before-read-scope-check",
            ),
            proof=proof(),
        )
    assert admitted.assertion is not None

    projection_only = frozenset({"authority.relation.project"})
    with open_relation_system(database, granted_scopes=projection_only) as system:
        with pytest.raises(AuthorizationDenied):
            system.relations.fixture_binding(BINDING_ID, proof=proof())
        with pytest.raises(AuthorizationDenied):
            system.relations.proposal(proposal.proposal_id, proof=proof())
        with pytest.raises(AuthorizationDenied):
            system.relations.decision(
                admitted.decision.decision_id,
                proof=proof(),
            )
        assert system.relations.admitted(
            valid_at=RELATION_NOW,
            proof=proof(),
        ) == (admitted.assertion,)
        projection = system.relations.projection_events_after(
            0,
            valid_at=RELATION_NOW,
            proof=proof(),
        )
        assert len(projection) == 1
        assert projection[0].assertion == admitted.assertion

    metadata_only = frozenset({"authority.relation.metadata.read"})
    with open_relation_system(database, granted_scopes=metadata_only) as system:
        assert system.relations.proposal(
            proposal.proposal_id,
            proof=proof(),
        ) == proposal
        with pytest.raises(AuthorizationDenied):
            system.relations.admitted(
                valid_at=RELATION_NOW,
                proof=proof(),
            )
        with pytest.raises(AuthorizationDenied):
            system.relations.projection_events_after(
                0,
                valid_at=RELATION_NOW,
                proof=proof(),
            )
