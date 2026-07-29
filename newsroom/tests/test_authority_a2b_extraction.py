from __future__ import annotations

import sqlite3
from pathlib import Path

import pytest

from newsroom.authority.object_policy import merge_authority_registries
from newsroom.extraction import ExtractionRightsDenied, merge_extraction_authority_registries

from .authority_a2b_helpers import open_object_system
from .extraction_4a_helpers import (
    contract_request,
    extraction_proof,
    open_extraction_system,
    run_request,
    seed_extraction_fixture,
)
from .source_3a_helpers import SOURCE_NOW, proof


def test_extraction_rechecks_governed_object_lifecycle_before_exact_replay(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    request = run_request(state)
    with open_extraction_system(state) as system:
        system.extraction.register_contract(
            contract_request(), proof=extraction_proof()
        )
        retained = system.extraction.execute(request, proof=extraction_proof())

    commands, schemas = merge_extraction_authority_registries(
        command_registry=state.commands,
        payload_schemas=state.schemas,
    )
    commands, schemas = merge_authority_registries(
        command_registry=commands,
        payload_schemas=schemas,
    )
    passage = state.input_binding.passages[0]
    with open_object_system(
        state.database,
        object_root=state.object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=commands,
        payload_schema_registry=schemas,
    ) as objects:
        deletion = objects.objects.request_deletion(
            passage.blob_digest,
            reason_code="RIGHTS_DELETE_REQUESTED",
            idempotency_key="a2b-extraction-delete",
            proof=proof(),
        )
        objects.objects.tombstone(
            deletion.deletion_id,
            reason_code="RIGHTS_TOMBSTONE",
            idempotency_key="a2b-extraction-tombstone",
            proof=proof(),
        )

    with open_extraction_system(state) as reopened:
        with pytest.raises(ExtractionRightsDenied):
            reopened.extraction.execute(request, proof=extraction_proof())

    with sqlite3.connect(state.database) as conn:
        assert conn.execute(
            "SELECT COUNT(*) FROM extraction_run_versions"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT COUNT(*) FROM extraction_outputs"
        ).fetchone()[0] == 1
        assert conn.execute(
            "SELECT authority_event_id FROM extraction_run_versions"
        ).fetchone()[0] == str(retained.event_id)
