from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1 or new in text:
        raise SystemExit(f"qualifier source mismatch in {path}: {old[:120]}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    store = "newsroom/authority/_integrated_store.py"
    replace_exact(
        store,
        '''        admission = conn.execute(
            "SELECT a.blob_digest,a.valid_from,a.valid_until,"
            "v.state AS admission_state,bv.state AS blob_state,"
            "bv.integrity_state,r.allowed AS rights_allowed,"
            "r.valid_from AS rights_valid_from,r.valid_until AS rights_valid_until "
            "FROM object_admissions a "
            "JOIN object_admission_heads h ON h.admission_id=a.admission_id "''',
        '''        admission = conn.execute(
            "SELECT a.blob_digest,b.size_bytes AS blob_size_bytes,"
            "a.valid_from,a.valid_until,"
            "v.state AS admission_state,bv.state AS blob_state,"
            "bv.integrity_state,r.allowed AS rights_allowed,"
            "r.valid_from AS rights_valid_from,r.valid_until AS rights_valid_until "
            "FROM object_admissions a "
            "JOIN blob_identities b ON b.blob_digest=a.blob_digest "
            "JOIN object_admission_heads h ON h.admission_id=a.admission_id "''',
    )
    replace_exact(
        store,
        '''            or int(access["byte_offset"]) != 0
            or int(access["allowed_bytes"]) <= 0
            or access_value.get("admission_id") != str(context.admission_id)''',
        '''            or int(access["byte_offset"]) != 0
            or int(access["allowed_bytes"])
            != int(admission["blob_size_bytes"])
            or str(access["decided_at"]) != context.recorded_at.to_text()
            or access_value.get("decided_at")
            != context.recorded_at.to_text()
            or access_value.get("admission_id") != str(context.admission_id)''',
    )

    test_path = Path("newsroom/tests/test_integrated_c1_hydration_commit.py")
    if test_path.exists():
        raise SystemExit(f"qualifier test path already exists: {test_path}")
    test_path.write_text(
        '''from __future__ import annotations

from dataclasses import replace
from datetime import timedelta
from pathlib import Path

import pytest

from newsroom.authority import HydrationRequest, UtcTimestamp
from newsroom.integrated import IntegratedStateError

from .authority_a2b_helpers import _policy_registries, open_object_system
from .authority_helpers import FIXED_NOW
from .integrated_c1_helpers import (
    authenticator,
    authorizer,
    candidate_request,
    event_policy,
    proof,
    scopes,
)
from .projection_b1_helpers import projection_contracts, projection_read_policy
from newsroom.authority._integrated_system import _open_candidate_with_adapter
from .test_integrated_c1_candidate_authority import (
    _open_candidate_system,
    _seed,
)


def _partial_hydration(tmp_path: Path, database, state):
    rights, hydration, admissions = _policy_registries()
    system = open_object_system(
        database,
        object_root=tmp_path / "objects",
        scopes=scopes(),
        policy_registries=(rights, hydration, admissions),
        authenticator=authenticator(),
        authorizer=authorizer(),
        clock=lambda: FIXED_NOW,
        command_registry=state.commands,
        payload_schema_registry=state.schemas,
    )
    try:
        length = len(state.manifest.canonical_bytes) - 1
        assert length > 0
        hydrated = system.objects.hydrate(
            HydrationRequest(
                state.admission_id,
                "project.discovery",
                offset=0,
                length=length,
            ),
            proof=proof(),
        )
        assert len(hydrated.data) == length
        return hydrated
    finally:
        system.close()


def test_partial_hydration_decision_cannot_commit_candidate_authority(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    partial = _partial_hydration(tmp_path, database, state)
    changed = replace(
        graph.context,
        hydration_access_decision_id=(
            partial.decision.access_decision_id
        ),
        recorded_at=partial.decision.decided_at,
    )
    system = _open_candidate_system(database, state, graph)
    try:
        before = system.events.after(0, limit=1000, proof=proof())
        with pytest.raises(
            IntegratedStateError,
            match="hydration decision differs",
        ):
            system.candidates.admit(
                candidate_request(
                    changed,
                    key="integrated-partial-hydration-candidate",
                ),
                context=changed,
                manifest=state.manifest,
                proof=proof(),
            )
        assert system.events.after(0, limit=1000, proof=proof()) == before
    finally:
        system.close()


def test_hydration_decision_time_cannot_be_rebound_at_candidate_commit(
    tmp_path: Path,
) -> None:
    database, state, graph = _seed(tmp_path)
    later = UtcTimestamp(FIXED_NOW.value + timedelta(minutes=1))
    changed = replace(graph.context, recorded_at=later)
    system = _open_candidate_with_adapter(
        path=database,
        registry=state.commands,
        payload_schemas=state.schemas,
        contracts=projection_contracts(),
        authenticator=authenticator(),
        authorizer=authorizer(),
        event_read_policy=event_policy(),
        projection_read_policy=projection_read_policy(),
        adapter=graph.adapter,
        clock=lambda: later,
    )
    try:
        before = system.events.after(0, limit=1000, proof=proof())
        with pytest.raises(
            IntegratedStateError,
            match="hydration decision differs",
        ):
            system.candidates.admit(
                candidate_request(
                    changed,
                    key="integrated-hydration-time-rebind",
                ),
                context=changed,
                manifest=state.manifest,
                proof=proof(),
            )
        assert system.events.after(0, limit=1000, proof=proof()) == before
    finally:
        system.close()
''',
        encoding="utf-8",
    )


if __name__ == "__main__":
    main()
