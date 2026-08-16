from __future__ import annotations

import json
from collections.abc import Mapping
from pathlib import Path

import pytest

import newsroom.increment10.plan as module
from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment10 import INCREMENT_10_PLAN, PLAN_PATH, Increment10PlanError, load_plan


def _changed(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, document: object):
    raw = canonical_json_bytes(document)
    path = tmp_path / "changed.json"
    path.write_bytes(raw)
    monkeypatch.setattr(module, "EXPECTED_PLAN_DIGEST", digest_bytes(raw))
    return load_plan(path)


def test_plan_is_exact_canonical_content_addressed_and_immutable() -> None:
    plan = INCREMENT_10_PLAN
    assert PLAN_PATH.read_bytes() == canonical_json_bytes(json.loads(PLAN_PATH.read_bytes()))
    assert plan.plan_digest == digest_bytes(PLAN_PATH.read_bytes())
    assert plan.issue_number == 527
    assert isinstance(plan.approval, Mapping)
    with pytest.raises(TypeError):
        plan.approval["status"] = "CHANGED"  # type: ignore[index]
    with pytest.raises(TypeError):
        plan.owner_decisions[0]["selection"]["scope"]["denominator"] = 4  # type: ignore[index]


def test_all_owner_decisions_scope_and_zero_effect_boundary_are_frozen() -> None:
    plan = INCREMENT_10_PLAN
    assert tuple(item["decision_id"] for item in plan.owner_decisions) == tuple(f"I10-OD-{i:03d}" for i in range(1, 13))
    scope = plan.owner_decisions[0]["selection"]["scope"]
    assert scope["denominator"] == scope["exposure_min"] == scope["exposure_max"] == 3
    assert scope["destination"] == "local://increment10/evidence-intake-fixture-v1"
    assert all(value is False for value in plan.non_effects.values())
    assert plan.permits_runtime is False
    assert plan.permits_contract_implementation is False


def test_dependency_waves_and_single_writer_ownership_are_complete() -> None:
    graph = INCREMENT_10_PLAN.execution_graph
    assert graph["waves"] == ((528, 530, 534), (529,), (531,), (532,), (533,), (535,), (536,))
    allocations = graph["allocations"]
    assert tuple(item["issue_number"] for item in allocations) == tuple(range(528, 537))
    files = [path for item in allocations for path in item["file_ownership"]]
    assert len(files) == len(set(files))


@pytest.mark.parametrize("field", tuple(module.EXPECTED_SECTION_DIGESTS))
def test_material_section_tamper_fails_even_when_outer_digest_is_repinned(tmp_path: Path, monkeypatch: pytest.MonkeyPatch, field: str) -> None:
    document = json.loads(PLAN_PATH.read_bytes())
    value = document["payload"][field]
    if isinstance(value, list):
        value.append({})
    elif isinstance(value, dict):
        value["tamper"] = True
    with pytest.raises(Increment10PlanError, match=f"{field} reviewed bytes differ"):
        _changed(tmp_path, monkeypatch, document)


@pytest.mark.parametrize("raw", (b'{"schema_version":"x","schema_version":"y"}', b"[]", b"{", b"\xff"))
def test_malformed_documents_use_public_error(tmp_path: Path, raw: bytes) -> None:
    path = tmp_path / "bad.json"
    path.write_bytes(raw)
    with pytest.raises(Increment10PlanError):
        load_plan(path)
