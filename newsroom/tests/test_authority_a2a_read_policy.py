from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.authority import (
    MetadataClass,
    ReadPolicyDenied,
    SUCCESSFUL_READ_AUDIT_STATUS,
    TrustScope,
    projector_service_read_policy,
)

from .authority_event_helpers import (
    fixture_read_policy,
    open_test_system,
)
from .authority_helpers import command, proof


def test_server_policy_filters_security_and_trust_without_caller_filters(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    policy = fixture_read_policy(
        allowed_security_scopes=frozenset(
            {"authority.internal"}
        ),
        allowed_trust_scopes=frozenset(
            {TrustScope.OBSERVED}
        ),
    )
    with open_test_system(
        database, read_policy=policy
    ) as system:
        observed = system.commands.execute(
            command(key="observed"), proof=proof()
        )
        admitted = system.commands.execute(
            command(
                command_type="record.admitted",
                key="admitted",
            ),
            proof=proof(),
        )

        visible = system.events.after(0, proof=proof())
        assert [event.command_id for event in visible] == [
            observed.command_id
        ]
        with pytest.raises(KeyError):
            system.events.provenance(
                admitted.event_id, proof=proof()
            )


def test_policy_bounds_sequence_results_and_metadata_classes(
    tmp_path: Path,
) -> None:
    policy = fixture_read_policy(
        minimum_ledger_seq=2,
        maximum_ledger_seq=3,
        max_results=2,
        metadata_classes=frozenset(
            {MetadataClass.ROUTING}
        ),
    )
    with open_test_system(
        tmp_path / "authority.sqlite3",
        read_policy=policy,
    ) as system:
        for index in range(3):
            system.commands.execute(
                command(key=f"event-{index}"), proof=proof()
            )

        with pytest.raises(ReadPolicyDenied):
            system.events.after(0, proof=proof())
        events = system.events.after(
            1, limit=2, proof=proof()
        )
        assert [event.ledger_seq for event in events] == [2, 3]
        with pytest.raises(ReadPolicyDenied):
            system.events.after(1, limit=3, proof=proof())
        with pytest.raises(ReadPolicyDenied):
            system.events.provenance(
                events[0].event_id, proof=proof()
            )


def test_policy_principal_is_server_owned(
    tmp_path: Path,
) -> None:
    policy = fixture_read_policy(
        principal_id="principal.other"
    )
    with open_test_system(
        tmp_path / "authority.sqlite3",
        read_policy=policy,
        principal_id="principal.alpha",
        scopes=frozenset(
            {
                "authority.observed.write",
                policy.required_scope,
            }
        ),
    ) as system:
        system.commands.execute(command(), proof=proof())
        with pytest.raises(ReadPolicyDenied):
            system.events.after(0, proof=proof())


def test_projector_policy_seam_is_bounded_and_not_a_projector(
    tmp_path: Path,
) -> None:
    policy = projector_service_read_policy(
        principal_id="projector.structural",
        allowed_security_scopes=frozenset(
            {"authority.internal"}
        ),
        allowed_trust_scopes=frozenset(
            {TrustScope.OBSERVED}
        ),
        max_results=5,
    )
    assert policy.purpose == "projector.structural"
    assert policy.required_scope == (
        "authority.projector.events.read"
    )
    assert policy.metadata_classes == frozenset(
        {MetadataClass.ROUTING, MetadataClass.PROVENANCE}
    )

    with open_test_system(
        tmp_path / "authority.sqlite3",
        read_policy=policy,
        principal_id="projector.structural",
        scopes=frozenset(
            {
                "authority.observed.write",
                policy.required_scope,
            }
        ),
    ) as system:
        committed = system.commands.execute(
            command(), proof=proof()
        )
        assert len(
            system.events.after(0, proof=proof())
        ) == 1
        assert system.events.provenance(
            committed.event_id, proof=proof()
        ).event.event_id == committed.event_id
        with pytest.raises(ReadPolicyDenied):
            system.events.command_result(
                committed.command_id, proof=proof()
            )


def test_successful_read_audit_retention_is_explicitly_deferred() -> None:
    assert SUCCESSFUL_READ_AUDIT_STATUS == "DEFERRED"
