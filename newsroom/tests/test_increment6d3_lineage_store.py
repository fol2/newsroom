from __future__ import annotations

import sqlite3

import pytest

from newsroom.authority.auth import StaticAuthorizer
from newsroom.authority.persistence import AuthoritySchemaError
from newsroom.increment6.lineage import (
    EventHypothesisLineageAuthority,
    HypothesisLineageReceipt,
    HypothesisLineageRelationshipProof,
    lineage_command_definition,
    open_event_hypothesis_lineage_authority,
)
from newsroom.increment6.outcomes import CanonicalOutcome
from newsroom.increment6.relationships import (
    open_event_hypothesis_relationship_authority,
    relationship_command_definition,
)
from newsroom.tests import test_increment6d2_relationship_store as d2
from newsroom.tests import test_increment6d3_lineage as d3


def _seed(tmp_path):
    seed = d2._seed_location(tmp_path / "lineage-store")
    relationship_scope = relationship_command_definition().required_scope
    lineage_scope = lineage_command_definition().required_scope
    authorizer = StaticAuthorizer(
        policy_version="lineage-test-v1",
        grants_by_principal={
            "editor": frozenset({relationship_scope, lineage_scope}),
            "other": frozenset({relationship_scope, lineage_scope}),
        },
    )
    args = d2._open_arguments(seed)
    args["authorizer"] = authorizer
    output, left, right = seed[3][:3]
    inputs = tuple(sorted((left, right), key=lambda item: item.version_id))
    assessment, evidence = d3._decision(output, inputs, CanonicalOutcome.REL_SAME_STATE)
    relationship = open_event_hypothesis_relationship_authority(**args)
    try:
        relationship.retain(
            assessment.canonical_bytes,
            tuple(item.canonical_bytes for item in evidence),
            proof=seed[0][3],
        )
    finally:
        relationship.close()
    receipt = HypothesisLineageReceipt.consolidation(
        expected_generation=0,
        inputs=inputs,
        output=output,
        relationship_proofs=(
            HypothesisLineageRelationshipProof.from_assessment(assessment, evidence),
        ),
    )
    return seed, args, receipt


class _OpeningSignal(BaseException):
    pass


@pytest.mark.parametrize("failure", ("port", "service", "verify"))
def test_post_super_open_failure_releases_writer_for_corrected_retry(
    tmp_path, monkeypatch: pytest.MonkeyPatch, failure: str
) -> None:
    from newsroom.authority import _event_hypothesis_lineage_system as private

    _, args, _ = _seed(tmp_path)
    with monkeypatch.context() as scoped:
        if failure == "port":
            scoped.setattr(
                private,
                "_create_event_hypothesis_relationship_read_port",
                lambda *args, **kwargs: (_ for _ in ()).throw(_OpeningSignal()),
            )
        elif failure == "service":
            scoped.setattr(
                private,
                "CommandService",
                lambda *args, **kwargs: (_ for _ in ()).throw(_OpeningSignal()),
            )
        else:
            scoped.setattr(
                private._LineageStore,
                "_verify",
                lambda self: (_ for _ in ()).throw(_OpeningSignal()),
            )
        with pytest.raises(_OpeningSignal):
            open_event_hypothesis_lineage_authority(**args)

    corrected = open_event_hypothesis_lineage_authority(**args)
    corrected.close()


def _rewrite_retained_relationship_evidence(database) -> None:
    connection = sqlite3.connect(database, isolation_level=None)
    trigger_sql = str(
        connection.execute(
            "SELECT sql FROM sqlite_schema WHERE type='trigger' AND name=?",
            ("immutable_event_hypothesis_relationship_update",),
        ).fetchone()[0]
    )
    row = connection.execute(
        "SELECT decision_id,assessment_bytes,evidence_bytes "
        "FROM event_hypothesis_relationship_decisions"
    ).fetchone()
    assessment = d2.RelationshipAssessment.from_canonical_bytes(bytes(row[1]))
    values = d2.json.loads(bytes(row[2]))
    evidence = tuple(d2.ComparatorEvidence.from_value(value) for value in values)
    tampered = replace(evidence[0], score=evidence[0].score + 1)
    rewritten_evidence = (tampered, *evidence[1:])
    rewritten = d2.assess_relationships(
        assessment.subject,
        assessment.comparator_manifest,
        rewritten_evidence,
    )
    connection.execute("DROP TRIGGER immutable_event_hypothesis_relationship_update")
    connection.execute(
        "UPDATE event_hypothesis_relationship_decisions SET "
        "decision_id=?,decision=?,assessment_bytes=?,assessment_digest=?,"
        "evidence_bytes=?,evidence_digest=? WHERE decision_id=?",
        (
            rewritten.canonical_digest,
            rewritten.decision.value,
            rewritten.canonical_bytes,
            rewritten.canonical_digest,
            d2.canonical_json_bytes(
                [item.canonical_value for item in rewritten_evidence]
            ),
            rewritten.evidence_digest,
            str(row[0]),
        ),
    )
    connection.execute(trigger_sql)
    connection.close()


def test_empty_lineage_verifies_retained_relationship_history(tmp_path) -> None:
    (tmp_path / "clean").mkdir()
    seed, args, _ = _seed(tmp_path / "clean")
    authority = open_event_hypothesis_lineage_authority(**args)
    try:
        assert authority.history() == ()
        assert authority.current_heads(proof=seed[0][3]) == ()
    finally:
        authority.close()

    (tmp_path / "pre-open-tamper").mkdir()
    _, tampered_args, _ = _seed(tmp_path / "pre-open-tamper")
    _rewrite_retained_relationship_evidence(tampered_args["database"])
    with pytest.raises(ValueError, match="relationship|lineage"):
        open_event_hypothesis_lineage_authority(**tampered_args)


def test_open_lineage_reads_reverify_retained_relationship_history(tmp_path) -> None:
    seed, args, _ = _seed(tmp_path)
    authority = open_event_hypothesis_lineage_authority(**args)
    try:
        _rewrite_retained_relationship_evidence(args["database"])
        with pytest.raises(ValueError, match="relationship|lineage"):
            authority.history()
        with pytest.raises(ValueError, match="relationship|lineage"):
            authority.current_heads(proof=seed[0][3])
    finally:
        authority.close()


def test_rollback_scope_reverifies_retained_relationship_history(tmp_path) -> None:
    from newsroom.authority._event_hypothesis_lineage_system import (
        _open_unlocked_lineage_authority_for_test,
    )

    _, args, _ = _seed(tmp_path)
    authority = _open_unlocked_lineage_authority_for_test(**args)
    observed: list[tuple[HypothesisLineageReceipt, ...]] = []
    try:
        authority.rollback_scope(
            lambda transaction: observed.append(transaction.history())
        )
        assert observed == [()]

        _rewrite_retained_relationship_evidence(args["database"])
        with pytest.raises(ValueError, match="relationship|lineage"):
            authority.rollback_scope(lambda transaction: transaction.history())
    finally:
        authority.close()


def test_retain_replay_reopen_and_guarded_heads(tmp_path) -> None:
    seed, args, receipt = _seed(tmp_path)
    authority = open_event_hypothesis_lineage_authority(**args)
    assert type(authority) is EventHypothesisLineageAuthority
    try:
        retained = authority.retain(receipt.canonical_bytes, proof=seed[0][3])
        assert retained == receipt
        connection = sqlite3.connect(seed[1])
        aggregate_id, idempotency_key = connection.execute(
            "SELECT l.authority_aggregate_id,c.idempotency_key "
            "FROM event_hypothesis_lineage l JOIN ledger_events e "
            "ON e.event_id=l.authority_event_id JOIN authority_commands c "
            "ON c.command_id=e.command_id WHERE l.lineage_id=?",
            (receipt.lineage_id,),
        ).fetchone()
        connection.close()
        from newsroom.authority._event_hypothesis_lineage_system import (
            _lineage_aggregate_id,
        )

        assert aggregate_id == str(_lineage_aggregate_id(receipt.lineage_id))
        assert idempotency_key == receipt.lineage_id
        assert (
            authority.create_or_replay(receipt.canonical_bytes, proof=seed[0][3])
            == receipt
        )
        assert authority.load(receipt.lineage_id) == receipt
        assert authority.history() == (receipt,)
        heads = authority.current_heads(proof=seed[0][3])
        assert tuple(head.node.version_id for head in heads) == (
            receipt.outputs[0].version_id,
        )
    finally:
        authority.close()

    reopened = open_event_hypothesis_lineage_authority(**args)
    try:
        assert reopened.history() == (receipt,)
    finally:
        reopened.close()

    connection = sqlite3.connect(seed[1], isolation_level=None)
    row = connection.execute("SELECT * FROM event_hypothesis_lineage_heads").fetchone()
    connection.execute("DELETE FROM event_hypothesis_lineage_heads")
    connection.execute(
        "INSERT INTO event_hypothesis_lineage_heads VALUES(?,?,?,?,?,?)",
        (row[0], row[1], "sha256:" + "f" * 64, row[3], row[4], row[5]),
    )
    connection.close()
    with pytest.raises((AuthoritySchemaError, ValueError), match="heads|lineage"):
        open_event_hypothesis_lineage_authority(**args)


def test_trigger_preserving_fk_clean_aggregate_rewrite_fails_closed(
    tmp_path,
) -> None:
    from newsroom.authority._event_hypothesis_lineage_system import (
        _lineage_aggregate_id,
    )

    seed, args, receipt = _seed(tmp_path)
    authority = open_event_hypothesis_lineage_authority(**args)
    authority.retain(receipt.canonical_bytes, proof=seed[0][3])
    authority.close()

    connection = sqlite3.connect(seed[1], isolation_level=None)
    connection.row_factory = sqlite3.Row
    expected = str(_lineage_aggregate_id(receipt.lineage_id))
    rewritten = str(uuid.uuid4())
    lineage = connection.execute(
        "SELECT * FROM event_hypothesis_lineage WHERE lineage_id=?",
        (receipt.lineage_id,),
    ).fetchone()
    event = connection.execute(
        "SELECT * FROM ledger_events WHERE event_id=?",
        (lineage["authority_event_id"],),
    ).fetchone()
    command = connection.execute(
        "SELECT * FROM authority_commands WHERE command_id=?",
        (event["command_id"],),
    ).fetchone()
    version = connection.execute(
        "SELECT * FROM authority_aggregate_versions WHERE command_id=?",
        (event["command_id"],),
    ).fetchone()
    aggregate = connection.execute(
        "SELECT * FROM authority_aggregates WHERE aggregate_type=? AND aggregate_id=?",
        (event["aggregate_type"], expected),
    ).fetchone()
    triggers = connection.execute(
        "SELECT name,sql FROM sqlite_schema WHERE type='trigger' ORDER BY name"
    ).fetchall()

    def rewritten_row(row: sqlite3.Row, **changes: object) -> tuple[object, ...]:
        return tuple(
            changes.get(key, row[key])
            for key in row.keys()  # noqa: SIM118
        )

    connection.execute("PRAGMA foreign_keys=ON")
    connection.execute("BEGIN IMMEDIATE")
    connection.execute("PRAGMA defer_foreign_keys=ON")
    connection.execute(
        "CREATE UNIQUE INDEX aggregate_rewrite_gate "
        "ON authority_aggregates(aggregate_type) "
        "WHERE aggregate_type='event_hypothesis_lineage'"
    )
    connection.execute(
        "INSERT OR REPLACE INTO authority_aggregates VALUES(?,?,?,?,?)",
        rewritten_row(aggregate, aggregate_id=rewritten),
    )
    connection.execute(
        "INSERT OR REPLACE INTO authority_aggregate_versions VALUES(?,?,?,?,?,?,?)",
        rewritten_row(version, aggregate_id=rewritten),
    )
    connection.execute(
        "INSERT OR REPLACE INTO ledger_events VALUES("
        + ",".join("?" for _ in event.keys())  # noqa: SIM118
        + ")",
        rewritten_row(event, aggregate_id=rewritten),
    )
    connection.execute(
        "INSERT OR REPLACE INTO event_hypothesis_lineage VALUES(?,?,?,?,?,?,?,?,?,?,?)",
        rewritten_row(lineage, authority_aggregate_id=rewritten),
    )
    connection.execute("DROP INDEX aggregate_rewrite_gate")
    connection.execute("COMMIT")

    assert connection.execute("PRAGMA foreign_key_check").fetchall() == []
    assert (
        connection.execute(
            "SELECT name,sql FROM sqlite_schema WHERE type='trigger' ORDER BY name"
        ).fetchall()
        == triggers
    )
    assert command["aggregate_id"] == expected
    assert expected.encode() in bytes(command["result_bytes"])
    request = connection.execute(
        "SELECT canonical_bytes FROM authorization_requests WHERE request_digest=?",
        (command["authorization_request_digest"],),
    ).fetchone()
    assert expected.encode() in bytes(request[0])
    connection.close()

    with pytest.raises((AuthoritySchemaError, ValueError), match="aggregate|lineage"):
        open_event_hypothesis_lineage_authority(**args)


def test_private_rollback_scope_exposes_real_uncommitted_v23_rows(tmp_path) -> None:
    from newsroom.authority._event_hypothesis_lineage_system import (
        _open_unlocked_lineage_authority_for_test,
    )

    seed, args, receipt = _seed(tmp_path)
    authority = _open_unlocked_lineage_authority_for_test(**args)
    observed: list[tuple[HypothesisLineageReceipt, ...]] = []
    try:

        def inspect(transaction: object) -> None:
            transaction.retain(receipt.canonical_bytes, proof=seed[0][3])  # type: ignore[attr-defined]
            observed.append(transaction.history())  # type: ignore[attr-defined]

        authority.rollback_scope(inspect)
        assert observed == [(receipt,)]
        assert authority.history() == ()
    finally:
        authority.close()


def test_v22_to_v23_preserves_retained_relationship_before_lineage_use(
    tmp_path,
) -> None:
    from newsroom.authority.event_hypothesis_lineage_migrations import (
        event_hypothesis_lineage_backup_paths,
    )
    from newsroom.authority.migrations import (
        apply_pending_migrations,
        prepare_pending_migration_backup,
    )
    from newsroom.tests.graphiti_adapter_4d_migration_helpers import (
        drop_empty_v23_lineage_schema,
    )

    seed, args, receipt = _seed(tmp_path)
    connection = sqlite3.connect(seed[1], isolation_level=None)
    before = (
        connection.execute(
            "SELECT * FROM event_hypothesis_relationship_decisions ORDER BY decision_id"
        ).fetchall(),
        connection.execute("SELECT * FROM ledger_events ORDER BY event_id").fetchall(),
    )
    drop_empty_v23_lineage_schema(connection)
    assert connection.execute("PRAGMA user_version").fetchone() == (22,)
    for path in event_hypothesis_lineage_backup_paths(seed[1]):
        path.unlink(missing_ok=True)
    assert prepare_pending_migration_backup(connection) is not None
    apply_pending_migrations(connection, applied_at="2042-01-03T00:00:00.000000Z")
    assert connection.execute("PRAGMA user_version").fetchone() == (23,)
    assert (
        connection.execute(
            "SELECT * FROM event_hypothesis_relationship_decisions ORDER BY decision_id"
        ).fetchall(),
        connection.execute("SELECT * FROM ledger_events ORDER BY event_id").fetchall(),
    ) == before
    connection.close()
    authority = open_event_hypothesis_lineage_authority(**args)
    try:
        assert authority.retain(receipt.canonical_bytes, proof=seed[0][3]) == receipt
    finally:
        authority.close()


def test_disjoint_lineages_preserve_each_head_producer_time(tmp_path) -> None:
    seed, args, first = _seed(tmp_path)
    output, left, right = seed[3][3:6]
    inputs = tuple(sorted((left, right), key=lambda item: item.version_id))
    assessment, evidence = d3._decision(output, inputs, CanonicalOutcome.REL_SAME_STATE)
    relationship = open_event_hypothesis_relationship_authority(**args)
    try:
        relationship.retain(
            assessment.canonical_bytes,
            tuple(item.canonical_bytes for item in evidence),
            proof=seed[0][3],
        )
    finally:
        relationship.close()
    second = HypothesisLineageReceipt.consolidation(
        expected_generation=0,
        inputs=inputs,
        output=output,
        relationship_proofs=(
            HypothesisLineageRelationshipProof.from_assessment(assessment, evidence),
        ),
    )
    authority = open_event_hypothesis_lineage_authority(**args)
    try:
        authority.retain(first.canonical_bytes, proof=seed[0][3])
    finally:
        authority.close()
    args["clock"] = lambda: d2.UtcTimestamp.parse("2042-01-03T00:00:00.000000Z")
    authority = open_event_hypothesis_lineage_authority(**args)
    try:
        authority.retain(second.canonical_bytes, proof=seed[0][3])
        assert {
            head.node.version_id for head in authority.current_heads(proof=seed[0][3])
        } == {
            first.outputs[0].version_id,
            second.outputs[0].version_id,
        }
    finally:
        authority.close()


def test_semantic_replay_rejects_divergent_output_and_actor(tmp_path) -> None:
    seed, args, receipt = _seed(tmp_path)
    divergent_output = seed[3][3]
    inputs = tuple(sorted(seed[3][1:3], key=lambda item: item.version_id))
    assessment, evidence = d3._decision(
        divergent_output,
        inputs,
        CanonicalOutcome.REL_SAME_STATE,
    )
    relationship = open_event_hypothesis_relationship_authority(**args)
    try:
        relationship.retain(
            assessment.canonical_bytes,
            tuple(item.canonical_bytes for item in evidence),
            proof=seed[0][3],
        )
    finally:
        relationship.close()
    divergent = HypothesisLineageReceipt.consolidation(
        expected_generation=0,
        inputs=inputs,
        output=divergent_output,
        relationship_proofs=(
            HypothesisLineageRelationshipProof.from_assessment(assessment, evidence),
        ),
    )
    assert divergent.lineage_id == receipt.lineage_id
    authority = open_event_hypothesis_lineage_authority(**args)
    try:
        authority.retain(receipt.canonical_bytes, proof=seed[0][3])
        with pytest.raises(ValueError, match="diverge|retention"):
            authority.retain(divergent.canonical_bytes, proof=seed[0][3])
        with pytest.raises(ValueError, match="diverge|retention"):
            authority.retain(
                receipt.canonical_bytes,
                proof=d2.AuthenticationProof(method="STATIC_TOKEN", credential="other"),
            )
        assert authority.history() == (receipt,)
    finally:
        authority.close()


@pytest.mark.parametrize("field", ("generation", "timestamp"))
def test_head_scalar_and_timestamp_tamper_fail_closed(tmp_path, field: str) -> None:
    root = tmp_path / field
    root.mkdir()
    seed, args, receipt = _seed(root)
    authority = open_event_hypothesis_lineage_authority(**args)
    authority.retain(receipt.canonical_bytes, proof=seed[0][3])
    authority.close()
    connection = sqlite3.connect(seed[1], isolation_level=None)
    row = connection.execute("SELECT * FROM event_hypothesis_lineage_heads").fetchone()
    connection.execute("DELETE FROM event_hypothesis_lineage_heads")
    values = list(row)
    values[3 if field == "generation" else 5] = (
        int(row[3]) + 1 if field == "generation" else "2042-01-09T00:00:00.000000Z"
    )
    connection.execute(
        "INSERT INTO event_hypothesis_lineage_heads VALUES(?,?,?,?,?,?)", values
    )
    connection.close()
    with pytest.raises((AuthoritySchemaError, ValueError), match="heads|lineage"):
        open_event_hypothesis_lineage_authority(**args)


def test_historical_reads_and_exact_replay_ignore_advanced_input_currentness(
    tmp_path,
) -> None:
    seed, args, receipt = _seed(tmp_path)
    authority = open_event_hypothesis_lineage_authority(**args)
    authority.retain(receipt.canonical_bytes, proof=seed[0][3])
    authority.close()
    connection = sqlite3.connect(seed[1], isolation_level=None)
    fixture = (connection, *seed[0][1:])
    proposal, dispositions = seed[7]["authority"]
    upstream = d2.hypothesis_helpers._open(fixture)
    try:
        upstream.retain(
            proposal,
            dispositions,
            proof=seed[0][3],
            expected_target_version=seed[3][0],
        )
    finally:
        upstream.close()
        connection.close()
    reopened = open_event_hypothesis_lineage_authority(**args)
    try:
        assert reopened.load(receipt.lineage_id) == receipt
        assert reopened.history() == (receipt,)
        assert reopened.retain(receipt.canonical_bytes, proof=seed[0][3]) == receipt
        with pytest.raises(ValueError, match="current heads failed"):
            reopened.current_heads(proof=seed[0][3])
    finally:
        reopened.close()


def test_reversal_target_retarget_fails_closed(tmp_path) -> None:
    from newsroom.increment6.lineage import merge_lineage_authority_registries
    from newsroom.increment6.relationships import (
        merge_relationship_authority_registries,
    )

    seed, args, _ = _seed(tmp_path)
    source = seed[3][0]
    outputs = (seed[3][1], seed[3][2])
    split_proofs = []
    relationship = open_event_hypothesis_relationship_authority(**args)
    try:
        for output in outputs:
            comparators = tuple(
                sorted(
                    (source, *(item for item in outputs if item != output)),
                    key=lambda item: item.version_id,
                )
            )
            assessment, evidence = d3._decision(
                output, comparators, CanonicalOutcome.REL_RELATED_DISTINCT
            )
            relationship.retain(
                assessment.canonical_bytes,
                tuple(item.canonical_bytes for item in evidence),
                proof=seed[0][3],
            )
            split_proofs.append(
                HypothesisLineageRelationshipProof.from_assessment(assessment, evidence)
            )
    finally:
        relationship.close()
    split = HypothesisLineageReceipt.split(
        expected_generation=0,
        source=source,
        outputs=outputs,
        relationship_proofs=tuple(split_proofs),
    )
    authority = open_event_hypothesis_lineage_authority(**args)
    authority.retain(split.canonical_bytes, proof=seed[0][3])
    authority.close()

    connection = sqlite3.connect(seed[1], isolation_level=None)
    upstream = d2.hypothesis_helpers._open((connection, *seed[0][1:]))
    proposal, dispositions = seed[7]["authority"]
    try:
        restored = upstream.retain(
            proposal,
            dispositions,
            proof=seed[0][3],
            expected_target_version=source,
        )
    finally:
        upstream.close()
        connection.close()

    commands, schemas = merge_relationship_authority_registries(
        args["command_registry"], args["payload_schemas"]
    )
    commands, schemas = merge_lineage_authority_registries(commands, schemas)
    checked_args = {**args, "command_registry": commands, "payload_schemas": schemas}
    comparators = tuple(sorted(outputs, key=lambda item: item.version_id))
    assessment, evidence = d3._decision(
        restored, comparators, CanonicalOutcome.REL_CORRECTION_REVERSAL_OF
    )
    relationship = open_event_hypothesis_relationship_authority(**checked_args)
    try:
        relationship.retain(
            assessment.canonical_bytes,
            tuple(item.canonical_bytes for item in evidence),
            proof=seed[0][3],
        )
    finally:
        relationship.close()
    reversal = HypothesisLineageReceipt.reversal(
        expected_generation=1,
        target=split,
        outputs=(restored,),
        relationship_proofs=(
            HypothesisLineageRelationshipProof.from_assessment(assessment, evidence),
        ),
    )
    authority = open_event_hypothesis_lineage_authority(**checked_args)
    authority.retain(reversal.canonical_bytes, proof=seed[0][3])
    authority.close()

    connection = sqlite3.connect(seed[1], isolation_level=None)
    connection.execute("PRAGMA foreign_keys=OFF")
    connection.execute("DROP TRIGGER immutable_event_hypothesis_lineage_update")
    connection.execute(
        "UPDATE event_hypothesis_lineage SET reversal_target_lineage_id=? "
        "WHERE lineage_id=?",
        (str(uuid.uuid4()), reversal.lineage_id),
    )
    connection.close()
    with pytest.raises((AuthoritySchemaError, ValueError), match="lineage"):
        open_event_hypothesis_lineage_authority(**checked_args)


def test_public_facade_normalises_forged_results_and_ordinary_exceptions(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    from newsroom.increment6 import lineage

    class Raw:
        retained: object = object()

        def retain(self, *_: object, **__: object) -> object:
            return self.retained

        def load(self, *_: object, **__: object) -> object:
            raise RuntimeError("ordinary")

        def current_heads(self, *_: object, **__: object) -> object:
            return (object.__new__(lineage.HypothesisLineageHead),)

    raw = Raw()
    facade = lineage._compose_event_hypothesis_lineage_authority(raw)
    with pytest.raises(lineage.HypothesisLineageContractError):
        facade.retain(b"{}", proof=object())
    raw.retained = object.__new__(lineage.HypothesisLineageReceipt)
    with pytest.raises(lineage.HypothesisLineageContractError):
        facade.retain(b"{}", proof=object())
    with pytest.raises(ValueError, match="load failed"):
        facade.load("lineage")
    with pytest.raises(lineage.HypothesisLineageContractError):
        facade.current_heads(proof=object())

    from newsroom.authority import event_hypothesis_lineage_system as system

    monkeypatch.setattr(
        system,
        "open_event_hypothesis_lineage_authority_system",
        lambda *a, **k: object(),
    )
    with pytest.raises(ValueError, match="forged facade"):
        lineage.open_event_hypothesis_lineage_authority(
            "fixture.sqlite3",
            retrieval_authority=object(),
            authenticator=object(),
            authorizer=object(),
            command_registry=object(),  # type: ignore[arg-type]
            payload_schemas=object(),  # type: ignore[arg-type]
        )


def test_second_public_writer_fails_closed_until_first_closes(tmp_path) -> None:
    _, args, _ = _seed(tmp_path)
    first = open_event_hypothesis_lineage_authority(**args)
    try:
        with pytest.raises(ValueError, match="open failed"):
            open_event_hypothesis_lineage_authority(**args)
    finally:
        first.close()
    reopened = open_event_hypothesis_lineage_authority(**args)
    reopened.close()


# #384 adapter: command-field encodings live in retained D2 evidence and every
# observable record/history value is reconstructed through a real v23 receipt.
import json
import uuid
from dataclasses import replace
from pathlib import Path
from typing import ClassVar

from newsroom.increment6.relationships import (
    ComparatorEvidence,
    ComparatorSetManifest,
    HypothesisVersionBinding,
    assess_relationships,
)
from newsroom.tests.authority_store_conformance import (
    _SCENARIOS,
    CASE_INVENTORY,
    Applicability,
    AuthorityValue,
    BindingConflict,
    CaseId,
    IntegrityViolation,
    LostResponse,
    StoredAuthorityState,
    TamperKind,
    WriteCommand,
)

_CONFORMANCE_TEMPLATES: dict[tuple[str, ...], tuple[bytes, tuple]] = {}


class _ConformanceLocation:
    def __init__(self, seed, records: tuple[str, ...]) -> None:
        self.seed = seed
        self.records = records
        self.outputs = dict(zip(records, seed[3][: len(records)], strict=True))
        root_count = 4 if "record-2" in records else 2
        roots = seed[3][len(records) : len(records) + root_count]
        assert len(self.outputs) == len(records) and len(roots) == root_count
        self.roots = {
            record_id: tuple(
                sorted(
                    roots[:2],
                    key=lambda item: item.version_id,
                )
            )
            for record_id in records
        }
        if "record-2" in records:
            self.roots["record-2"] = tuple(
                sorted(roots[2:4], key=lambda item: item.version_id)
            )


def _seed_conformance_relationships(location: _ConformanceLocation) -> None:
    args = d2._open_arguments(location.seed)
    args["authorizer"] = _seed_authorizer()
    relationship = d2._open_unlocked_relationship_authority_for_test(**args)
    try:
        for record_id in location.records:
            command = d2._generic(record_id)
            assessment, evidence, _ = _conformance_domain(location, command)
            relationship.retain(
                assessment.canonical_bytes,
                tuple(item.canonical_bytes for item in evidence),
                proof=d2._ACTOR_PROOFS[command.actor],
            )
    finally:
        relationship.close()


def _conformance_domain(location: _ConformanceLocation, command: WriteCommand):
    value = command.scalar_columns.get("value")
    record_code = d2._code(d2._RECORD_VALUES, (command.record_id, value), "record")
    base = d2._generic(command.record_id, command.cas_predecessor, value)
    if (
        command.canonical_bytes,
        command.scalar_columns,
        command.identity_columns,
        command.linked_rows,
    ) != (
        base.canonical_bytes,
        base.scalar_columns,
        base.identity_columns,
        base.linked_rows,
    ):
        raise ValueError("unsupported conformance representation")
    request_code = d2._code(d2._REQUEST_VALUES, command.request, "request")
    idempotency_code = d2._code(
        d2._IDEMPOTENCY_VALUES, command.idempotency, "idempotency"
    )
    cas_code = d2._code(d2._CAS_VALUES, command.cas_predecessor, "CAS predecessor")
    upstream_code = d2._code(
        d2._UPSTREAM_VALUES, command.required_upstream_heads, "upstream"
    )
    subject = HypothesisVersionBinding.from_version(location.outputs[command.record_id])
    comparators = tuple(
        HypothesisVersionBinding.from_version(item)
        for item in location.roots[command.record_id]
    )
    evidence = (
        ComparatorEvidence(
            subject,
            comparators[0],
            60 + request_code,
            idempotency_code,
            cas_code,
            80 + record_code,
            upstream_code,
        ),
        ComparatorEvidence(subject, comparators[1], 60, 0, 0, 80, 0),
    )
    assessment = assess_relationships(
        subject, ComparatorSetManifest.complete(comparators), evidence
    )
    proof = HypothesisLineageRelationshipProof.from_assessment(assessment, evidence)
    receipt = HypothesisLineageReceipt.consolidation(
        expected_generation=0,
        inputs=location.roots[command.record_id],
        output=location.outputs[command.record_id],
        relationship_proofs=(proof,),
    )
    return assessment, evidence, receipt


class _ConformanceHandle:
    def __init__(self, location: _ConformanceLocation) -> None:
        from newsroom.authority._event_hypothesis_lineage_system import (
            _open_unlocked_lineage_authority_for_test,
        )

        self.location = location
        self.args = d2._open_arguments(location.seed)
        self.args["authorizer"] = _seed_authorizer()
        try:
            self.authority = _open_unlocked_lineage_authority_for_test(**self.args)
        except (LookupError, RuntimeError, ValueError, sqlite3.DatabaseError) as exc:
            failure = exc

            class FailedAuthority:
                def __getattr__(_, name: str):
                    if name == "close":
                        return lambda: None

                    def failed(*args: object, **kwargs: object) -> object:
                        raise IntegrityViolation("lineage open failed") from failure

                    return failed

            self.authority = FailedAuthority()

    def _row(self, record_id: str, connection=None):
        owned = connection is None
        connection = connection or sqlite3.connect(self.location.seed[1])
        try:
            return connection.execute(
                "SELECT lineage_id FROM event_hypothesis_lineage WHERE lineage_id=?",
                (
                    _conformance_domain(self.location, d2._generic(record_id))[
                        2
                    ].lineage_id,
                ),
            ).fetchone()
        finally:
            if owned:
                connection.close()

    def _decode(self, lineage_id: str, connection=None) -> WriteCommand:
        owned = connection is None
        connection = connection or sqlite3.connect(self.location.seed[1])
        try:
            row = connection.execute(
                "SELECT l.receipt_bytes,a.principal_id FROM event_hypothesis_lineage l JOIN ledger_events e ON e.event_id=l.authority_event_id JOIN authority_commands c ON c.command_id=e.command_id JOIN authentication_contexts a ON a.authentication_context_id=c.authentication_context_id WHERE l.lineage_id=?",
                (lineage_id,),
            ).fetchone()
            if row is None:
                raise ValueError("unknown lineage")
            receipt = HypothesisLineageReceipt.from_canonical_bytes(bytes(row[0]))
            binding = receipt.relationships[0]
            evidence_row = connection.execute(
                "SELECT evidence_bytes FROM event_hypothesis_relationship_decisions WHERE decision_id=?",
                (binding.assessment_digest,),
            ).fetchone()
            values = json.loads(bytes(evidence_row[0]))
            evidence = ComparatorEvidence.from_value(values[0])
            record_code = evidence.same_state_score - 80
            record_id, value = d2._RECORD_VALUES[record_code]
            command = replace(
                d2._generic(
                    record_id, d2._CAS_VALUES[evidence.development_score], value
                ),
                actor=d2._PRINCIPAL_ACTORS[str(row[1])],
                request=d2._REQUEST_VALUES[evidence.score - 60],
                idempotency=d2._IDEMPOTENCY_VALUES[evidence.correction_reversal_score],
                required_upstream_heads=d2._UPSTREAM_VALUES[
                    evidence.related_distinct_score
                ],
            )
            if (
                receipt.outputs[0].version_id
                != self.location.outputs[record_id].version_id
            ):
                raise ValueError("lineage output differs")
            return command
        finally:
            if owned:
                connection.close()

    def submit(
        self, command: WriteCommand, *, lose_response: bool = False
    ) -> AuthorityValue:
        try:
            _, _, receipt = _conformance_domain(self.location, command)
            proof = d2._ACTOR_PROOFS[command.actor]
            retained = self.authority.retain(receipt.canonical_bytes, proof=proof)
            value = AuthorityValue.from_command(self._decode(retained.lineage_id))
        except Exception as exc:
            row = self._row(command.record_id)
            if row is not None:
                try:
                    self.authority.load(str(row[0]))
                except Exception as integrity:
                    raise IntegrityViolation(command.record_id) from integrity
                raise BindingConflict(command.record_id) from exc
            raise BindingConflict(command.record_id) from exc
        if lose_response:
            raise LostResponse(command.record_id)
        return value

    def observe(self, record_id: str):
        row = self._row(record_id)
        if row is None:
            return None
        try:
            self.authority.load(str(row[0]))
            command = self._decode(str(row[0]))
        except Exception as exc:
            raise IntegrityViolation(record_id) from exc
        return (
            StoredAuthorityState.from_command(command)
            if command.record_id == record_id
            else None
        )

    def history(self):
        try:
            receipts = self.authority.history()
        except Exception as exc:
            raise IntegrityViolation("history") from exc
        return tuple(
            AuthorityValue.from_command(self._decode(item.lineage_id))
            for item in receipts
        )

    def read(self, record_id: str):
        state = self.observe(record_id)
        if state is None:
            raise KeyError(record_id)
        return AuthorityValue.from_command(self._decode(str(self._row(record_id)[0])))

    list_history = history

    def set_upstream_head(self, authority: str, value: str) -> None:
        if value.endswith("head-1") or self._row("record-1") is None:
            return
        subject = self.location.outputs["record-1"]
        connection = sqlite3.connect(self.location.seed[1], isolation_level=None)
        try:
            if authority == "authority":
                fixture = (connection, *self.location.seed[0][1:])
                proposal, dispositions = self.location.seed[7]["authority"]
                upstream = d2.hypothesis_helpers._open(fixture)
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
                    d2.hypothesis_helpers.work_item_helpers._version(item, 2),
                    retrieval=current.retrieval,
                )
                d2.TriageWorkItemStore(
                    connection, self.location.seed[0][1]
                ).append_version(
                    current.version_id, current.canonical_digest, successor
                )
        finally:
            connection.close()

    def current_use(self, record_id: str):
        try:
            self.authority.current_heads(proof=self.location.seed[0][3])
        except Exception as exc:
            raise IntegrityViolation(record_id) from exc
        return self.read(record_id)

    def tamper(self, record_id: str, kind: TamperKind) -> None:
        lineage_id = str(self._row(record_id)[0])
        connection = sqlite3.connect(self.location.seed[1], isolation_level=None)
        connection.execute(
            "DROP TRIGGER IF EXISTS immutable_event_hypothesis_lineage_update"
        )
        if kind is TamperKind.CANONICAL:
            connection.execute(
                "UPDATE event_hypothesis_lineage SET receipt_bytes=? WHERE lineage_id=?",
                (b"{}", lineage_id),
            )
        elif kind is TamperKind.SCALAR:
            connection.execute(
                "UPDATE event_hypothesis_lineage SET expected_generation=expected_generation+1 WHERE lineage_id=?",
                (lineage_id,),
            )
        elif kind is TamperKind.IDENTITY:
            connection.execute(
                "UPDATE event_hypothesis_lineage SET kind='HYPOTHESIS_SPLIT' WHERE lineage_id=?",
                (lineage_id,),
            )
        elif kind is TamperKind.LINKED_ROW:
            connection.execute("DELETE FROM event_hypothesis_lineage_heads")
        elif kind is TamperKind.DIGEST:
            connection.execute(
                "UPDATE event_hypothesis_lineage SET receipt_digest=? WHERE lineage_id=?",
                ("sha256:" + "0" * 64, lineage_id),
            )
        elif kind is TamperKind.PROVENANCE:
            connection.execute(
                "UPDATE event_hypothesis_lineage SET actor_identity_digest=? WHERE lineage_id=?",
                ("sha256:" + "0" * 64, lineage_id),
            )
        elif kind is TamperKind.OFFLINE_REWRITE:
            _, _, divergent = _conformance_domain(
                self.location, d2._generic("record-b")
            )
            assert divergent.lineage_id == lineage_id
            assert divergent.canonical_digest != str(
                connection.execute(
                    "SELECT receipt_digest FROM event_hypothesis_lineage "
                    "WHERE lineage_id=?",
                    (lineage_id,),
                ).fetchone()[0]
            )
            updated_at = str(
                connection.execute(
                    "SELECT updated_at FROM event_hypothesis_lineage_heads"
                ).fetchone()[0]
            )
            connection.execute(
                "UPDATE event_hypothesis_lineage SET kind=?,expected_generation=?,"
                "receipt_bytes=?,receipt_digest=?,reversal_target_lineage_id=?,"
                "reversal_target_lineage_digest=? WHERE lineage_id=?",
                (
                    divergent.kind.value,
                    divergent.expected_generation,
                    divergent.canonical_bytes,
                    divergent.canonical_digest,
                    None,
                    None,
                    lineage_id,
                ),
            )
            connection.execute("DELETE FROM event_hypothesis_lineage_heads")
            output = divergent.outputs[0]
            connection.execute(
                "INSERT INTO event_hypothesis_lineage_heads VALUES(?,?,?,?,?,?)",
                (
                    output.hypothesis_id,
                    output.version_id,
                    output.version_digest,
                    divergent.expected_generation + 1,
                    lineage_id,
                    updated_at,
                ),
            )
            ledger_payload = bytes(
                connection.execute(
                    "SELECT p.payload_bytes FROM event_hypothesis_lineage l "
                    "JOIN ledger_events e ON e.event_id=l.authority_event_id "
                    "JOIN authority_payloads p ON p.payload_id=e.payload_id "
                    "WHERE l.lineage_id=?",
                    (lineage_id,),
                ).fetchone()[0]
            )
            assert ledger_payload != divergent.canonical_bytes
        else:  # pragma: no cover - conformance enum exhaustiveness guard
            raise AssertionError(kind)
        connection.close()

    def rollback_scope(self, operation) -> None:
        outer = self

        class Scope:
            def submit(_, command):
                _, _, receipt = _conformance_domain(outer.location, command)
                proof = d2._ACTOR_PROOFS[command.actor]
                retained = transaction.retain(receipt.canonical_bytes, proof=proof)
                return AuthorityValue.from_command(
                    outer._decode(retained.lineage_id, transaction._store._connection)
                )

            def observe(_, record_id):
                row = outer._row(record_id, transaction._store._connection)
                return (
                    None
                    if row is None
                    else StoredAuthorityState.from_command(
                        outer._decode(str(row[0]), transaction._store._connection)
                    )
                )

            def history(_):
                return tuple(
                    AuthorityValue.from_command(
                        outer._decode(item.lineage_id, transaction._store._connection)
                    )
                    for item in transaction.history()
                )

        def inspect(scope):
            nonlocal transaction
            transaction = scope
            operation(Scope())

        transaction = None
        self.authority.rollback_scope(inspect)

    def close(self) -> None:
        self.authority.close()


def _seed_authorizer():
    relationship_scope = relationship_command_definition().required_scope
    lineage_scope = lineage_command_definition().required_scope
    return StaticAuthorizer(
        policy_version="lineage-conformance-v1",
        grants_by_principal={
            "editor": frozenset({relationship_scope, lineage_scope}),
            "other": frozenset({relationship_scope, lineage_scope}),
        },
    )


class _LineageAdapter:
    name = "lineage-v23-real"
    applicability: ClassVar = {
        case: Applicability.required() for case in CASE_INVENTORY
    }

    def __init__(self, root: Path, case: CaseId) -> None:
        self.root = root
        self.records = {
            CaseId.HISTORICAL_READ: ("record-1", "record-2"),
            CaseId.COMPETING_WRITERS: ("record-a", "record-b"),
            CaseId.TRANSACTION_ROLLBACK: (
                "record-rollback-normal",
                "record-rollback-abort",
            ),
            CaseId.TAMPER_REJECTION: ("record-1", "record-b"),
        }.get(case, ("record-1",))

    def create_location(self):
        template = _CONFORMANCE_TEMPLATES.get(self.records)
        if template is None:
            d2._SEED_CACHE = None
            subjects = len(self.records) + (4 if "record-2" in self.records else 2)
            location = _ConformanceLocation(
                d2._seed_location(self.root / str(uuid.uuid4()), subjects=subjects),
                self.records,
            )
            _seed_conformance_relationships(location)
            connection = sqlite3.connect(location.seed[1], isolation_level=None)
            assert connection.execute(
                "SELECT COUNT(*) FROM event_hypothesis_relationship_decisions"
            ).fetchone() == (len(self.records),)
            assert connection.execute(
                "SELECT COUNT(*) FROM event_hypothesis_lineage"
            ).fetchone() == (0,)
            connection.execute("PRAGMA wal_checkpoint(TRUNCATE)")
            connection.close()
            template = (location.seed[1].read_bytes(), location.seed)
            _CONFORMANCE_TEMPLATES[self.records] = template
        else:
            root = self.root / str(uuid.uuid4())
            root.mkdir(mode=0o700)
            database = root / "relationship-authority.sqlite3"
            database.write_bytes(template[0])
            database.chmod(0o600)
            template_seed = template[1]
            location = _ConformanceLocation(
                (template_seed[0], database, *template_seed[2:]), self.records
            )
        return location

    def open_handle(self, location, *, migrate: bool = False):
        if migrate:
            from newsroom.authority.migrations import (
                apply_pending_migrations,
                prepare_pending_migration_backup,
            )

            connection = sqlite3.connect(location.seed[1], isolation_level=None)
            try:
                assert prepare_pending_migration_backup(connection) is None
                apply_pending_migrations(
                    connection, applied_at="2042-01-03T00:00:00.000000Z"
                )
                assert connection.execute("PRAGMA user_version").fetchone() == (23,)
                assert connection.execute(
                    "SELECT MAX(version) FROM authority_migrations"
                ).fetchone() == (23,)
            finally:
                connection.close()
        return _ConformanceHandle(location)


@pytest.mark.parametrize("case", CASE_INVENTORY, ids=lambda case: case.value)
def test_real_v23_store_passes_required_conformance_case(tmp_path, case) -> None:
    adapter = _LineageAdapter(tmp_path, case)
    assert adapter.applicability[case] == Applicability.required()
    _SCENARIOS[case](adapter)
