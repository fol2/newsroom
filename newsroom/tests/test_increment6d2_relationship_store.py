from __future__ import annotations

import json
import os
import sqlite3
import uuid
from collections.abc import Callable
from dataclasses import replace
from pathlib import Path
from typing import ClassVar

import pytest

from newsroom.authority._event_hypothesis_relationship_system import (
    _open_unlocked_relationship_authority_for_test,
)
from newsroom.authority.auth import AuthenticationProof, StaticAuthorizer
from newsroom.authority.migrations import (
    apply_pending_migrations,
    prepare_pending_migration_backup,
)
from newsroom.authority.persistence import AuthoritySchemaError
from newsroom.authority.types import UtcTimestamp
from newsroom.checks.policy import merge_discovery_check_authority_registries
from newsroom.discovery.policy import merge_discovery_signal_lead_registries
from newsroom.increment6.dispositions import ProposalDispositionStore
from newsroom.increment6.outcomes import (
    CanonicalNextAction,
    CanonicalOutcome,
    ReasonCode,
)
from newsroom.increment6.relationships import (
    ComparatorEvidence,
    ComparatorSetManifest,
    EventHypothesisRelationshipAuthority,
    HypothesisVersionBinding,
    RelationshipContractError,
    assess_relationships,
    open_event_hypothesis_relationship_authority,
    relationship_command_definition,
)
from newsroom.increment6.work_items import (
    DecisionLeadBinding,
    RetrievalContextAuthority,
    RetrievalInputBinding,
    TriageWorkItem,
    TriageWorkItemStore,
)
from newsroom.sources.policy import merge_source_registry_authority_registries
from newsroom.tests import test_increment6c2_dispositions as disposition_helpers
from newsroom.tests import test_increment6d1_hypothesis_store as hypothesis_helpers
from newsroom.tests.authority_event_helpers import payload_schemas, registry_v1
from newsroom.tests.authority_store_conformance import (
    CASE_INVENTORY,
    Applicability,
    AuthorityValue,
    BindingConflict,
    CaseId,
    IntegrityViolation,
    LostResponse,
    RollbackScope,
    StoredAuthorityState,
    TamperKind,
    WriteCommand,
    run_conformance,
)
from newsroom.tests.discovery_3d_authority_helpers import (
    exact_admission_request,
    open_discovery_system,
    seed_check_lineage,
)
from newsroom.tests.discovery_3d_authority_helpers import (
    proof as discovery_proof,
)
from newsroom.tests.test_increment5d1_hybrid_composer import branch_inputs
from newsroom.tests.test_increment5d2_retrieval_context import (
    _retained_complete_context,
)


def _independent_version(fixture, label: str):
    connection, retrieval, authenticator, proof, *_, receipt, sources = fixture
    version, decision = sources.pop(0)
    document = json.loads(
        disposition_helpers._persistable_proposal(version, decision, receipt)
    )
    document["proposal"]["proposal_id"] = str(uuid.uuid4())
    document["proposal"]["recommendations"][0]["hypothesis"]["proposal_local_id"] = (
        label
    )
    raw = disposition_helpers._resign(document)
    selection = disposition_helpers._selection(
        CanonicalOutcome.LEAD_ADMIT_NEW_CANDIDATE,
        CanonicalNextAction.HANDOFF_FOR_EVALUATION,
        ReasonCode.NOVELTY_LIKELY_NEW_EVENT,
    )
    dispositions = ProposalDispositionStore(
        connection, retrieval, authenticator
    ).persist(raw, {decision.lead_id: selection}, proof=proof)
    authority = hypothesis_helpers._open(fixture)
    try:
        return authority.retain(raw, dispositions, proof=proof)
    finally:
        authority.close()


def _downgrade_checked_v22_to_v21(database: Path) -> None:
    target = sqlite3.connect(database, isolation_level=None)
    target.execute("PRAGMA foreign_keys=OFF")
    guard = target.execute(
        "SELECT sql FROM sqlite_master WHERE name='immutable_authority_migrations_delete'"
    ).fetchone()[0]
    target.execute("DROP TRIGGER immutable_authority_migrations_delete")
    for trigger in (
        "retained_event_hypothesis_relationship_delete",
        "immutable_event_hypothesis_relationship_update",
        "event_hypothesis_relationship_coherence",
    ):
        target.execute(f"DROP TRIGGER {trigger}")
    target.execute("DROP TABLE event_hypothesis_relationship_decisions")
    target.execute("DELETE FROM authority_migrations WHERE version=22")
    target.execute(guard)
    target.execute("PRAGMA user_version=21")
    target.execute("PRAGMA foreign_keys=ON")
    target.close()
    os.chmod(database, 0o600)


def _collaborators(fixture):
    definition = relationship_command_definition()
    commands, schemas = merge_source_registry_authority_registries(
        command_registry=registry_v1(), payload_schemas=payload_schemas()
    )
    commands, schemas = merge_discovery_check_authority_registries(
        command_registry=commands, payload_schemas=schemas
    )
    commands, schemas = merge_discovery_signal_lead_registries(
        command_registry=commands, payload_schemas=schemas
    )
    authorizer = StaticAuthorizer(
        policy_version="relationship-test-v1",
        grants_by_principal={
            "editor": frozenset({definition.required_scope}),
            "other": frozenset({definition.required_scope}),
        },
    )
    return commands, schemas, authorizer


def _assessment(subject, comparator, outcome: str = "REL_UNCERTAIN", salt: int = 0):
    subject_binding = HypothesisVersionBinding.from_version(subject)
    comparator_binding = HypothesisVersionBinding.from_version(comparator)
    scores = {
        "REL_SAME_STATE": (80, 0, 0, 80, 0),
        "REL_DEVELOPMENT_OF": (80, 0, 75, 0, 0),
        "REL_CORRECTION_REVERSAL_OF": (80, 80, 0, 0, 0),
        "REL_RELATED_DISTINCT": (80, 0, 0, 0, 60),
        "REL_NO_ADEQUATE_PRIOR_MATCH": (0, 0, 0, 0, 0),
        "REL_UNCERTAIN": (60 + salt % 40, salt % 60, 0, 0, 0),
    }[outcome]
    evidence = ComparatorEvidence(subject_binding, comparator_binding, *scores)
    assessment = assess_relationships(
        subject_binding,
        ComparatorSetManifest.complete((comparator_binding,)),
        (evidence,),
    )
    return assessment, (evidence.canonical_bytes,)


_SEED_CACHE = None


def _seed_location(root: Path, *, subjects: int = 6):
    global _SEED_CACHE
    root.mkdir(mode=0o700)
    database = root / "relationship-authority.sqlite3"
    if _SEED_CACHE is not None:
        database.write_bytes(_SEED_CACHE[0])
        os.chmod(database, 0o600)
        fixture, comparator, versions, commands, schemas, authorizer, append = (
            _SEED_CACHE[1:]
        )
        return (
            fixture,
            database,
            comparator,
            versions,
            commands,
            schemas,
            authorizer,
            append,
        )
    inputs = branch_inputs.__wrapped__(root)
    builder, _, _, _, _, request, receipt, _ = _retained_complete_context(
        root, inputs, name="relationship-authority"
    )
    retrieval = RetrievalContextAuthority(
        builder.journal.path, {request.request_digest: (request, receipt)}
    )
    decisions = []
    with open_discovery_system(database) as discovery:
        seed_check_lineage(discovery)
        for index in range(subjects + 2):
            admission = exact_admission_request()
            suffix = str(uuid.uuid4())
            gate_id = type(admission.gate.decision_id).parse(str(uuid.uuid4()))
            signal_id = type(admission.signal.signal_id).parse(str(uuid.uuid4()))
            lead_id = type(admission.lead.lead_id).parse(suffix)
            disposition_id = type(admission.initial_disposition.decision_id).parse(
                str(uuid.uuid4())
            )
            admission = __import__("dataclasses").replace(
                admission,
                signal=__import__("dataclasses").replace(
                    admission.signal,
                    signal_id=signal_id,
                    discriminator=f"relationship-{index}",
                    idempotency_key=f"relationship-signal-{index}",
                ),
                gate=__import__("dataclasses").replace(
                    admission.gate,
                    decision_id=gate_id,
                    signal_id=signal_id,
                    idempotency_key=f"relationship-gate-{index}",
                ),
                lead=__import__("dataclasses").replace(
                    admission.lead,
                    lead_id=lead_id,
                    signal_id=signal_id,
                    promoting_gate_decision_id=gate_id,
                    idempotency_key=f"relationship-lead-{index}",
                ),
                initial_disposition=__import__("dataclasses").replace(
                    admission.initial_disposition,
                    decision_id=disposition_id,
                    lead_id=lead_id,
                    gate_decision_id=gate_id,
                    idempotency_key=f"relationship-disposition-{index}",
                ),
            )
            admitted = discovery.discovery.admit_signal_to_lead(
                admission, proof=discovery_proof()
            )
            decisions.append(
                DecisionLeadBinding.from_authority(
                    admitted.lead, admitted.initial_disposition
                )
            )
    connection = sqlite3.connect(database, isolation_level=None)
    connection.execute("PRAGMA foreign_keys=ON")
    authenticator = hypothesis_helpers.StaticAuthenticator(
        credentials={
            "credential": hypothesis_helpers.StaticPrincipal("editor"),
            "other": hypothesis_helpers.StaticPrincipal("other"),
        },
        authority_domain="newsroom.dispositions",
    )
    proof = AuthenticationProof(method="STATIC_TOKEN", credential="credential")
    work_items = TriageWorkItemStore(connection, retrieval)
    versions = []
    items = []
    work_versions = []
    hypotheses = hypothesis_helpers._HypothesisStore(
        connection,
        retrieval,
        authenticator,
        lambda: UtcTimestamp.parse("2042-01-01T00:00:00.000000Z"),
    )
    for index, decision in enumerate(decisions):
        item = TriageWorkItem.create((decision,))
        items.append(item)
        work_version = __import__("dataclasses").replace(
            hypothesis_helpers.work_item_helpers._version(item),
            retrieval=RetrievalInputBinding.from_receipt(request, receipt),
        )
        work_items.create_or_replay(item, work_version)
        work_versions.append(work_version)
        if index == subjects + 1:
            continue
        proposal_document = json.loads(
            disposition_helpers._persistable_proposal(work_version, decision, receipt)
        )
        proposal_document["proposal"]["proposal_id"] = str(uuid.uuid4())
        proposal_document["proposal"]["recommendations"][0]["hypothesis"][
            "proposal_local_id"
        ] = f"relationship-{index}"
        proposal = disposition_helpers._resign(proposal_document)
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
        versions.append(hypotheses.retain(proposal, dispositions, proof=proof))
    authority_advance = hypothesis_helpers._targeted_proposal(
        (
            connection,
            retrieval,
            authenticator,
            proof,
            None,
            None,
            None,
            None,
            None,
            None,
            receipt,
            [(work_versions[-1], decisions[-1])],
        ),
        proposal_id=str(uuid.uuid4()),
        local_id="relationship-currentness-advance",
        relationship="DEVELOPMENT_OF",
        target=versions[1].hypothesis_id,
    )
    upstream_advances = {
        "authority": authority_advance,
        "policy": (items[1], work_versions[1]),
    }
    connection.close()
    comparator, *subject_versions = versions
    fixture = (None, retrieval, authenticator, proof)
    versions = tuple(subject_versions[:subjects])
    _downgrade_checked_v22_to_v21(database)
    commands, schemas, authorizer = _collaborators(fixture)
    _SEED_CACHE = (
        database.read_bytes(),
        fixture,
        comparator,
        versions,
        commands,
        schemas,
        authorizer,
        upstream_advances,
    )
    return (
        fixture,
        database,
        comparator,
        versions,
        commands,
        schemas,
        authorizer,
        upstream_advances,
    )


def _open_arguments(seed) -> dict[str, object]:
    fixture, database, _, _, commands, schemas, authorizer, _ = seed
    return {
        "database": database,
        "retrieval_authority": fixture[1],
        "authenticator": fixture[2],
        "authorizer": authorizer,
        "command_registry": commands,
        "payload_schemas": schemas,
        "clock": lambda: UtcTimestamp.parse("2042-01-02T00:00:00.000000Z"),
    }


def _open(seed):
    return open_event_hypothesis_relationship_authority(**_open_arguments(seed))


def _open_unlocked_for_test(seed):
    return _open_unlocked_relationship_authority_for_test(**_open_arguments(seed))


@pytest.mark.parametrize(
    "outcome",
    (
        "REL_SAME_STATE",
        "REL_DEVELOPMENT_OF",
        "REL_CORRECTION_REVERSAL_OF",
        "REL_RELATED_DISTINCT",
        "REL_NO_ADEQUATE_PRIOR_MATCH",
        "REL_UNCERTAIN",
    ),
)
def test_six_outcomes_anchor_exact_ledger_and_replay(tmp_path, outcome) -> None:
    seed = _seed_location(tmp_path / outcome)
    assessment, evidence = _assessment(seed[3][0], seed[2], outcome)
    authority = _open(seed)
    retained = authority.retain(assessment.canonical_bytes, evidence, proof=seed[0][3])
    assert (
        authority.retain(assessment.canonical_bytes, evidence, proof=seed[0][3])
        == retained
    )
    assert authority.load(retained.canonical_digest) == retained
    authority.close()
    connection = sqlite3.connect(seed[1])
    row = connection.execute(
        "SELECT authority_aggregate_id,authority_event_id,subject_version_id FROM event_hypothesis_relationship_decisions"
    ).fetchone()
    assert row[2] == assessment.subject.version_id
    assert connection.execute(
        "SELECT aggregate_id,event_type FROM ledger_events WHERE event_id=?", (row[1],)
    ).fetchone() == (row[0], "event_hypothesis_relationship_decision_retained")
    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []


def test_factory_lock_facade_and_self_consistent_rewrite_fail_closed(
    tmp_path, monkeypatch: pytest.MonkeyPatch
) -> None:
    seed = _seed_location(tmp_path / "guards")
    assessment, evidence = _assessment(seed[3][0], seed[2])
    authority = _open(seed)
    with pytest.raises(RelationshipContractError):
        _open(seed)

    with pytest.raises(RelationshipContractError):
        EventHypothesisRelationshipAuthority(object(), object())

    from newsroom.authority import event_hypothesis_relationship_system

    with monkeypatch.context() as patch:
        patch.setattr(
            event_hypothesis_relationship_system,
            "open_event_hypothesis_relationship_authority_system",
            lambda *_, **__: object(),
        )
        with pytest.raises(RelationshipContractError):
            open_event_hypothesis_relationship_authority(**_open_arguments(seed))

    class FakeStore:
        constructed = False

        def __init__(self, *_: object, **__: object) -> None:
            type(self).constructed = True

    with pytest.raises(TypeError):
        open_event_hypothesis_relationship_authority(
            **_open_arguments(seed), store_type=FakeStore
        )
    assert not FakeStore.constructed
    authority.retain(assessment.canonical_bytes, evidence, proof=seed[0][3])
    authority.close()
    reopened = _open(seed)
    assert reopened.load(assessment.canonical_digest) == assessment
    reopened.close()
    lock_path = seed[1].with_name(seed[1].name + ".writer.lock")
    lock_path.chmod(0o644)
    with pytest.raises(RelationshipContractError):
        _open(seed)
    assert lock_path.stat().st_mode & 0o777 == 0o644
    lock_path.chmod(0o600)
    connection = sqlite3.connect(seed[1], isolation_level=None)
    connection.execute("PRAGMA foreign_keys=OFF")
    connection.execute("DROP TRIGGER immutable_event_hypothesis_relationship_update")
    connection.execute(
        "UPDATE event_hypothesis_relationship_decisions SET actor_identity_digest=?,assessment_bytes=?,assessment_digest=?,decision_id=?",
        (
            "sha256:" + "0" * 64,
            assessment.canonical_bytes,
            assessment.canonical_digest,
            assessment.canonical_digest,
        ),
    )
    connection.execute("PRAGMA foreign_keys=ON")
    connection.close()
    with pytest.raises(RelationshipContractError):
        _open(seed)


class _Location:
    def __init__(self, seed) -> None:
        self.seed = seed
        ids = (
            "record-1",
            "record-2",
            "record-a",
            "record-b",
            "record-rollback-normal",
            "record-rollback-abort",
        )
        self.subjects = dict(zip(ids, seed[3], strict=True))
        self.subjects["record-b"] = self.subjects["record-a"]


def _generic(
    record_id: str, predecessor: str | None = None, value: str | None = None
) -> WriteCommand:
    predecessor = predecessor or ("record-1" if record_id == "record-2" else "record-0")
    value = value or ("beta" if record_id in {"record-2", "record-b"} else "alpha")
    return WriteCommand(
        record_id=record_id,
        canonical_bytes=f'{{"value":"{value}"}}'.encode(),
        scalar_columns={"value": value, "version": 1},
        identity_columns={"record_id": record_id, "authority": "fixture"},
        linked_rows=(
            {"child_id": f"child-{record_id}", "record_id": record_id, "ordinal": 0},
        ),
        actor="actor-1",
        request=f"request-{record_id}",
        idempotency=f"idempotency-{record_id}",
        cas_predecessor=predecessor,
        required_upstream_heads=(
            ("authority", "authority-head-1"),
            ("policy", "policy-head-1"),
        ),
    )


_RECORD_VALUES = (
    ("record-1", "alpha"),
    ("record-2", "beta"),
    ("record-a", "alpha"),
    ("record-b", "beta"),
    ("record-rollback-normal", "alpha"),
    ("record-rollback-abort", "alpha"),
)
_REQUEST_VALUES = ("different-request",) + tuple(
    f"request-{record_id}" for record_id, _ in _RECORD_VALUES
)
_IDEMPOTENCY_VALUES = ("different-idempotency",) + tuple(
    f"idempotency-{record_id}" for record_id, _ in _RECORD_VALUES
)
_CAS_VALUES = ("different-cas_predecessor", "record-0", "record-1")
_UPSTREAM_VALUES = ((("authority", "authority-head-1"), ("policy", "policy-head-1")),)
_ACTOR_PROOFS = {
    "actor-1": AuthenticationProof(method="STATIC_TOKEN", credential="credential"),
    "different-actor": AuthenticationProof(method="STATIC_TOKEN", credential="other"),
}
_PRINCIPAL_ACTORS = {"editor": "actor-1", "other": "different-actor"}


def _code(values: tuple, value: object, field: str) -> int:
    try:
        return values.index(value)
    except ValueError as exc:
        raise RelationshipContractError(
            f"unsupported conformance {field} binding"
        ) from exc


def _binding_assessment(location: _Location, command: WriteCommand):
    value = command.scalar_columns.get("value")
    record_code = _code(_RECORD_VALUES, (command.record_id, value), "record")
    base = _generic(command.record_id, command.cas_predecessor, value)
    if (
        command.canonical_bytes != base.canonical_bytes
        or command.scalar_columns != base.scalar_columns
        or command.identity_columns != base.identity_columns
        or command.linked_rows != base.linked_rows
    ):
        raise RelationshipContractError("unsupported conformance representation")
    request_code = _code(_REQUEST_VALUES, command.request, "request")
    idempotency_code = _code(_IDEMPOTENCY_VALUES, command.idempotency, "idempotency")
    cas_code = _code(_CAS_VALUES, command.cas_predecessor, "CAS predecessor")
    upstream_code = _code(_UPSTREAM_VALUES, command.required_upstream_heads, "upstream")
    if command.actor not in _ACTOR_PROOFS:
        raise RelationshipContractError("unsupported conformance actor binding")
    subject = HypothesisVersionBinding.from_version(
        location.subjects[command.record_id]
    )
    comparator = HypothesisVersionBinding.from_version(location.seed[2])
    evidence = ComparatorEvidence(
        subject,
        comparator,
        60 + request_code,
        idempotency_code,
        cas_code,
        record_code,
        upstream_code,
    )
    assessment = assess_relationships(
        subject,
        ComparatorSetManifest.complete((comparator,)),
        (evidence,),
    )
    return assessment, (evidence.canonical_bytes,)


class _Handle:
    def __init__(self, location: _Location) -> None:
        self.location = location
        self.authority = None
        self.open_error: Exception | None = None
        try:
            self.authority = _open_unlocked_for_test(location.seed)
        except Exception as exc:
            if not isinstance(exc, AuthoritySchemaError):
                raise
            self.open_error = exc

    def _opened(self):
        if self.open_error is not None:
            raise IntegrityViolation(
                "relationship authority open failed"
            ) from self.open_error
        assert self.authority is not None
        return self.authority

    def _domain(self, command: WriteCommand):
        return _binding_assessment(self.location, command)

    def _decision_id(self, command: WriteCommand) -> str:
        assessment, _ = self._domain(command)
        return assessment.canonical_digest

    def _decode_command(
        self, decision_id: str, *, connection: sqlite3.Connection | None = None
    ) -> WriteCommand:
        owned_connection = connection is None
        if connection is None:
            connection = sqlite3.connect(self.location.seed[1])
        try:
            row = connection.execute(
                "SELECT r.subject_version_id,r.evidence_bytes,a.principal_id "
                "FROM event_hypothesis_relationship_decisions r "
                "JOIN ledger_events e ON e.event_id=r.authority_event_id "
                "JOIN authority_commands c ON c.command_id=e.command_id "
                "JOIN authentication_contexts a ON a.authentication_context_id="
                "c.authentication_context_id WHERE r.decision_id=?",
                (decision_id,),
            ).fetchone()
            if row is None:
                raise RelationshipContractError("unknown conformance decision")
            evidence_values = json.loads(bytes(row[1]))
            if type(evidence_values) is not list or len(evidence_values) != 1:
                raise RelationshipContractError("conformance evidence binding differs")
            evidence = ComparatorEvidence.from_value(evidence_values[0])
            request_code = evidence.score - 60
            record_code = evidence.same_state_score
            upstream_code = evidence.related_distinct_score
            codes = (
                (request_code, len(_REQUEST_VALUES)),
                (record_code, len(_RECORD_VALUES)),
                (
                    evidence.correction_reversal_score,
                    len(_IDEMPOTENCY_VALUES),
                ),
                (evidence.development_score, len(_CAS_VALUES)),
                (upstream_code, len(_UPSTREAM_VALUES)),
            )
            if any(code < 0 or code >= size for code, size in codes):
                raise RelationshipContractError("conformance authority binding differs")
            try:
                record_id, value = _RECORD_VALUES[record_code]
                request = _REQUEST_VALUES[request_code]
                idempotency = _IDEMPOTENCY_VALUES[evidence.correction_reversal_score]
                predecessor = _CAS_VALUES[evidence.development_score]
                upstream = _UPSTREAM_VALUES[upstream_code]
                actor = _PRINCIPAL_ACTORS[str(row[2])]
            except (IndexError, KeyError) as exc:
                raise RelationshipContractError(
                    "conformance authority binding differs"
                ) from exc
            if self.location.subjects[record_id].version_id != str(row[0]):
                raise RelationshipContractError("conformance subject binding differs")
            return replace(
                _generic(record_id, predecessor, value),
                actor=actor,
                request=request,
                idempotency=idempotency,
                required_upstream_heads=upstream,
            )
        finally:
            if owned_connection:
                connection.close()

    def submit(
        self, command: WriteCommand, *, lose_response: bool = False
    ) -> AuthorityValue:
        try:
            assessment, evidence = self._domain(command)
            proof = _ACTOR_PROOFS[command.actor]
        except (KeyError, RelationshipContractError) as exc:
            raise BindingConflict(command.record_id) from exc
        try:
            retained = self._opened().retain(
                assessment.canonical_bytes, evidence, proof=proof
            )
        except Exception as exc:
            retained = self._subject_row(command.record_id)
            if retained is not None:
                try:
                    self._opened().load(str(retained[0]))
                except Exception as integrity_exc:
                    raise IntegrityViolation(command.record_id) from integrity_exc
                raise BindingConflict(command.record_id) from exc
            raise IntegrityViolation(command.record_id) from exc
        if lose_response:
            raise LostResponse(command.record_id)
        return AuthorityValue.from_command(
            self._decode_command(retained.canonical_digest)
        )

    def _row(self, record_id: str):
        decision_id = self._decision_id(_generic(record_id))
        connection = sqlite3.connect(self.location.seed[1])
        row = connection.execute(
            "SELECT decision_id FROM event_hypothesis_relationship_decisions "
            "WHERE decision_id=?",
            (decision_id,),
        ).fetchone()
        connection.close()
        return row

    def _subject_row(self, record_id: str):
        subject = self.location.subjects[record_id]
        connection = sqlite3.connect(self.location.seed[1])
        row = connection.execute(
            "SELECT decision_id FROM event_hypothesis_relationship_decisions "
            "WHERE subject_version_id=?",
            (subject.version_id,),
        ).fetchone()
        connection.close()
        return row

    def observe(self, record_id: str):
        row = self._subject_row(record_id)
        if row is None:
            return None
        try:
            self._opened().load(str(row[0]))
            command = self._decode_command(str(row[0]))
        except Exception as exc:
            raise IntegrityViolation(record_id) from exc
        if command.record_id != record_id:
            return None
        return StoredAuthorityState.from_command(command)

    def history(self):
        try:
            retained = self._opened().history()
        except Exception as exc:
            raise IntegrityViolation("history") from exc
        return tuple(
            AuthorityValue.from_command(self._decode_command(item.canonical_digest))
            for item in retained
        )

    def read(self, record_id):
        row = self._subject_row(record_id)
        state = self.observe(record_id)
        if row is None or state is None:
            raise KeyError(record_id)
        return AuthorityValue.from_command(self._decode_command(str(row[0])))

    list_history = history

    def set_upstream_head(self, authority, value):
        if value.endswith("head-1") or self._row("record-1") is None:
            return
        subject = self.location.subjects["record-1"]
        connection = sqlite3.connect(self.location.seed[1], isolation_level=None)
        try:
            if authority == "authority":
                fixture = (connection, *self.location.seed[0][1:])
                proposal, dispositions = self.location.seed[7]["authority"]
                upstream = hypothesis_helpers._open(fixture)
                try:
                    upstream.retain(
                        proposal,
                        dispositions,
                        proof=self.location.seed[0][3],
                        expected_target_version=subject,
                    )
                finally:
                    upstream.close()
            elif authority == "policy":
                item, current = self.location.seed[7]["policy"]
                successor = replace(
                    hypothesis_helpers.work_item_helpers._version(item, 2),
                    retrieval=current.retrieval,
                )
                TriageWorkItemStore(
                    connection, self.location.seed[0][1]
                ).append_version(
                    current.version_id, current.canonical_digest, successor
                )
            else:
                raise IntegrityViolation("unsupported upstream authority")
        finally:
            connection.close()

    def current_use(self, record_id):
        row = self._subject_row(record_id)
        try:
            self._opened().current(str(row[0]), proof=self.location.seed[0][3])
        except Exception as exc:
            raise IntegrityViolation(record_id) from exc
        return AuthorityValue.from_command(self._decode_command(str(row[0])))

    def tamper(self, record_id, kind):
        row = self._row(record_id)
        connection = sqlite3.connect(self.location.seed[1], isolation_level=None)
        connection.execute(
            "DROP TRIGGER IF EXISTS immutable_event_hypothesis_relationship_update"
        )
        column, value = {
            TamperKind.CANONICAL: ("assessment_bytes", b"{}"),
            TamperKind.SCALAR: ("decision", "REL_SAME_STATE"),
            TamperKind.IDENTITY: ("subject_version_digest", "sha256:" + "0" * 64),
            TamperKind.LINKED_ROW: ("evidence_bytes", b"[]"),
            TamperKind.DIGEST: ("assessment_digest", "sha256:" + "0" * 64),
            TamperKind.PROVENANCE: ("actor_identity_digest", "sha256:" + "0" * 64),
            TamperKind.OFFLINE_REWRITE: ("authority_aggregate_id", str(uuid.uuid4())),
        }[kind]
        if kind is TamperKind.DIGEST:
            connection.execute(
                "UPDATE event_hypothesis_relationship_decisions SET decision_id=?,assessment_digest=? WHERE decision_id=?",
                (value, value, row[0]),
            )
        else:
            connection.execute(
                f"UPDATE event_hypothesis_relationship_decisions SET {column}=? WHERE decision_id=?",
                (value, row[0]),
            )
        connection.close()

    def rollback_scope(self, operation: Callable[[RollbackScope], None]) -> None:
        store = self._opened()._EventHypothesisRelationshipAuthority__store

        class Scope:
            def submit(_, command):
                assessment, evidence = self._domain(command)
                retained = transaction.retain(
                    assessment.canonical_bytes,
                    evidence,
                    proof=_ACTOR_PROOFS[command.actor],
                )
                return AuthorityValue.from_command(
                    self._decode_command(
                        retained.canonical_digest,
                        connection=transaction._store._connection,
                    )
                )

            def observe(_, record_id):
                row = transaction._store._connection.execute(
                    "SELECT decision_id FROM event_hypothesis_relationship_decisions "
                    "WHERE subject_version_id=?",
                    (self.location.subjects[record_id].version_id,),
                ).fetchone()
                if row is None:
                    return None
                try:
                    transaction.load(str(row[0]))
                except RelationshipContractError:
                    return None
                command = self._decode_command(
                    str(row[0]), connection=transaction._store._connection
                )
                if command.record_id != record_id:
                    return None
                return StoredAuthorityState.from_command(command)

            def history(_):
                return tuple(
                    AuthorityValue.from_command(
                        self._decode_command(
                            item.canonical_digest,
                            connection=transaction._store._connection,
                        )
                    )
                    for item in transaction.history()
                )

        def inspect(transaction_scope):
            nonlocal transaction
            transaction = transaction_scope
            operation(Scope())

        transaction = None
        store.rollback_scope(inspect)

    def close(self):
        if self.authority is not None:
            self.authority.close()


class _Adapter:
    name = "relationship-v22-real"
    applicability: ClassVar = {
        case: Applicability.required() for case in CASE_INVENTORY
    }

    def __init__(self, root: Path) -> None:
        self.root = root

    def create_location(self) -> _Location:
        return _Location(_seed_location(self.root / str(uuid.uuid4())))

    def open_handle(self, location: _Location, *, migrate: bool = False) -> _Handle:
        if migrate:
            connection = sqlite3.connect(location.seed[1], isolation_level=None)
            try:
                prepare_pending_migration_backup(connection)
                apply_pending_migrations(
                    connection, applied_at="2042-01-02T00:00:00.000000Z"
                )
            finally:
                connection.close()
        return _Handle(location)


def test_real_store_passes_all_required_conformance_cases(tmp_path) -> None:
    report = run_conformance(_Adapter(tmp_path))
    assert report.passed, repr(report.failures)
    assert tuple(item.case for item in report.outcomes) == CASE_INVENTORY
    assert all(item.status.value == "pass" for item in report.outcomes)


def test_adapter_bindings_are_collision_free_and_persisted_in_distinct_fields(
    tmp_path,
) -> None:
    base = _generic("record-1")
    commands = (
        base,
        replace(base, request="different-request"),
        replace(base, idempotency="different-idempotency"),
        replace(base, cas_predecessor="different-cas_predecessor"),
    )
    persisted = []
    assessment_ids = []
    for index, command in enumerate(commands):
        location = _Location(_seed_location(tmp_path / f"binding-{index}"))
        handle = _Handle(location)
        assessment, _ = handle._domain(command)
        assessment_ids.append(assessment.canonical_digest)
        assert handle.submit(command) == AuthorityValue.from_command(command)
        connection = sqlite3.connect(location.seed[1])
        row = connection.execute(
            "SELECT r.evidence_bytes,a.principal_id FROM "
            "event_hypothesis_relationship_decisions r "
            "JOIN ledger_events e ON e.event_id=r.authority_event_id "
            "JOIN authority_commands c ON c.command_id=e.command_id "
            "JOIN authentication_contexts a ON a.authentication_context_id="
            "c.authentication_context_id"
        ).fetchone()
        connection.close()
        evidence = ComparatorEvidence.from_value(json.loads(bytes(row[0]))[0])
        persisted.append(
            (
                str(row[1]),
                evidence.score,
                evidence.correction_reversal_score,
                evidence.development_score,
            )
        )
        handle.close()
    assert len(set(assessment_ids)) == 4
    assert persisted[0][1] != persisted[1][1]
    assert persisted[0][2] != persisted[2][2]
    assert persisted[0][3] != persisted[3][3]
    collision_location = _Location(_seed_location(tmp_path / "collision"))
    collision_handle = _Handle(collision_location)
    assert collision_handle.submit(base) == AuthorityValue.from_command(base)
    with pytest.raises(BindingConflict):
        collision_handle.submit(replace(base, actor="different-actor"))
    with pytest.raises(BindingConflict):
        collision_handle.submit(replace(base, request="different-request"))
    with pytest.raises(BindingConflict):
        collision_handle.submit(replace(base, request="unsupported-request"))
    assert collision_handle.read(base.record_id) == AuthorityValue.from_command(base)
    connection = sqlite3.connect(collision_location.seed[1])
    assert connection.execute(
        "SELECT count(*) FROM event_hypothesis_relationship_decisions"
    ).fetchone() == (1,)
    assert connection.execute(
        "SELECT a.principal_id FROM event_hypothesis_relationship_decisions r "
        "JOIN ledger_events e ON e.event_id=r.authority_event_id "
        "JOIN authority_commands c ON c.command_id=e.command_id "
        "JOIN authentication_contexts a ON a.authentication_context_id="
        "c.authentication_context_id"
    ).fetchone() == ("editor",)
    connection.close()
    collision_handle.close()


def test_named_upstreams_advance_distinct_real_authority_heads(tmp_path) -> None:
    snapshots = []
    for authority in ("authority", "policy"):
        location = _Location(_seed_location(tmp_path / authority))
        handle = _Handle(location)
        handle.submit(_generic("record-1"))
        item, _ = location.seed[7]["policy"]

        def heads(location=location, item=item):
            connection = sqlite3.connect(location.seed[1])
            values = (
                connection.execute(
                    "SELECT version_id FROM event_hypothesis_heads_v2 "
                    "WHERE hypothesis_id=?",
                    (location.subjects["record-1"].hypothesis_id,),
                ).fetchone()[0],
                connection.execute(
                    "SELECT current_version_id FROM triage_work_item_heads "
                    "WHERE work_item_id=?",
                    (item.work_item_id,),
                ).fetchone()[0],
            )
            connection.close()
            return values

        before = heads()
        handle.set_upstream_head(authority, "changed")
        after = heads()
        snapshots.append((before, after))
        with pytest.raises(IntegrityViolation):
            handle.current_use("record-1")
        handle.close()
    assert snapshots[0][0][0] != snapshots[0][1][0]
    assert snapshots[0][0][1] == snapshots[0][1][1]
    assert snapshots[1][0][0] == snapshots[1][1][0]
    assert snapshots[1][0][1] != snapshots[1][1][1]


def test_migrate_flag_executes_the_real_v21_to_v22_path(tmp_path, monkeypatch) -> None:
    adapter = _Adapter(tmp_path)
    location = adapter.create_location()
    connection = sqlite3.connect(location.seed[1])
    assert connection.execute("PRAGMA user_version").fetchone() == (21,)
    connection.close()
    sentinel = object()
    monkeypatch.setattr(
        "newsroom.tests.test_increment6d2_relationship_store._Handle",
        lambda _: sentinel,
    )
    assert adapter.open_handle(location, migrate=True) is sentinel
    connection = sqlite3.connect(location.seed[1])
    assert connection.execute("PRAGMA user_version").fetchone() == (22,)
    assert connection.execute(
        "SELECT count(*) FROM event_hypothesis_relationship_decisions"
    ).fetchone() == (0,)
    connection.close()


class _DefectiveAdapter(_Adapter):
    def __init__(self, root: Path, defect: str, case: CaseId) -> None:
        super().__init__(root)
        self.defect = defect
        self.applicability = {
            inventory_case: (
                Applicability.required()
                if inventory_case is case
                else Applicability.waived(
                    reason="focused mutation sensitivity",
                    waiver_reference="issue:364#review-sensitivity",
                )
            )
            for inventory_case in CASE_INVENTORY
        }

    def open_handle(self, location: _Location, *, migrate: bool = False) -> _Handle:
        handle = super().open_handle(location, migrate=migrate)
        if self.defect == "no-store":
            handle.submit = lambda command, **_: AuthorityValue.from_command(command)
        elif self.defect == "shadow":
            shadow = getattr(location, "shadow", None)
            if shadow is None:
                shadow = {}
                location.shadow = shadow

            def shadow_submit(command, **_):
                shadow[command.record_id] = command
                return AuthorityValue.from_command(command)

            handle.submit = shadow_submit
            handle.observe = lambda record_id: (
                StoredAuthorityState.from_command(shadow[record_id])
                if record_id in shadow
                else None
            )
            handle.history = lambda: tuple(
                AuthorityValue.from_command(command) for command in shadow.values()
            )
            handle.list_history = handle.history
            handle.read = lambda record_id: AuthorityValue.from_command(
                shadow[record_id]
            )
        elif self.defect == "bypass":
            handle.read = lambda record_id: AuthorityValue.from_command(
                _generic(record_id)
            )
        return handle


@pytest.mark.parametrize(
    ("defect", "case"),
    (
        ("no-store", CaseId.FRESH_REPLAY),
        ("shadow", CaseId.FRESH_REOPEN),
        ("bypass", CaseId.TAMPER_REJECTION),
    ),
)
def test_conformance_sensitivity_rejects_non_authoritative_adapters(
    tmp_path, defect: str, case: CaseId
) -> None:
    report = run_conformance(_DefectiveAdapter(tmp_path, defect, case))
    assert not report.passed
    assert any(failure.case is case for failure in report.failures)
