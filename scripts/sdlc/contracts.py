from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
import tomllib
from typing import Any, Mapping


class ContractError(ValueError):
    """Raised when the accepted SDLC machine contract is inconsistent."""


_REQUIRED_PATH_GROUPS = frozenset(
    {
        "documentation",
        "local_code",
        "contract_control",
        "stateful_contract",
        "external_service_security",
        "release_operational",
        "clustering",
    }
)
_REQUIRED_RISKS = (
    "R0_DOCUMENTATION",
    "R1_LOCAL_CODE",
    "R2_STATEFUL_CONTRACT",
    "R3_EXTERNAL_SERVICE_SECURITY",
    "R4_RELEASE_OPERATIONAL",
)
_INTERACTIVE_LANES = frozenset({"core", "service", "merge_group"})


def _mapping(value: object, name: str) -> Mapping[str, Any]:
    if not isinstance(value, dict):
        raise ContractError(f"{name} must be a table")
    return value


def _positive_int(value: object, name: str, *, below: int | None = None) -> int:
    if isinstance(value, bool) or not isinstance(value, int) or value <= 0:
        raise ContractError(f"{name} must be a positive integer")
    if below is not None and value >= below:
        raise ContractError(f"{name} must be below {below}")
    return value


def _probability(value: object, name: str) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ContractError(f"{name} must be numeric")
    probability = float(value)
    if not 0.0 < probability <= 1.0:
        raise ContractError(f"{name} must be in (0, 1]")
    return probability


def _repository_file(root: Path, relative: str, *, label: str) -> Path:
    if not relative:
        raise ContractError(f"{label} path is required")
    lexical = Path(relative)
    if lexical.is_absolute() or any(part in {"", ".", ".."} for part in lexical.parts):
        raise ContractError(f"{label} path escapes the repository: {relative}")
    current = root
    for part in lexical.parts:
        current /= part
        if current.is_symlink():
            raise ContractError(f"{label} path is symlinked: {relative}")
    resolved = current.resolve()
    if not resolved.is_relative_to(root) or not resolved.is_file():
        raise ContractError(f"{label} file does not exist in repository: {relative}")
    return resolved


@dataclass(frozen=True)
class SdlcContract:
    repo_root: Path
    source_path: Path
    data: Mapping[str, Any]

    @property
    def contract_version(self) -> str:
        return str(self.data["contract_version"])

    @property
    def classifier_version(self) -> str:
        return str(self.classification["version"])

    @property
    def classification(self) -> Mapping[str, Any]:
        return _mapping(self.data["classification"], "classification")

    @property
    def path_groups(self) -> Mapping[str, tuple[str, ...]]:
        raw = _mapping(self.classification["paths"], "classification.paths")
        return {name: tuple(str(item) for item in values) for name, values in raw.items()}

    @property
    def risk_rank(self) -> Mapping[str, int]:
        raw = _mapping(self.data["risk"], "risk")
        return {
            name: int(_mapping(value, f"risk.{name}")["rank"])
            for name, value in raw.items()
        }

    @property
    def sentinels(self) -> tuple[str, ...]:
        raw = _mapping(self.data["sentinels"], "sentinels").get("current")
        if not isinstance(raw, list):
            raise ContractError("sentinels.current must be an array")
        return tuple(str(item) for item in raw)

    @property
    def unknown_path_risk(self) -> str:
        return str(self.classification["unknown_path"])

    def service_required(self, risk_tier: str) -> bool:
        risk = _mapping(
            _mapping(self.data["risk"], "risk")[risk_tier],
            f"risk.{risk_tier}",
        )
        return bool(risk["service"])

    def owner_authority_required(self, risk_tier: str) -> bool:
        risk = _mapping(
            _mapping(self.data["risk"], "risk")[risk_tier],
            f"risk.{risk_tier}",
        )
        return bool(risk.get("owner_authority_required", False))


def validate_contract_data(
    data: Mapping[str, Any], *, repo_root: Path | None = None
) -> None:
    if data.get("schema_version") != "newsroom.sdlc.gates.v1":
        raise ContractError("unsupported SDLC contract schema")
    if data.get("status") != "accepted":
        raise ContractError("SDLC contract is not accepted")
    if not isinstance(data.get("contract_version"), str) or not data["contract_version"]:
        raise ContractError("contract_version is required")

    global_config = _mapping(data.get("global"), "global")
    command_limit = _positive_int(
        global_config.get("gate_command_timeout_seconds"),
        "global.gate_command_timeout_seconds",
        below=60,
    )
    lane_limit = _positive_int(
        global_config.get("lane_execution_timeout_seconds"),
        "global.lane_execution_timeout_seconds",
        below=60,
    )
    finalization_limit = _positive_int(
        global_config.get("finalization_timeout_seconds"),
        "global.finalization_timeout_seconds",
        below=60,
    )
    if global_config.get("required_decision_always_reports") is not True:
        raise ContractError("the required decision must always report")
    if global_config.get("rerun_can_overwrite_required_result") is not False:
        raise ContractError("a rerun cannot overwrite the required result")

    lanes = _mapping(data.get("lanes"), "lanes")
    gates = _mapping(data.get("gate"), "gate")
    if not gates:
        raise ContractError("at least one gate is required")
    gate_ids: set[str] = set()
    for gate_name, gate_value in gates.items():
        gate = _mapping(gate_value, f"gate.{gate_name}")
        gate_id = gate.get("id")
        if not isinstance(gate_id, str) or not gate_id:
            raise ContractError(f"gate.{gate_name}.id is required")
        if gate_id in gate_ids:
            raise ContractError(f"duplicate gate id: {gate_id}")
        gate_ids.add(gate_id)
        if gate_id != gate_name and (gate_name, gate_id) != ("science-shard", "science-*"):
            raise ContractError(f"gate.{gate_name}.id differs from its table name")
        lane_name = gate.get("lane")
        if not isinstance(lane_name, str) or lane_name not in lanes:
            raise ContractError(
                f"gate.{gate_name}.lane does not resolve to lanes.{lane_name}"
            )
        timeout = _positive_int(
            gate.get("hard_timeout_seconds"),
            f"gate.{gate_name}.hard_timeout_seconds",
            below=60,
        )
        if timeout > command_limit:
            raise ContractError(f"gate.{gate_name} exceeds the global command timeout")

    for lane_name in _INTERACTIVE_LANES:
        lane = _mapping(lanes.get(lane_name), f"lanes.{lane_name}")
        timeout = _positive_int(
            lane.get("hard_timeout_seconds"),
            f"lanes.{lane_name}.hard_timeout_seconds",
            below=60,
        )
        if timeout > lane_limit:
            raise ContractError(f"lanes.{lane_name} exceeds the aggregate lane timeout")
    science = _mapping(lanes.get("science"), "lanes.science")
    _positive_int(
        science.get("per_shard_hard_timeout_seconds"),
        "lanes.science.per_shard_hard_timeout_seconds",
        below=60,
    )
    decision = _mapping(lanes.get("decision"), "lanes.decision")
    decision_timeout = _positive_int(
        decision.get("hard_timeout_seconds"),
        "lanes.decision.hard_timeout_seconds",
        below=60,
    )
    if decision.get("always_reports") is not True:
        raise ContractError("lanes.decision must always report")
    if decision_timeout > finalization_limit:
        raise ContractError("lanes.decision exceeds the finalization timeout")

    risks = _mapping(data.get("risk"), "risk")
    if set(risks) != set(_REQUIRED_RISKS):
        raise ContractError("risk contract must contain exactly R0 through R4")
    ranked = {
        name: int(_mapping(risks[name], f"risk.{name}")["rank"])
        for name in _REQUIRED_RISKS
    }
    if tuple(ranked[name] for name in _REQUIRED_RISKS) != tuple(range(5)):
        raise ContractError("risk ranks must be unique and ordered R0 through R4")
    for name in _REQUIRED_RISKS:
        risk = _mapping(risks[name], f"risk.{name}")
        if not isinstance(risk.get("core"), bool) or not isinstance(
            risk.get("service"), bool
        ):
            raise ContractError(f"risk.{name} must define core/service booleans")

    classification = _mapping(data.get("classification"), "classification")
    if classification.get("version") != "sdlc-risk-v1":
        raise ContractError("unsupported risk classifier version")
    for field in (
        "unknown_path",
        "unknown_dependency_edge",
        "classifier_error",
        "changed_gate_contract",
        "changed_workflow",
        "changed_dependency_or_lock",
        "changed_release_or_deployment",
    ):
        if classification.get(field) not in risks:
            raise ContractError(f"classification.{field} references an unknown risk")
    paths = _mapping(classification.get("paths"), "classification.paths")
    missing_groups = _REQUIRED_PATH_GROUPS - paths.keys()
    if missing_groups:
        raise ContractError(f"classification.paths lacks: {sorted(missing_groups)}")
    for group, patterns in paths.items():
        if not isinstance(patterns, list) or not patterns:
            raise ContractError(
                f"classification.paths.{group} must be a non-empty array"
            )
        if any(not isinstance(pattern, str) or not pattern for pattern in patterns):
            raise ContractError(
                f"classification.paths.{group} contains an invalid pattern"
            )

    strategy = _mapping(data.get("test_strategy"), "test_strategy")
    owner = _mapping(data.get("owner_decisions"), "owner_decisions")
    review = _mapping(data.get("change_review"), "change_review")
    if owner.get("review_net_executable_lines_trigger") != review.get(
        "net_executable_lines_trigger"
    ):
        raise ContractError("accepted executable-line trigger differs from change_review")
    if owner.get("review_changed_files_trigger") != review.get(
        "changed_files_trigger"
    ):
        raise ContractError("accepted changed-file trigger differs from change_review")
    for owner_key, strategy_key in (
        ("selector_shadow_calendar_days", "selector_shadow_calendar_days"),
        ("selector_shadow_minimum_changes", "selector_shadow_minimum_changes"),
        ("selector_known_failure_miss_limit", "selector_known_failure_miss_limit"),
        ("selector_mutation_recall_minimum", "selector_mutation_recall_minimum"),
    ):
        if owner.get(owner_key) != strategy.get(strategy_key):
            raise ContractError(f"accepted {owner_key} differs from test_strategy")
    _probability(
        owner.get("selector_mutation_recall_minimum"),
        "owner mutation recall",
    )
    if owner.get("prewarmed_runner_evaluation_permitted_after_measured_slo_failure") is not True:
        raise ContractError("accepted runner evaluation policy is missing")
    if owner.get("critical_main_failure_pauses_merges") is not True:
        raise ContractError("critical main failure must pause merges")
    for field in (
        "pr_evidence_retention_days",
        "main_evidence_retention_days",
        "release_evidence_retention_years",
    ):
        _positive_int(owner.get(field), f"owner_decisions.{field}")

    if repo_root is not None:
        root = repo_root.resolve()
        for label, relative in (
            ("specification", str(data.get("specification", ""))),
            ("acceptance record", str(data.get("acceptance_record", ""))),
            (
                "evidence schema",
                str(_mapping(data.get("evidence"), "evidence").get("schema", "")),
            ),
            (
                "route schema",
                str(
                    _mapping(data.get("evidence"), "evidence").get(
                        "route_schema", ""
                    )
                ),
            ),
        ):
            path = _repository_file(root, relative, label=label)
            if path.suffix == ".json":
                try:
                    json.loads(path.read_text(encoding="utf-8"))
                except json.JSONDecodeError as exc:
                    raise ContractError(f"invalid JSON contract: {relative}") from exc


def load_contract(
    repo_root: str | Path, contract_path: str | Path = ".sdlc/gates.toml"
) -> SdlcContract:
    root = Path(repo_root).resolve()
    source = _repository_file(root, str(contract_path), label="SDLC contract")
    try:
        data = tomllib.loads(source.read_text(encoding="utf-8"))
    except (OSError, tomllib.TOMLDecodeError) as exc:
        raise ContractError(f"cannot load SDLC contract: {source}") from exc
    validate_contract_data(data, repo_root=root)
    return SdlcContract(root, source, data)
