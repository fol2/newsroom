from __future__ import annotations

from dataclasses import dataclass

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes, digest_canonical

from ._model_common import require_idempotency_key, require_locator, require_versioned_ref
from .types import (
    BaselinePolicy,
    BaselinePolicyKind,
    CoverageContribution,
    CoverageMapping,
    CoverageResponsibility,
    EXECUTION_AUTHORITY_DISABLED,
    ExplicitSourceGap,
    ObservationModel,
    PortfolioFunction,
    RightsReference,
    SourceContractError,
    SourceDefinitionId,
    SourceDefinitionVersionId,
    SourceDependency,
    SourceLifecycleStage,
    SourceRole,
    SourceRoleAssignment,
    VersionedPolicyRef,
    bounded_text,
    bounded_text_tuple,
    sorted_coverage_mappings,
    sorted_dependencies,
    sorted_role_assignments,
    sorted_source_gaps,
    typed_enum_tuple,
)

@dataclass(frozen=True, slots=True)
class SourceDefinitionRequest:
    definition_id: SourceDefinitionId
    name: str
    editorial_purpose: str
    idempotency_key: str

    def __post_init__(self) -> None:
        if not isinstance(self.definition_id, SourceDefinitionId):
            raise SourceContractError("source definition identity must be typed")
        bounded_text(self.name, field="source_name", maximum_bytes=512)
        bounded_text(
            self.editorial_purpose,
            field="editorial_purpose",
            maximum_bytes=4096,
        )
        require_idempotency_key(self.idempotency_key)

    def canonical_value(self) -> dict[str, object]:
        return {
            "definition_id": str(self.definition_id),
            "name": self.name,
            "editorial_purpose": self.editorial_purpose,
        }

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class SourceDefinitionVersionRequest:
    version_id: SourceDefinitionVersionId
    definition_id: SourceDefinitionId
    version_number: int
    expected_previous_version_id: SourceDefinitionVersionId | None
    locator: str
    adapter_contract: VersionedPolicyRef
    extraction_scope: tuple[str, ...]
    rights: RightsReference
    roles: tuple[SourceRoleAssignment, ...]
    portfolio_functions: tuple[PortfolioFunction, ...]
    coverage_mappings: tuple[CoverageMapping, ...]
    dependencies: tuple[SourceDependency, ...]
    explicit_gaps: tuple[ExplicitSourceGap, ...]
    observation_model: ObservationModel
    baseline_policy: BaselinePolicy
    item_identity_policy: VersionedPolicyRef
    revision_policy: VersionedPolicyRef
    canonicalization_policy: VersionedPolicyRef
    lifecycle_stage: SourceLifecycleStage
    change_reason: str
    idempotency_key: str
    execution_authority: str = EXECUTION_AUTHORITY_DISABLED

    def __post_init__(self) -> None:
        if not isinstance(self.version_id, SourceDefinitionVersionId):
            raise SourceContractError("source version identity must be typed")
        if not isinstance(self.definition_id, SourceDefinitionId):
            raise SourceContractError("source definition identity must be typed")
        if (
            isinstance(self.version_number, bool)
            or not isinstance(self.version_number, int)
            or self.version_number <= 0
        ):
            raise SourceContractError("source version number must be positive")
        if self.version_number == 1:
            if self.expected_previous_version_id is not None:
                raise SourceContractError(
                    "initial source version cannot name a predecessor"
                )
        elif not isinstance(
            self.expected_previous_version_id, SourceDefinitionVersionId
        ):
            raise SourceContractError(
                "later source version requires exact predecessor identity"
            )
        require_locator(self.locator)
        require_versioned_ref(self.adapter_contract, field="adapter_contract")
        bounded_text_tuple(
            self.extraction_scope,
            field="extraction_scope",
            maximum_items=64,
            maximum_item_bytes=256,
        )
        if not isinstance(self.rights, RightsReference):
            raise SourceContractError("source rights reference must be typed")
        if self.roles != sorted_role_assignments(self.roles):
            raise SourceContractError("source roles must be canonically sorted")
        functions = typed_enum_tuple(
            self.portfolio_functions,
            enum_type=PortfolioFunction,
            field="portfolio_functions",
        )
        if functions != self.portfolio_functions:
            raise SourceContractError(
                "portfolio functions must be canonically sorted"
            )
        if self.coverage_mappings != sorted_coverage_mappings(
            self.coverage_mappings
        ):
            raise SourceContractError(
                "coverage mappings must be canonically sorted"
            )
        if self.dependencies != sorted_dependencies(self.dependencies):
            raise SourceContractError(
                "source dependencies must be canonically sorted"
            )
        if self.explicit_gaps != sorted_source_gaps(self.explicit_gaps):
            raise SourceContractError("source gaps must be canonically sorted")
        if not isinstance(self.observation_model, ObservationModel):
            raise SourceContractError("observation model must be typed")
        if not isinstance(self.baseline_policy, BaselinePolicy):
            raise SourceContractError("baseline policy must be typed")
        for value, field in (
            (self.item_identity_policy, "item_identity_policy"),
            (self.revision_policy, "revision_policy"),
            (self.canonicalization_policy, "canonicalization_policy"),
        ):
            require_versioned_ref(value, field=field)
        if not isinstance(self.lifecycle_stage, SourceLifecycleStage):
            raise SourceContractError("source lifecycle stage must be typed")
        bounded_text(
            self.change_reason,
            field="source_version_change_reason",
            maximum_bytes=2048,
        )
        require_idempotency_key(self.idempotency_key)
        if self.execution_authority != EXECUTION_AUTHORITY_DISABLED:
            raise SourceContractError(
                "Increment 3A source versions cannot carry execution authority"
            )
        self._validate_semantic_contract()

    def _validate_semantic_contract(self) -> None:
        functions = set(self.portfolio_functions)
        roles = {item.role for item in self.roles}
        if SourceRole.MANUAL_EDITOR_READER_LEAD in roles:
            if PortfolioFunction.MANUAL_ONLY not in functions:
                raise SourceContractError(
                    "manual lead source requires MANUAL_ONLY portfolio function"
                )
        if PortfolioFunction.MANUAL_ONLY in functions and (
            roles != {SourceRole.MANUAL_EDITOR_READER_LEAD}
        ):
            raise SourceContractError(
                "MANUAL_ONLY cannot silently apply to automated source roles"
            )
        if self.observation_model is ObservationModel.PLANNED_AGENDA:
            if SourceRole.PLANNED_AGENDA not in roles:
                raise SourceContractError(
                    "Planned Agenda observation requires the Planned Agenda role"
                )
            if (
                self.baseline_policy.kind
                is not BaselinePolicyKind.PLANNED_AGENDA_FUTURE_ONLY
            ):
                raise SourceContractError(
                    "Planned Agenda observation requires a future-only baseline"
                )
        elif SourceRole.PLANNED_AGENDA in roles:
            raise SourceContractError(
                "Planned Agenda role requires the Planned Agenda observation model"
            )
        baseline_by_model = {
            ObservationModel.MUTABLE_ITEM: {
                BaselinePolicyKind.MAINTAINED_DOCUMENT,
            },
            ObservationModel.APPEND_ONLY: {
                BaselinePolicyKind.BOUNDED_BACKFILL,
            },
            ObservationModel.ROLLING_LIST: {
                BaselinePolicyKind.BOUNDED_BACKFILL,
            },
            ObservationModel.COMPLETE_CURRENT_STATE: {
                BaselinePolicyKind.COMPLETE_STATE_FIRST_OBSERVED_ACTIVE,
            },
            ObservationModel.EXPLICIT_DELTA: {
                BaselinePolicyKind.EXPLICIT_DELTA_SEQUENCE,
                BaselinePolicyKind.MANUAL_ONLY,
            },
            ObservationModel.PLANNED_AGENDA: {
                BaselinePolicyKind.PLANNED_AGENDA_FUTURE_ONLY,
            },
        }
        if self.baseline_policy.kind not in baseline_by_model[self.observation_model]:
            raise SourceContractError(
                "baseline policy is incompatible with the observation model"
            )
        active = [
            item
            for item in self.coverage_mappings
            if item.responsibility is CoverageResponsibility.ACTIVE
        ]
        if active and functions <= {PortfolioFunction.COMPARATOR}:
            raise SourceContractError(
                "Comparator-only source cannot claim an Active detection path"
            )
        if any(
            item.contribution is CoverageContribution.COMPARATOR
            for item in active
        ):
            raise SourceContractError(
                "Comparator mapping cannot claim Active coverage"
            )
        gap_ids = {item.gap_id for item in self.explicit_gaps}
        for mapping in self.coverage_mappings:
            if (
                mapping.responsibility
                is CoverageResponsibility.EXPLICIT_DEFERRED_GAP
                and mapping.explicit_gap_id not in gap_ids
            ):
                raise SourceContractError(
                    "deferred mapping must resolve to a retained explicit gap"
                )
        dependency_ids = {item.dependency_id for item in self.dependencies}
        if len(dependency_ids) != len(self.dependencies):
            raise SourceContractError("source dependency identities are duplicated")

    def canonical_value(self) -> dict[str, object]:
        return {
            "version_id": str(self.version_id),
            "definition_id": str(self.definition_id),
            "version_number": self.version_number,
            "expected_previous_version_id": (
                None
                if self.expected_previous_version_id is None
                else str(self.expected_previous_version_id)
            ),
            "locator": self.locator,
            "adapter_contract": self.adapter_contract.canonical_value(),
            "extraction_scope": list(self.extraction_scope),
            "rights": self.rights.canonical_value(),
            "roles": [item.canonical_value() for item in self.roles],
            "portfolio_functions": [
                item.value for item in self.portfolio_functions
            ],
            "coverage_mappings": [
                item.canonical_value() for item in self.coverage_mappings
            ],
            "dependencies": [
                item.canonical_value() for item in self.dependencies
            ],
            "explicit_gaps": [
                item.canonical_value() for item in self.explicit_gaps
            ],
            "observation_model": self.observation_model.value,
            "baseline_policy": self.baseline_policy.canonical_value(),
            "item_identity_policy": self.item_identity_policy.canonical_value(),
            "revision_policy": self.revision_policy.canonical_value(),
            "canonicalization_policy": (
                self.canonicalization_policy.canonical_value()
            ),
            "lifecycle_stage": self.lifecycle_stage.value,
            "change_reason": self.change_reason,
            "execution_authority": self.execution_authority,
        }

    def semantic_value(self) -> dict[str, object]:
        value = self.canonical_value()
        for field in (
            "version_id",
            "version_number",
            "expected_previous_version_id",
            "change_reason",
        ):
            value.pop(field)
        return value

    @property
    def canonical_bytes(self) -> bytes:
        return canonical_json_bytes(self.canonical_value())

    @property
    def digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def semantic_digest(self) -> str:
        return digest_canonical(self.semantic_value())

    @property
    def locator_digest(self) -> str:
        return digest_canonical(
            {
                "definition_id": str(self.definition_id),
                "locator": self.locator,
            }
        )


__all__ = ["SourceDefinitionRequest", "SourceDefinitionVersionRequest"]
