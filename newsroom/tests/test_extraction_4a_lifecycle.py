from __future__ import annotations

from pathlib import Path

import pytest

from newsroom.authority.object_policy import merge_authority_registries
from newsroom.extraction import (
    ExtractionRightsDenied,
    merge_extraction_authority_registries,
)
from newsroom.sources import (
    SourceDefinitionVersionId,
    open_governed_source_registry_authority_system,
)

from .authority_a2b_helpers import open_object_system
from .extraction_4a_helpers import (
    RUN_VERSION_1_ID,
    contract_request,
    extraction_proof,
    open_extraction_system,
    run_request,
    seed_extraction_fixture,
)
from .source_3a_helpers import (
    SOURCE_NOW,
    VERSION_2_ID,
    authenticator,
    authorizer,
    proof,
    read_policy,
    version_request,
)


def _combined_registries(state):
    commands, schemas = merge_extraction_authority_registries(
        command_registry=state.commands,
        payload_schemas=state.schemas,
    )
    return merge_authority_registries(
        command_registry=commands,
        payload_schemas=schemas,
    )


def _seed_retained_run(state):
    with open_extraction_system(state) as system:
        system.extraction.register_contract(
            contract_request(), proof=extraction_proof()
        )
        result = system.extraction.execute(
            run_request(state), proof=extraction_proof()
        )
    assert result.output is not None
    return result


def test_requested_deletion_remains_readable_until_tombstone_then_blocks_use(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    result = _seed_retained_run(state)
    passage = state.input_binding.passages[0]
    commands, schemas = _combined_registries(state)

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
            idempotency_key="increment-4a-delete-request",
            proof=proof(),
        )

    # A REQUESTED deletion is an inspectable pending lifecycle state. The object
    # remains active until the separate tombstone decision, so replay is allowed.
    with open_extraction_system(state) as system:
        replay = system.extraction.execute(
            run_request(state), proof=extraction_proof()
        )
        assert replay.replayed is True
        assert replay.event_id == result.event_id

    with open_object_system(
        state.database,
        object_root=state.object_root,
        clock=lambda: SOURCE_NOW,
        command_registry=commands,
        payload_schema_registry=schemas,
    ) as objects:
        objects.objects.tombstone(
            deletion.deletion_id,
            reason_code="RIGHTS_TOMBSTONE",
            idempotency_key="increment-4a-tombstone",
            proof=proof(),
        )

    # Historical authority can still reopen, but every downstream use rechecks
    # current governed-object lifecycle and fails closed after tombstoning.
    with open_extraction_system(state) as reopened:
        with pytest.raises(ExtractionRightsDenied):
            reopened.extraction.execute(
                run_request(state), proof=extraction_proof()
            )
        with pytest.raises(ExtractionRightsDenied):
            reopened.extraction.metadata(
                RUN_VERSION_1_ID, proof=extraction_proof()
            )
        with pytest.raises(ExtractionRightsDenied):
            reopened.extraction.raw_output(
                result.output.output_id, proof=extraction_proof()
            )


def test_source_version_change_blocks_replay_and_retained_downstream_use(
    tmp_path: Path,
) -> None:
    state = seed_extraction_fixture(tmp_path)
    _seed_retained_run(state)
    commands, schemas = _combined_registries(state)

    version_3 = SourceDefinitionVersionId.parse(
        "00000000-0000-4000-8000-000000005201"
    )
    with open_governed_source_registry_authority_system(
        path=state.database,
        registry=commands,
        payload_schemas=schemas,
        authenticator=authenticator(),
        authorizer=authorizer(),
        read_policy=read_policy(),
        clock=lambda: SOURCE_NOW,
    ) as sources:
        sources.sources.record_definition_version(
            version_request(
                version_id=version_3,
                version_number=3,
                previous_version_id=VERSION_2_ID,
                locator="fixture://increment-4a/maintained-guidance-v3",
                key="increment-4a-source-version-v3",
            ),
            proof=proof(),
        )

    with open_extraction_system(state) as reopened:
        with pytest.raises(ExtractionRightsDenied, match="no longer current"):
            reopened.extraction.execute(
                run_request(state), proof=extraction_proof()
            )
        with pytest.raises(ExtractionRightsDenied, match="no longer current"):
            reopened.extraction.metadata(
                RUN_VERSION_1_ID, proof=extraction_proof()
            )
        with pytest.raises(ExtractionRightsDenied, match="no longer current"):
            reopened.extraction.proposals(
                RUN_VERSION_1_ID, proof=extraction_proof()
            )
