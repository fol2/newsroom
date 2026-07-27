from __future__ import annotations

from typing import Any

from newsroom.authority.canonical import canonical_json_bytes

from ._payload_common import (
    _enum,
    _error,
    _exact,
    _policy_ref,
    _scope,
    _strings,
    _text,
    _token,
    _uuid,
)
from .types import (
    BaselinePolicyKind,
    CoverageContribution,
    CoverageResponsibility,
    EXECUTION_AUTHORITY_DISABLED,
    ObservationModel,
    PortfolioFunction,
    SourceDependencyKind,
    SourceLifecycleStage,
    SourceRole,
)


def _definition_payload(value: Any) -> bytes:
    item = _exact(
        value,
        fields=frozenset({"definition_id", "name", "editorial_purpose"}),
        name="source definition",
    )
    _uuid(item["definition_id"], field="definition_id")
    _text(item["name"], field="source_name", maximum_bytes=512)
    _text(
        item["editorial_purpose"],
        field="editorial_purpose",
        maximum_bytes=4096,
    )
    return canonical_json_bytes(item)


def _version_payload(value: Any) -> bytes:
    fields = frozenset(
        {
            "version_id",
            "definition_id",
            "version_number",
            "expected_previous_version_id",
            "locator",
            "adapter_contract",
            "extraction_scope",
            "rights",
            "roles",
            "portfolio_functions",
            "coverage_mappings",
            "dependencies",
            "explicit_gaps",
            "observation_model",
            "baseline_policy",
            "item_identity_policy",
            "revision_policy",
            "canonicalization_policy",
            "lifecycle_stage",
            "change_reason",
            "execution_authority",
        }
    )
    item = _exact(value, fields=fields, name="source definition version")
    _uuid(item["version_id"], field="version_id")
    _uuid(item["definition_id"], field="definition_id")
    version_number = item["version_number"]
    if (
        isinstance(version_number, bool)
        or not isinstance(version_number, int)
        or version_number <= 0
    ):
        raise _error("version_number must be positive")
    previous = item["expected_previous_version_id"]
    if version_number == 1:
        if previous is not None:
            raise _error("initial source version cannot name a predecessor")
    else:
        _uuid(previous, field="expected_previous_version_id")
    _text(item["locator"], field="locator", maximum_bytes=8192)
    _policy_ref(item["adapter_contract"], field="adapter_contract")
    _strings(
        item["extraction_scope"],
        field="extraction_scope",
        maximum_items=64,
        maximum_item_bytes=256,
    )
    rights = _exact(
        item["rights"],
        fields=frozenset(
            {
                "rights_decision_id",
                "rights_policy_version",
                "allowed_use",
                "retention_scope",
            }
        ),
        name="source rights",
    )
    _uuid(rights["rights_decision_id"], field="rights_decision_id")
    _token(rights["rights_policy_version"], field="rights_policy_version")
    _scope(rights["allowed_use"], field="allowed_use")
    _scope(rights["retention_scope"], field="retention_scope")

    roles = item["roles"]
    if not isinstance(roles, list) or not roles or len(roles) > len(SourceRole):
        raise _error("source roles must be a bounded non-empty list")
    role_values: list[str] = []
    for role in roles:
        role_item = _exact(
            role,
            fields=frozenset({"role", "purpose", "limitations"}),
            name="source role",
        )
        role_values.append(
            _enum(role_item["role"], enum_type=SourceRole, field="role")
        )
        _text(role_item["purpose"], field="role.purpose", maximum_bytes=2048)
        _strings(
            role_item["limitations"],
            field="role.limitations",
            maximum_items=16,
            allow_empty=True,
        )
    if role_values != sorted(set(role_values)):
        raise _error("source roles must be sorted and unique")

    functions = item["portfolio_functions"]
    if (
        not isinstance(functions, list)
        or not functions
        or len(functions) > len(PortfolioFunction)
    ):
        raise _error("portfolio functions must be bounded and non-empty")
    function_values = [
        _enum(value, enum_type=PortfolioFunction, field="portfolio_function")
        for value in functions
    ]
    if function_values != sorted(set(function_values)):
        raise _error("portfolio functions must be sorted and unique")

    mappings = item["coverage_mappings"]
    if not isinstance(mappings, list) or not mappings or len(mappings) > 128:
        raise _error("coverage mappings must be bounded and non-empty")
    mapping_keys: list[tuple[str, str, str]] = []
    mapped_gap_ids: set[str] = set()
    for mapping in mappings:
        mapping_item = _exact(
            mapping,
            fields=frozenset(
                {
                    "obligation_id",
                    "responsibility",
                    "contribution",
                    "geographies",
                    "languages",
                    "limitations",
                    "explicit_gap_id",
                }
            ),
            name="coverage mapping",
        )
        obligation = _token(
            mapping_item["obligation_id"], field="obligation_id"
        )
        responsibility = _enum(
            mapping_item["responsibility"],
            enum_type=CoverageResponsibility,
            field="coverage_responsibility",
        )
        contribution = _enum(
            mapping_item["contribution"],
            enum_type=CoverageContribution,
            field="coverage_contribution",
        )
        _strings(
            mapping_item["geographies"],
            field="coverage_geographies",
            maximum_items=16,
            maximum_item_bytes=64,
        )
        _strings(
            mapping_item["languages"],
            field="coverage_languages",
            maximum_items=16,
            maximum_item_bytes=64,
        )
        _strings(
            mapping_item["limitations"],
            field="coverage_limitations",
            maximum_items=16,
            allow_empty=True,
        )
        gap = mapping_item["explicit_gap_id"]
        if responsibility == CoverageResponsibility.EXPLICIT_DEFERRED_GAP.value:
            mapped_gap_ids.add(_token(gap, field="explicit_gap_id"))
        elif gap is not None:
            raise _error("only deferred coverage may name an explicit gap")
        mapping_keys.append((obligation, responsibility, contribution))
    if mapping_keys != sorted(set(mapping_keys)):
        raise _error("coverage mappings must be sorted and unique")

    dependencies = item["dependencies"]
    if not isinstance(dependencies, list) or len(dependencies) > 128:
        raise _error("source dependencies must be bounded")
    dependency_ids: list[str] = []
    for dependency in dependencies:
        dep = _exact(
            dependency,
            fields=frozenset(
                {
                    "dependency_id",
                    "kind",
                    "description",
                    "upstream_source_definition_id",
                }
            ),
            name="source dependency",
        )
        dependency_ids.append(
            _token(dep["dependency_id"], field="dependency_id")
        )
        _enum(
            dep["kind"],
            enum_type=SourceDependencyKind,
            field="dependency_kind",
        )
        _text(
            dep["description"],
            field="dependency_description",
            maximum_bytes=2048,
        )
        _uuid(
            dep["upstream_source_definition_id"],
            field="upstream_source_definition_id",
            optional=True,
        )
    if dependency_ids != sorted(set(dependency_ids)):
        raise _error("source dependencies must be sorted and unique")

    gaps = item["explicit_gaps"]
    if not isinstance(gaps, list) or len(gaps) > 128:
        raise _error("source gaps must be bounded")
    gap_ids: list[str] = []
    for gap in gaps:
        gap_item = _exact(
            gap,
            fields=frozenset(
                {"gap_id", "gap_class", "description", "launch_blocking"}
            ),
            name="source gap",
        )
        gap_ids.append(_token(gap_item["gap_id"], field="gap_id"))
        _token(gap_item["gap_class"], field="gap_class")
        _text(
            gap_item["description"],
            field="gap_description",
            maximum_bytes=2048,
        )
        if not isinstance(gap_item["launch_blocking"], bool):
            raise _error("source gap launch_blocking must be boolean")
    if gap_ids != sorted(set(gap_ids)):
        raise _error("source gaps must be sorted and unique")
    if not mapped_gap_ids.issubset(set(gap_ids)):
        raise _error("deferred coverage must resolve to a retained explicit gap")

    observation = _enum(
        item["observation_model"],
        enum_type=ObservationModel,
        field="observation_model",
    )
    baseline = _exact(
        item["baseline_policy"],
        fields=frozenset(
            {
                "reference",
                "kind",
                "freshness_window_seconds",
                "reset_requires_decision",
                "notes",
            }
        ),
        name="baseline policy",
    )
    _policy_ref(baseline["reference"], field="baseline.reference")
    baseline_kind = _enum(
        baseline["kind"],
        enum_type=BaselinePolicyKind,
        field="baseline.kind",
    )
    freshness = baseline["freshness_window_seconds"]
    if baseline_kind == BaselinePolicyKind.BOUNDED_BACKFILL.value:
        if (
            isinstance(freshness, bool)
            or not isinstance(freshness, int)
            or freshness <= 0
        ):
            raise _error("bounded baseline requires positive freshness")
    elif freshness is not None:
        raise _error("non-bounded baseline cannot carry freshness")
    if not isinstance(baseline["reset_requires_decision"], bool):
        raise _error("baseline reset flag must be boolean")
    _text(
        baseline["notes"],
        field="baseline.notes",
        maximum_bytes=2048,
        allow_empty=True,
    )
    for field in (
        "item_identity_policy",
        "revision_policy",
        "canonicalization_policy",
    ):
        _policy_ref(item[field], field=field)
    _enum(
        item["lifecycle_stage"],
        enum_type=SourceLifecycleStage,
        field="lifecycle_stage",
    )
    _text(item["change_reason"], field="change_reason", maximum_bytes=2048)
    if item["execution_authority"] != EXECUTION_AUTHORITY_DISABLED:
        raise _error("source execution authority is not allowed in Increment 3A")
    if (
        observation == ObservationModel.PLANNED_AGENDA.value
        and baseline_kind
        != BaselinePolicyKind.PLANNED_AGENDA_FUTURE_ONLY.value
    ):
        raise _error("Planned Agenda requires future-only baseline")
    return canonical_json_bytes(item)


__all__ = ["_definition_payload", "_version_payload"]
