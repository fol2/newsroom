"""Load the exact reviewed Increment 5 retrieval evaluation plan."""

from __future__ import annotations

from collections.abc import Mapping
import json
from pathlib import Path
from typing import Any

from newsroom.authority.canonical import (
    CanonicalizationError,
    canonical_json_bytes,
    digest_bytes,
)

from .contract_types import Increment5ContractError, freeze
from .decision import INCREMENT_5A_CONTRACT


class Increment5EvaluationPlanError(ValueError):
    """The checked evaluation plan is not the reviewed v1 content."""


EVALUATION_PLAN_PATH = (
    Path(__file__).resolve().parent
    / "data"
    / "increment5_retrieval_evaluation_plan_v1.json"
)
EVALUATION_PLAN_DIGEST = (
    "sha256:6d52ea47056a8df4cd71213ae68c47471f7c2f546bd834053b27d747a0247c29"
)
MANDATORY_QUERY_FAMILY_IDS = (
    "EVENT_AND_DEVELOPMENT_PRECISION",
    "SOURCE_REVISION_IMPACT",
    "LONG_RUNNING_POLICY_CASE_OR_PROCESS_TIMELINE",
)
ZERO_TOLERANCE_GATE_NAMES = (
    "rebuild_reproducibility_mismatch_count",
    "temporal_correctness_error_count",
)


def _without_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:
    value: dict[str, Any] = {}
    for name, item in pairs:
        if name in value:
            raise Increment5EvaluationPlanError(f"duplicate object name: {name}")
        value[name] = item
    return value


def _thaw(value: Any) -> Any:
    if isinstance(value, Mapping):
        return {name: _thaw(item) for name, item in value.items()}
    if isinstance(value, tuple):
        return [_thaw(item) for item in value]
    return value


def load_increment5_evaluation_plan(path: Path) -> Mapping[str, Any]:
    """Return an immutable view only when bytes equal the reviewed v1 plan."""

    if not isinstance(path, Path):
        raise Increment5EvaluationPlanError("evaluation plan path must be a pathlib.Path")
    try:
        raw = path.read_bytes()
        record = json.loads(
            raw.decode("utf-8", errors="strict"),
            object_pairs_hook=_without_duplicate_names,
        )
        canonical = canonical_json_bytes(record)
    except (
        OSError,
        UnicodeError,
        json.JSONDecodeError,
        CanonicalizationError,
    ) as exc:
        raise Increment5EvaluationPlanError(
            "cannot read canonical Increment 5 evaluation plan"
        ) from exc
    if raw != canonical:
        raise Increment5EvaluationPlanError(
            "evaluation plan must use exact canonical JSON"
        )
    if digest_bytes(raw) != EVALUATION_PLAN_DIGEST:
        raise Increment5EvaluationPlanError(
            "evaluation plan bytes differ from reviewed v1"
        )
    if not isinstance(record, dict):
        raise Increment5EvaluationPlanError("evaluation plan must be an object")

    try:
        if (
            record["schema_version"]
            != "newsroom.increment5.retrieval-evaluation-plan.v1"
            or record["contract_digest"] != INCREMENT_5A_CONTRACT.contract_digest
            or record["contract_evaluation_summary"]
            != _thaw(INCREMENT_5A_CONTRACT.payload["evaluation_plan"])
        ):
            raise Increment5EvaluationPlanError(
                "evaluation plan differs from the reviewed contract summary"
            )

        families = record["mandatory_query_families"]
        if not isinstance(families, list) or tuple(
            family["family_id"] for family in families
        ) != MANDATORY_QUERY_FAMILY_IDS:
            raise Increment5EvaluationPlanError(
                "mandatory GraphRAG query families differ from reviewed v1"
            )
        if any(
            not family["required_case_types"]
            or not family["required_metrics"]
            or not family["required_slices"]
            for family in families
        ):
            raise Increment5EvaluationPlanError(
                "mandatory GraphRAG query family is incomplete"
            )

        gates = record["zero_tolerance_gates"]
        if not isinstance(gates, dict) or tuple(sorted(gates)) != tuple(
            sorted(ZERO_TOLERANCE_GATE_NAMES)
        ):
            raise Increment5EvaluationPlanError(
                "zero-tolerance gates differ from reviewed v1"
            )
        for name in ZERO_TOLERANCE_GATE_NAMES:
            gate = gates[name]
            if (
                not isinstance(gate, dict)
                or gate.get("blocking") is not True
                or gate.get("maximum") != 0
                or not gate.get("definition")
            ):
                raise Increment5EvaluationPlanError(
                    f"zero-tolerance gate is not blocking at zero: {name}"
                )
        if gates["temporal_correctness_error_count"].get("required_slice") != (
            "TEMPORAL_CUTOFF"
        ):
            raise Increment5EvaluationPlanError(
                "temporal correctness is not bound to TEMPORAL_CUTOFF"
            )
        if gates["rebuild_reproducibility_mismatch_count"].get(
            "required_experiment"
        ) != "RIGHTS_PURGE_AND_REBUILD":
            raise Increment5EvaluationPlanError(
                "rebuild reproducibility is not bound to rebuild qualification"
            )
    except (KeyError, TypeError) as exc:
        if isinstance(exc, Increment5EvaluationPlanError):
            raise
        raise Increment5EvaluationPlanError(
            "evaluation plan shape differs from reviewed v1"
        ) from exc

    return freeze(record)


try:
    INCREMENT_5_EVALUATION_PLAN = load_increment5_evaluation_plan(
        EVALUATION_PLAN_PATH
    )
except Increment5ContractError as exc:
    raise Increment5EvaluationPlanError(str(exc)) from exc
