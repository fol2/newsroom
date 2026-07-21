from __future__ import annotations

from dataclasses import replace
from pathlib import Path

import pytest

from newsroom.authority import AggregateId, InlinePayload, SemanticCommand
from newsroom.projection import (
    ProjectionDeliveryOutcome,
    ProjectionDeliveryRequest,
    ProjectionFamilyRegistrationRequest,
    ProjectionGapResolutionRequest,
    ProjectionGapState,
    ProjectionGenerationCreateRequest,
    ProjectionGenerationId,
    ProjectionGenerationState,
    ProjectionGenerationTransitionRequest,
    ProjectionStateError,
    ProjectionContractRegistry,
    ProjectionFamilyRegistry,
)

from .projection_b1_helpers import (
    FAMILY_ID,
    open_projection_system,
    projection_contracts,
    proof,
)


def _source_command(*, aggregate_id: AggregateId | None = None, key: str) -> SemanticCommand:
    return SemanticCommand(
        command_type="source.item.write",
        aggregate_id=aggregate_id or AggregateId.new(),
        expected_aggregate_version=0,
        payload=InlinePayload({"headline": "Golden", "count": 1}),
        idempotency_key=key,
    )


def _register_and_create(system):
    family = system.projections.register_family(
        ProjectionFamilyRegistrationRequest(FAMILY_ID, "family-register"),
        proof=proof(),
    )
    generation_id = ProjectionGenerationId.new()
    generation = system.projections.create_generation(
        ProjectionGenerationCreateRequest(
            generation_id,
            FAMILY_ID,
            "INITIAL_BUILD",
            "generation-create",
        ),
        proof=proof(),
    )
    return family, generation


def test_family_and_generation_authority_are_idempotent_and_historical(
    tmp_path: Path,
) -> None:
    system = open_projection_system(tmp_path / "authority.sqlite3")
    try:
        family, generation = _register_and_create(system)
        replayed_family = system.projections.register_family(
            ProjectionFamilyRegistrationRequest(FAMILY_ID, "family-register"),
            proof=proof(),
        )
        replayed_generation = system.projections.create_generation(
            ProjectionGenerationCreateRequest(
                generation.generation_id,
                FAMILY_ID,
                "INITIAL_BUILD",
                "generation-create",
            ),
            proof=proof(),
        )
        assert replayed_family == family
        assert replayed_generation == generation

        validating = system.projections.transition_generation(
            ProjectionGenerationTransitionRequest(
                generation.generation_id,
                generation.authority_aggregate_version,
                ProjectionGenerationState.VALIDATING,
                "VALIDATED_EMPTY_BUILD",
                "generation-validating",
                validated_through_ledger_seq=0,
            ),
            proof=proof(),
        )
        assert validating.state is ProjectionGenerationState.VALIDATING

        # A lost-response retry returns the exact BUILDING result rather than
        # silently returning the later mutable generation head.
        historical_create = system.projections.create_generation(
            ProjectionGenerationCreateRequest(
                generation.generation_id,
                FAMILY_ID,
                "INITIAL_BUILD",
                "generation-create",
            ),
            proof=proof(),
        )
        assert historical_create.state is ProjectionGenerationState.BUILDING
        assert historical_create.lifecycle_version == 1
        assert historical_create.authority_aggregate_version == 1
    finally:
        system.close()


def test_contiguous_checkpoint_auto_skips_optional_control_events(
    tmp_path: Path,
) -> None:
    system = open_projection_system(tmp_path / "authority.sqlite3")
    try:
        _, generation = _register_and_create(system)
        source = system.commands.execute(_source_command(key="source-1"), proof=proof())
        source_event = system.events.after(0, limit=100, proof=proof())[-1]
        assert source_event.command_id == str(source.command_id)

        # The family/generation control events are unmapped and therefore
        # deterministically optional. Applying the required source event must
        # advance across them and across the delivery command's own event,
        # otherwise projector bookkeeping would create an infinite ledger tail.
        delivered = system.projections.record_delivery(
            ProjectionDeliveryRequest(
                generation.generation_id,
                generation.authority_aggregate_version,
                source_event.ledger_seq,
                ProjectionDeliveryOutcome.APPLIED,
                "deliver-source-1",
            ),
            proof=proof(),
        )
        assert delivered.finalized is True
        status = system.projections.status(FAMILY_ID, proof=proof())
        ledger = system.events.after(0, limit=100, proof=proof())
        assert status.contiguous_ledger_seq == ledger[-1].ledger_seq
        assert status.open_gap_count == 0
    finally:
        system.close()


def test_out_of_order_required_event_creates_gap_then_recovers(
    tmp_path: Path,
) -> None:
    system = open_projection_system(tmp_path / "authority.sqlite3")
    try:
        _, generation = _register_and_create(system)
        system.commands.execute(_source_command(key="source-1"), proof=proof())
        system.commands.execute(_source_command(key="source-2"), proof=proof())
        source_events = [
            item
            for item in system.events.after(0, limit=100, proof=proof())
            if item.event_type == "source.item.versioned"
        ]
        first, second = source_events

        later = system.projections.record_delivery(
            ProjectionDeliveryRequest(
                generation.generation_id,
                generation.authority_aggregate_version,
                second.ledger_seq,
                ProjectionDeliveryOutcome.APPLIED,
                "deliver-later",
            ),
            proof=proof(),
        )
        assert later.finalized is True
        gaps = system.projections.gaps(
            generation.generation_id, proof=proof()
        )
        assert len(gaps) == 1
        assert gaps[0].ledger_seq_start == first.ledger_seq
        assert gaps[0].required is True
        assert gaps[0].state is ProjectionGapState.OPEN
        status = system.projections.status(FAMILY_ID, proof=proof())
        assert status.contiguous_ledger_seq < first.ledger_seq

        current = system.projections.generations(FAMILY_ID, proof=proof())[0]
        recovered = system.projections.record_delivery(
            ProjectionDeliveryRequest(
                generation.generation_id,
                current.authority_aggregate_version,
                first.ledger_seq,
                ProjectionDeliveryOutcome.APPLIED,
                "deliver-missing",
            ),
            proof=proof(),
        )
        assert recovered.finalized is True
        gap = system.projections.gaps(
            generation.generation_id, proof=proof()
        )[0]
        assert gap.state is ProjectionGapState.OPEN
        current = system.projections.generations(FAMILY_ID, proof=proof())[0]
        resolved = system.projections.resolve_gap(
            ProjectionGapResolutionRequest(
                generation.generation_id,
                current.authority_aggregate_version,
                gap.gap_id,
                "SUCCESSFUL_REPLAY_CONFIRMED",
                "resolve-missing-gap",
            ),
            proof=proof(),
        )
        assert resolved.state is ProjectionGapState.RESOLVED
        status = system.projections.status(FAMILY_ID, proof=proof())
        ledger = system.events.after(0, limit=100, proof=proof())
        assert status.contiguous_ledger_seq == ledger[-1].ledger_seq
    finally:
        system.close()


def test_retry_exhaustion_dead_letters_without_skip_and_allows_recovery(
    tmp_path: Path,
) -> None:
    system = open_projection_system(tmp_path / "authority.sqlite3")
    try:
        _, generation = _register_and_create(system)
        system.commands.execute(_source_command(key="source-retry"), proof=proof())
        source = [
            item
            for item in system.events.after(0, limit=100, proof=proof())
            if item.event_type == "source.item.versioned"
        ][0]

        first_request = None
        first_result = None
        for attempt in range(1, 4):
            current = system.projections.generations(FAMILY_ID, proof=proof())[0]
            request = ProjectionDeliveryRequest(
                generation.generation_id,
                current.authority_aggregate_version,
                source.ledger_seq,
                ProjectionDeliveryOutcome.RETRYABLE_FAILURE,
                f"retry-{attempt}",
                error_code="TRANSIENT_GRAPH_FAILURE",
            )
            result = system.projections.record_delivery(request, proof=proof())
            if attempt == 1:
                first_request = request
                first_result = result
            assert result.attempt_count == attempt
            assert result.finalized is (attempt == 3)

        dead_letters = system.projections.dead_letters(
            generation.generation_id, proof=proof()
        )
        assert len(dead_letters) == 1
        assert dead_letters[0].ledger_seq == source.ledger_seq
        status = system.projections.status(FAMILY_ID, proof=proof())
        assert status.contiguous_ledger_seq < source.ledger_seq
        assert status.open_gap_count == 1

        assert first_request is not None and first_result is not None
        historical = system.projections.record_delivery(
            first_request, proof=proof()
        )
        assert historical.attempt_count == 1
        assert historical.finalized is False
        assert historical.authority_event_id == first_result.authority_event_id

        current = system.projections.generations(FAMILY_ID, proof=proof())[0]
        recovered = system.projections.record_delivery(
            ProjectionDeliveryRequest(
                generation.generation_id,
                current.authority_aggregate_version,
                source.ledger_seq,
                ProjectionDeliveryOutcome.APPLIED,
                "recovered-after-dead-letter",
            ),
            proof=proof(),
        )
        assert recovered.attempt_count == 4
        assert recovered.finalized is True
        gap = system.projections.gaps(
            generation.generation_id, proof=proof()
        )[0]
        assert gap.state is ProjectionGapState.OPEN
        current = system.projections.generations(FAMILY_ID, proof=proof())[0]
        resolved = system.projections.resolve_gap(
            ProjectionGapResolutionRequest(
                generation.generation_id,
                current.authority_aggregate_version,
                gap.gap_id,
                "DEAD_LETTER_REPLAYED",
                "resolve-dead-letter-gap",
            ),
            proof=proof(),
        )
        assert resolved.state is ProjectionGapState.RESOLVED
    finally:
        system.close()


def test_generation_validation_cannot_cross_required_gap(
    tmp_path: Path,
) -> None:
    system = open_projection_system(tmp_path / "authority.sqlite3")
    try:
        _, generation = _register_and_create(system)
        system.commands.execute(_source_command(key="source-1"), proof=proof())
        system.commands.execute(_source_command(key="source-2"), proof=proof())
        source_events = [
            item
            for item in system.events.after(0, limit=100, proof=proof())
            if item.event_type == "source.item.versioned"
        ]
        current = system.projections.generations(FAMILY_ID, proof=proof())[0]
        system.projections.record_delivery(
            ProjectionDeliveryRequest(
                generation.generation_id,
                current.authority_aggregate_version,
                source_events[1].ledger_seq,
                ProjectionDeliveryOutcome.APPLIED,
                "out-of-order",
            ),
            proof=proof(),
        )
        current = system.projections.generations(FAMILY_ID, proof=proof())[0]
        with pytest.raises(ProjectionStateError, match="contiguous checkpoint"):
            system.projections.transition_generation(
                ProjectionGenerationTransitionRequest(
                    generation.generation_id,
                    current.authority_aggregate_version,
                    ProjectionGenerationState.VALIDATING,
                    "VALIDATE_ACROSS_GAP",
                    "validate-gap",
                    validated_through_ledger_seq=source_events[1].ledger_seq,
                ),
                proof=proof(),
            )
    finally:
        system.close()


def test_one_active_generation_per_family_is_enforced_before_commit(
    tmp_path: Path,
) -> None:
    system = open_projection_system(tmp_path / "authority.sqlite3")
    try:
        system.projections.register_family(
            ProjectionFamilyRegistrationRequest(FAMILY_ID, "family-register"),
            proof=proof(),
        )
        first = system.projections.create_generation(
            ProjectionGenerationCreateRequest(
                ProjectionGenerationId.new(), FAMILY_ID, "FIRST", "gen-first"
            ),
            proof=proof(),
        )
        second = system.projections.create_generation(
            ProjectionGenerationCreateRequest(
                ProjectionGenerationId.new(), FAMILY_ID, "SECOND", "gen-second"
            ),
            proof=proof(),
        )
        first_validating = system.projections.transition_generation(
            ProjectionGenerationTransitionRequest(
                first.generation_id,
                first.authority_aggregate_version,
                ProjectionGenerationState.VALIDATING,
                "FIRST_VALID",
                "first-validating",
                validated_through_ledger_seq=0,
            ),
            proof=proof(),
        )
        system.projections.transition_generation(
            ProjectionGenerationTransitionRequest(
                first.generation_id,
                first_validating.authority_aggregate_version,
                ProjectionGenerationState.ACTIVE,
                "FIRST_ACTIVE",
                "first-active",
                validated_through_ledger_seq=0,
            ),
            proof=proof(),
        )
        second_validating = system.projections.transition_generation(
            ProjectionGenerationTransitionRequest(
                second.generation_id,
                second.authority_aggregate_version,
                ProjectionGenerationState.VALIDATING,
                "SECOND_VALID",
                "second-validating",
                validated_through_ledger_seq=0,
            ),
            proof=proof(),
        )
        with pytest.raises(ProjectionStateError, match="already has an active"):
            system.projections.transition_generation(
                ProjectionGenerationTransitionRequest(
                    second.generation_id,
                    second_validating.authority_aggregate_version,
                    ProjectionGenerationState.ACTIVE,
                    "SECOND_ACTIVE",
                    "second-active",
                    validated_through_ledger_seq=0,
                ),
                proof=proof(),
            )
    finally:
        system.close()


def test_required_unsupported_event_creates_dead_letter_and_gap(
    tmp_path: Path,
) -> None:
    system = open_projection_system(tmp_path / "authority.sqlite3")
    try:
        _, generation = _register_and_create(system)
        system.commands.execute(_source_command(key="unsupported-source"), proof=proof())
        source = [
            item
            for item in system.events.after(0, limit=100, proof=proof())
            if item.event_type == "source.item.versioned"
        ][0]
        record = system.projections.record_delivery(
            ProjectionDeliveryRequest(
                generation.generation_id,
                generation.authority_aggregate_version,
                source.ledger_seq,
                ProjectionDeliveryOutcome.REQUIRED_UNSUPPORTED,
                "required-unsupported",
                error_code="PROJECTOR_VERSION_UNSUPPORTED",
            ),
            proof=proof(),
        )
        assert record.required is True
        assert record.finalized is True
        assert record.outcome is ProjectionDeliveryOutcome.REQUIRED_UNSUPPORTED
        assert len(system.projections.dead_letters(
            generation.generation_id, proof=proof()
        )) == 1
        gap = system.projections.gaps(
            generation.generation_id, proof=proof()
        )[0]
        assert gap.required is True
        assert gap.state is ProjectionGapState.OPEN
        assert system.projections.status(
            FAMILY_ID, proof=proof()
        ).contiguous_ledger_seq < source.ledger_seq
    finally:
        system.close()


def test_delivery_cannot_target_its_own_authority_event(
    tmp_path: Path,
) -> None:
    system = open_projection_system(tmp_path / "authority.sqlite3")
    try:
        _, generation = _register_and_create(system)
        before = system.events.after(0, limit=100, proof=proof())
        guessed_current_command_seq = before[-1].ledger_seq + 1
        with pytest.raises(ProjectionStateError, match="own authority event"):
            system.projections.record_delivery(
                ProjectionDeliveryRequest(
                    generation.generation_id,
                    generation.authority_aggregate_version,
                    guessed_current_command_seq,
                    ProjectionDeliveryOutcome.IGNORED_OPTIONAL,
                    "self-delivery",
                ),
                proof=proof(),
            )
        after = system.events.after(0, limit=100, proof=proof())
        assert after == before
        assert system.projections.generations(
            FAMILY_ID, proof=proof()
        )[0].authority_aggregate_version == generation.authority_aggregate_version
    finally:
        system.close()



def _rolled_projection_contracts(*, include_v1: bool = True) -> ProjectionContractRegistry:
    base = projection_contracts()
    v1 = base.families.resolve(FAMILY_ID, "family-v1")
    v2 = replace(
        v1,
        definition_version="family-v2",
        projector_version="structural-projector-v2",
        max_delivery_attempts=1,
    )
    definitions = (v1, v2) if include_v1 else (v2,)
    families = ProjectionFamilyRegistry(
        definitions,
        ontologies=base.ontologies,
        mappings=base.mappings,
        current_versions={FAMILY_ID: "family-v2"},
    )
    return ProjectionContractRegistry(
        ontologies=base.ontologies,
        mappings=base.mappings,
        families=families,
        graphiti_workspaces=base.graphiti_workspaces,
    )


def test_generation_transition_replay_returns_historical_result_after_later_states(
    tmp_path: Path,
) -> None:
    system = open_projection_system(tmp_path / "authority.sqlite3")
    try:
        _, generation = _register_and_create(system)
        validating_request = ProjectionGenerationTransitionRequest(
            generation.generation_id,
            generation.authority_aggregate_version,
            ProjectionGenerationState.VALIDATING,
            "VALIDATED_EMPTY_BUILD",
            "generation-validating-replay",
            validated_through_ledger_seq=0,
        )
        validating = system.projections.transition_generation(
            validating_request, proof=proof()
        )
        active_request = ProjectionGenerationTransitionRequest(
            generation.generation_id,
            validating.authority_aggregate_version,
            ProjectionGenerationState.ACTIVE,
            "ACTIVATE_EMPTY_BUILD",
            "generation-active-replay",
            validated_through_ledger_seq=0,
        )
        active = system.projections.transition_generation(
            active_request, proof=proof()
        )
        retired = system.projections.transition_generation(
            ProjectionGenerationTransitionRequest(
                generation.generation_id,
                active.authority_aggregate_version,
                ProjectionGenerationState.RETIRED,
                "REPLACED",
                "generation-retired",
            ),
            proof=proof(),
        )
        assert retired.validated_through_ledger_seq == 0

        historical_validating = system.projections.transition_generation(
            validating_request, proof=proof()
        )
        historical_active = system.projections.transition_generation(
            active_request, proof=proof()
        )
        assert historical_validating.state is ProjectionGenerationState.VALIDATING
        assert historical_validating.lifecycle_version == validating.lifecycle_version
        assert historical_active.state is ProjectionGenerationState.ACTIVE
        assert historical_active.lifecycle_version == active.lifecycle_version
        assert system.projections.generations(FAMILY_ID, proof=proof())[0].state is (
            ProjectionGenerationState.RETIRED
        )
    finally:
        system.close()


def test_terminal_generation_rejects_delivery_and_gap_resolution_atomically(
    tmp_path: Path,
) -> None:
    system = open_projection_system(tmp_path / "authority.sqlite3")
    try:
        _, generation = _register_and_create(system)
        system.commands.execute(_source_command(key="terminal-source-1"), proof=proof())
        system.commands.execute(_source_command(key="terminal-source-2"), proof=proof())
        sources = [
            item
            for item in system.events.after(0, limit=100, proof=proof())
            if item.event_type == "source.item.versioned"
        ]
        current = system.projections.generations(FAMILY_ID, proof=proof())[0]
        system.projections.record_delivery(
            ProjectionDeliveryRequest(
                generation.generation_id,
                current.authority_aggregate_version,
                sources[1].ledger_seq,
                ProjectionDeliveryOutcome.APPLIED,
                "terminal-out-of-order",
            ),
            proof=proof(),
        )
        gap = system.projections.gaps(generation.generation_id, proof=proof())[0]
        current = system.projections.generations(FAMILY_ID, proof=proof())[0]
        failed = system.projections.transition_generation(
            ProjectionGenerationTransitionRequest(
                generation.generation_id,
                current.authority_aggregate_version,
                ProjectionGenerationState.FAILED,
                "TERMINAL_FAILURE",
                "terminal-failed",
            ),
            proof=proof(),
        )
        before = system.events.after(0, limit=1000, proof=proof())

        with pytest.raises(ProjectionStateError, match="terminal"):
            system.projections.record_delivery(
                ProjectionDeliveryRequest(
                    generation.generation_id,
                    failed.authority_aggregate_version,
                    sources[0].ledger_seq,
                    ProjectionDeliveryOutcome.APPLIED,
                    "terminal-delivery",
                ),
                proof=proof(),
            )
        with pytest.raises(ProjectionStateError, match="terminal"):
            system.projections.resolve_gap(
                ProjectionGapResolutionRequest(
                    generation.generation_id,
                    failed.authority_aggregate_version,
                    gap.gap_id,
                    "TERMINAL_GAP",
                    "terminal-gap",
                ),
                proof=proof(),
            )
        assert system.events.after(0, limit=1000, proof=proof()) == before
        assert system.projections.generations(FAMILY_ID, proof=proof())[0] == failed
    finally:
        system.close()


def test_registered_family_and_registration_replay_use_retained_definition_after_rollout(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    initial = open_projection_system(database, contracts=projection_contracts())
    family = initial.projections.register_family(
        ProjectionFamilyRegistrationRequest(FAMILY_ID, "family-rollout"),
        proof=proof(),
    )
    initial.close()

    rolled = open_projection_system(
        database,
        contracts=_rolled_projection_contracts(),
    )
    try:
        replayed = rolled.projections.register_family(
            ProjectionFamilyRegistrationRequest(FAMILY_ID, "family-rollout"),
            proof=proof(),
        )
        assert replayed == family
        status = rolled.projections.status(FAMILY_ID, proof=proof())
        retained = projection_contracts().families.resolve(FAMILY_ID, "family-v1")
        assert status.projector_version == retained.projector_version
        assert status.ontology_contract_digest == retained.ontology_contract_digest
        assert status.mapping_contract_digest == retained.mapping_contract_digest
    finally:
        rolled.close()


def test_reopen_fails_when_registered_family_definition_is_not_retained(
    tmp_path: Path,
) -> None:
    database = tmp_path / "authority.sqlite3"
    system = open_projection_system(database, contracts=projection_contracts())
    system.projections.register_family(
        ProjectionFamilyRegistrationRequest(FAMILY_ID, "family-retained"),
        proof=proof(),
    )
    system.close()

    with pytest.raises(Exception, match="definition is unavailable"):
        open_projection_system(
            database,
            contracts=_rolled_projection_contracts(include_v1=False),
        )


def test_family_registration_rejects_authority_change_between_lookup_and_commit(
    tmp_path: Path,
) -> None:
    from newsroom.authority import StaticAuthenticator, StaticPrincipal

    class AlternatingDomainAuthenticator:
        def __init__(self) -> None:
            self.calls = 0
            self.first = StaticAuthenticator(
                credentials={"token-1": StaticPrincipal("principal.alpha")},
                authority_domain="newsroom.authority.first",
            )
            self.second = StaticAuthenticator(
                credentials={"token-1": StaticPrincipal("principal.alpha")},
                authority_domain="newsroom.authority.second",
            )

        def authenticate(self, authentication_proof: object, *, now: object) -> object:
            self.calls += 1
            selected = self.first if self.calls % 2 == 1 else self.second
            return selected.authenticate(authentication_proof, now=now)

    database = tmp_path / "authority.sqlite3"
    system = open_projection_system(
        database,
        authenticator=AlternatingDomainAuthenticator(),
    )
    try:
        with pytest.raises(PermissionError, match="authority changed"):
            system.projections.register_family(
                ProjectionFamilyRegistrationRequest(FAMILY_ID, "family-switch"),
                proof=proof(),
            )
    finally:
        system.close()

    reopened = open_projection_system(database)
    try:
        with pytest.raises(ProjectionStateError, match="not registered"):
            reopened.projections.status(FAMILY_ID, proof=proof())
        assert not [
            event
            for event in reopened.events.after(0, limit=100, proof=proof())
            if event.event_type == "projection.family.registered"
        ]
    finally:
        reopened.close()


def test_active_generation_requires_validation_through_current_checkpoint(
    tmp_path: Path,
) -> None:
    system = open_projection_system(tmp_path / "authority.sqlite3")
    try:
        _, generation = _register_and_create(system)
        system.commands.execute(
            _source_command(key="activation-validation-source"), proof=proof()
        )
        source = [
            item
            for item in system.events.after(0, limit=100, proof=proof())
            if item.event_type == "source.item.versioned"
        ][0]
        current = system.projections.generations(FAMILY_ID, proof=proof())[0]
        system.projections.record_delivery(
            ProjectionDeliveryRequest(
                generation.generation_id,
                current.authority_aggregate_version,
                source.ledger_seq,
                ProjectionDeliveryOutcome.APPLIED,
                "activation-validation-delivery",
            ),
            proof=proof(),
        )
        checkpoint = system.projections.status(
            FAMILY_ID, proof=proof()
        ).contiguous_ledger_seq
        assert checkpoint > 0
        current = system.projections.generations(FAMILY_ID, proof=proof())[0]
        validating = system.projections.transition_generation(
            ProjectionGenerationTransitionRequest(
                generation.generation_id,
                current.authority_aggregate_version,
                ProjectionGenerationState.VALIDATING,
                "PARTIAL_VALIDATION",
                "partial-validation",
                validated_through_ledger_seq=checkpoint - 1,
            ),
            proof=proof(),
        )
        before = system.events.after(0, limit=1000, proof=proof())
        with pytest.raises(ProjectionStateError, match="current contiguous checkpoint"):
            system.projections.transition_generation(
                ProjectionGenerationTransitionRequest(
                    generation.generation_id,
                    validating.authority_aggregate_version,
                    ProjectionGenerationState.ACTIVE,
                    "PARTIAL_ACTIVATION",
                    "partial-activation",
                    validated_through_ledger_seq=checkpoint - 1,
                ),
                proof=proof(),
            )
        assert system.events.after(0, limit=1000, proof=proof()) == before
        active = system.projections.transition_generation(
            ProjectionGenerationTransitionRequest(
                generation.generation_id,
                validating.authority_aggregate_version,
                ProjectionGenerationState.ACTIVE,
                "COMPLETE_ACTIVATION",
                "complete-activation",
                validated_through_ledger_seq=checkpoint,
            ),
            proof=proof(),
        )
        assert active.state is ProjectionGenerationState.ACTIVE
        assert active.validated_through_ledger_seq == checkpoint
    finally:
        system.close()


def test_optional_delivery_can_be_explicitly_ignored_after_retry_exhaustion(
    tmp_path: Path,
) -> None:
    system = open_projection_system(tmp_path / "authority.sqlite3")
    try:
        _, generation = _register_and_create(system)
        system.commands.execute(
            SemanticCommand(
                command_type="candidate.fixture.write",
                aggregate_id=AggregateId.new(),
                expected_aggregate_version=0,
                payload=InlinePayload({"headline": "Optional", "count": 1}),
                idempotency_key="optional-event",
            ),
            proof=proof(),
        )
        source = [
            event
            for event in system.events.after(0, limit=100, proof=proof())
            if event.event_type == "candidate.derived"
        ][0]
        for attempt in range(1, 4):
            current = system.projections.generations(FAMILY_ID, proof=proof())[0]
            result = system.projections.record_delivery(
                ProjectionDeliveryRequest(
                    generation.generation_id,
                    current.authority_aggregate_version,
                    source.ledger_seq,
                    ProjectionDeliveryOutcome.RETRYABLE_FAILURE,
                    f"optional-retry-{attempt}",
                    error_code="OPTIONAL_PROJECTOR_FAILURE",
                ),
                proof=proof(),
            )
        assert result.finalized is True
        gap = system.projections.gaps(generation.generation_id, proof=proof())[0]
        assert gap.required is False

        current = system.projections.generations(FAMILY_ID, proof=proof())[0]
        ignored = system.projections.record_delivery(
            ProjectionDeliveryRequest(
                generation.generation_id,
                current.authority_aggregate_version,
                source.ledger_seq,
                ProjectionDeliveryOutcome.IGNORED_OPTIONAL,
                "optional-explicit-ignore",
            ),
            proof=proof(),
        )
        assert ignored.finalized is True
        assert ignored.outcome is ProjectionDeliveryOutcome.IGNORED_OPTIONAL
        current = system.projections.generations(FAMILY_ID, proof=proof())[0]
        resolved = system.projections.resolve_gap(
            ProjectionGapResolutionRequest(
                generation.generation_id,
                current.authority_aggregate_version,
                gap.gap_id,
                "OPTIONAL_EVENT_EXPLICITLY_IGNORED",
                "optional-gap-resolve",
            ),
            proof=proof(),
        )
        assert resolved.state is ProjectionGapState.RESOLVED
        assert system.projections.status(
            FAMILY_ID, proof=proof()
        ).contiguous_ledger_seq >= source.ledger_seq
    finally:
        system.close()
