from __future__ import annotations

from copy import deepcopy
from dataclasses import dataclass
from pathlib import Path, PurePosixPath
from types import MappingProxyType
from typing import Any, Mapping

from jsonschema import Draft202012Validator, FormatChecker

from .packages import parse_json_bytes


_PACKAGE_ROOT = Path(__file__).resolve().parent.parent
_POLICY_PATH = _PACKAGE_ROOT / "policies" / "editorial_shadow_v1.json"
_SCHEMA_PATH = _PACKAGE_ROOT / "schemas" / "editorial_policy_v1.schema.json"
_MAX_POLICY_BYTES = 1_048_576


class PolicyValidationError(ValueError):
    """Raised when the checked-in shadow authority is absent or inconsistent."""


@dataclass(frozen=True, slots=True)
class GatePolicy:
    gate_id: str
    source: str
    reject_reason: str
    hold_reason: str
    missing_reason: str
    unknown_reason: str
    indeterminate_reason: str


@dataclass(frozen=True, slots=True)
class RootPolicy:
    root_id: str
    base: str
    relative_path: str


@dataclass(frozen=True, slots=True)
class ResourceLimits:
    max_input_bytes: int
    max_package_bytes: int
    max_database_bytes: int
    min_free_bytes: int
    wal_autocheckpoint_pages: int
    busy_timeout_ms: int


@dataclass(frozen=True, slots=True)
class EditorialPolicy:
    policy_id: str
    component_versions: Mapping[str, str]
    target_allowlist: tuple[str, ...]
    outcome_precedence: tuple[str, ...]
    status_outcomes: Mapping[str, str]
    gates: tuple[GatePolicy, ...]
    reason_order: tuple[str, ...]
    trusted_input_roots: tuple[RootPolicy, ...]
    state_root: RootPolicy
    limits: ResourceLimits
    specification_trace: tuple[tuple[str, str], ...]
    _raw: dict[str, Any]

    @property
    def raw(self) -> dict[str, Any]:
        return deepcopy(self._raw)


def _load_schema() -> dict[str, Any]:
    value = parse_json_bytes(_SCHEMA_PATH.read_bytes(), max_bytes=_MAX_POLICY_BYTES)
    if not isinstance(value, dict):
        raise RuntimeError("Editorial policy schema root must be an object")
    Draft202012Validator.check_schema(value)
    return value


_POLICY_SCHEMA = _load_schema()


def _validate_relative_path(value: str, *, field: str) -> None:
    path = PurePosixPath(value)
    if path.is_absolute() or value in {"", "."} or ".." in path.parts:
        raise PolicyValidationError(f"{field} must be a contained relative path")


def _require_unique(values: list[str], *, field: str) -> None:
    if len(values) != len(set(values)):
        raise PolicyValidationError(f"duplicate {field}")


def validate_policy(value: Mapping[str, Any]) -> EditorialPolicy:
    raw = deepcopy(dict(value))
    validator = Draft202012Validator(_POLICY_SCHEMA, format_checker=FormatChecker())
    errors = sorted(validator.iter_errors(raw), key=lambda error: list(error.absolute_path))
    if errors:
        details = "; ".join(
            (
                f"{'/'.join(str(part) for part in error.absolute_path) or '$'}: duplicate item"
                if error.validator == "uniqueItems"
                else f"{'/'.join(str(part) for part in error.absolute_path) or '$'}: {error.message}"
            )
            for error in errors
        )
        raise PolicyValidationError(details)

    gate_values = list(raw["gates"])
    gate_ids = [str(gate["id"]) for gate in gate_values]
    root_values = list(raw["trusted_input_roots"])
    root_ids = [str(root["id"]) for root in root_values]
    reasons = [str(reason) for reason in raw["reason_order"]]
    trace_values = list(raw["specification_trace"])
    trace_ids = [str(item["id"]) for item in trace_values]
    _require_unique(gate_ids, field="gate id")
    _require_unique(root_ids, field="trusted-root id")
    _require_unique(reasons, field="reason code")
    _require_unique(trace_ids, field="trace id")

    reason_set = set(reasons)
    for gate in gate_values:
        for field in (
            "reject_reason",
            "hold_reason",
            "missing_reason",
            "unknown_reason",
            "indeterminate_reason",
        ):
            if gate[field] not in reason_set:
                raise PolicyValidationError(
                    f"gate {gate['id']} references reason absent from reason_order: {gate[field]}"
                )

    for root in root_values:
        _validate_relative_path(str(root["relative_path"]), field=f"root {root['id']}")
    state_value = dict(raw["state_root"])
    _validate_relative_path(str(state_value["relative_path"]), field="state root")

    component_versions = dict(raw["component_versions"])
    if component_versions["policy"] != raw["policy_id"]:
        raise PolicyValidationError("component policy version must equal policy_id")

    required_reason_codes = {
        "MIGRATION_MISSING_STABLE_STORY_ID",
        "UNKNOWN_TARGET",
        "UNKNOWN_POLICY_INPUT",
        "MISSING_PUBLICATION_CONTENT",
    }
    if not required_reason_codes.issubset(reason_set):
        raise PolicyValidationError("reason_order omits mandatory controller reason codes")

    gates = tuple(
        GatePolicy(
            gate_id=str(gate["id"]),
            source=str(gate["source"]),
            reject_reason=str(gate["reject_reason"]),
            hold_reason=str(gate["hold_reason"]),
            missing_reason=str(gate["missing_reason"]),
            unknown_reason=str(gate["unknown_reason"]),
            indeterminate_reason=str(gate["indeterminate_reason"]),
        )
        for gate in gate_values
    )
    roots = tuple(
        RootPolicy(
            root_id=str(root["id"]),
            base=str(root["base"]),
            relative_path=str(root["relative_path"]),
        )
        for root in root_values
    )
    limits = dict(raw["limits"])
    return EditorialPolicy(
        policy_id=str(raw["policy_id"]),
        component_versions=MappingProxyType(component_versions),
        target_allowlist=tuple(str(item) for item in raw["target_allowlist"]),
        outcome_precedence=tuple(str(item) for item in raw["outcome_precedence"]),
        status_outcomes=MappingProxyType(
            {str(key): str(item) for key, item in raw["status_outcomes"].items()}
        ),
        gates=gates,
        reason_order=tuple(reasons),
        trusted_input_roots=roots,
        state_root=RootPolicy(
            root_id=str(state_value["id"]),
            base=str(state_value["base"]),
            relative_path=str(state_value["relative_path"]),
        ),
        limits=ResourceLimits(
            max_input_bytes=int(limits["max_input_bytes"]),
            max_package_bytes=int(limits["max_package_bytes"]),
            max_database_bytes=int(limits["max_database_bytes"]),
            min_free_bytes=int(limits["min_free_bytes"]),
            wal_autocheckpoint_pages=int(limits["wal_autocheckpoint_pages"]),
            busy_timeout_ms=int(limits["busy_timeout_ms"]),
        ),
        specification_trace=tuple(
            (str(item["id"]), str(item["status"])) for item in trace_values
        ),
        _raw=raw,
    )


def load_shadow_policy() -> EditorialPolicy:
    """Load the sole checked-in shadow policy; no external path is accepted."""

    value = parse_json_bytes(_POLICY_PATH.read_bytes(), max_bytes=_MAX_POLICY_BYTES)
    if not isinstance(value, dict):
        raise PolicyValidationError("editorial policy root must be an object")
    return validate_policy(value)
