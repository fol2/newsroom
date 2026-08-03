#!/usr/bin/env python3
"""Materialize the exact expanded Increment 5 qualification scope on staging.

This helper is intentionally staging-only. It rewrites the complete digest chain
from reviewed source bytes and records every changed path. The final PR commit is
created separately from the fixed base and does not include this helper.
"""

from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess
from typing import Any


ROOT = Path(__file__).resolve().parents[2]
BASE = "3ea1874de5e1bd6c622a3760eabb74adfe75d169"
OLD_SCOPE = "RETRIEVER_INDEX_HYDRATION_AND_DEGRADATION_ONLY"
NEW_SCOPE = (
    "RETRIEVER_INDEX_FUSION_DEDUPLICATION_HYDRATION_DEGRADATION_"
    "AND_RECOVERY_ONLY"
)

DATA = ROOT / "newsroom/increment5/data"
QUAL_STRUCTURAL = DATA / "increment5_qualification_profile_structural_v1.schema.json"
FIXTURE_PUBLIC = DATA / "increment5_fixture_replay_profile_v1.schema.json"
QUAL_PUBLIC = DATA / "increment5_qualification_profile_v1.schema.json"
CONTRACT = DATA / "increment5a_retrieval_contract_v1.json"
PLAN = DATA / "increment5_retrieval_evaluation_plan_v1.json"
PROFILE_TEST = ROOT / "newsroom/tests/test_increment5a_profiles.py"
OUTPUT = ROOT / "increment5a-scope-digests.json"


def canonical(value: Any) -> bytes:
    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8", errors="strict")


def digest(raw: bytes) -> str:
    return "sha256:" + hashlib.sha256(raw).hexdigest()


def read_canonical(path: Path) -> tuple[Any, bytes]:
    raw = path.read_bytes()
    value = json.loads(raw.decode("utf-8", errors="strict"))
    if canonical(value) != raw:
        raise RuntimeError(f"non-canonical source JSON: {path}")
    return value, raw


def write_canonical(path: Path, value: Any) -> bytes:
    raw = canonical(value)
    path.write_bytes(raw)
    return raw


def replace_exact(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count == 0:
        raise RuntimeError(f"missing replacement target {label}: {old}")
    return text.replace(old, new)


def changed_paths(source_head: str) -> list[Path]:
    output = subprocess.check_output(
        ["git", "diff", "--name-only", BASE, source_head],
        cwd=ROOT,
        text=True,
    )
    return [ROOT / item for item in output.splitlines() if item]


def main() -> None:
    source_head = "40d387840ee6d2b41042b32191a962ae9baf9502"
    if source_head != "40d387840ee6d2b41042b32191a962ae9baf9502":
        raise RuntimeError(f"unexpected source head: {source_head}")

    qstruct, old_qstruct_raw = read_canonical(QUAL_STRUCTURAL)
    fixture_public, old_fixture_public_raw = read_canonical(FIXTURE_PUBLIC)
    qualification_public, old_qualification_public_raw = read_canonical(QUAL_PUBLIC)
    contract, old_contract_raw = read_canonical(CONTRACT)
    plan, old_plan_raw = read_canonical(PLAN)

    old_qstruct_digest = digest(old_qstruct_raw)
    old_fixture_public_digest = digest(old_fixture_public_raw)
    old_qualification_public_digest = digest(old_qualification_public_raw)
    old_contract_digest = digest(old_contract_raw)
    old_plan_digest = digest(old_plan_raw)

    current_scope = qstruct["properties"]["expected_outcome_scope"]["const"]
    if current_scope != OLD_SCOPE:
        raise RuntimeError(f"unexpected structural scope: {current_scope}")
    qstruct["properties"]["expected_outcome_scope"]["const"] = NEW_SCOPE
    new_qstruct_raw = write_canonical(QUAL_STRUCTURAL, qstruct)
    new_qstruct_digest = digest(new_qstruct_raw)

    payload = contract["payload"]
    profile_digests = payload["profile_schema_digests"]
    if profile_digests["PRODUCTION_SHAPED_QUALIFICATION"] != old_qstruct_digest:
        raise RuntimeError("contract does not bind the source qualification schema")
    profile_digests["PRODUCTION_SHAPED_QUALIFICATION"] = new_qstruct_digest
    contract["payload_digest"] = digest(canonical(payload))
    new_contract_raw = write_canonical(CONTRACT, contract)
    new_contract_digest = digest(new_contract_raw)

    fixture_contract = fixture_public["properties"]["contract_digest"]
    qualification_contract = qualification_public["properties"]["contract_digest"]
    if fixture_contract != {"const": old_contract_digest}:
        raise RuntimeError("fixture public schema contract binding differs")
    if qualification_contract != {"const": old_contract_digest}:
        raise RuntimeError("qualification public schema contract binding differs")
    if (
        qualification_public["properties"]["expected_outcome_scope"]["const"]
        != OLD_SCOPE
    ):
        raise RuntimeError("qualification public schema scope differs")

    fixture_public["properties"]["contract_digest"] = {"const": new_contract_digest}
    qualification_public["properties"]["contract_digest"] = {
        "const": new_contract_digest
    }
    qualification_public["properties"]["expected_outcome_scope"]["const"] = NEW_SCOPE
    new_fixture_public_raw = write_canonical(FIXTURE_PUBLIC, fixture_public)
    new_qualification_public_raw = write_canonical(QUAL_PUBLIC, qualification_public)
    new_fixture_public_digest = digest(new_fixture_public_raw)
    new_qualification_public_digest = digest(new_qualification_public_raw)

    if plan["contract_digest"] != old_contract_digest:
        raise RuntimeError("evaluation Plan does not bind the source contract")
    plan["contract_digest"] = new_contract_digest
    new_plan_raw = write_canonical(PLAN, plan)
    new_plan_digest = digest(new_plan_raw)

    replacements = {
        OLD_SCOPE: NEW_SCOPE,
        old_qstruct_digest: new_qstruct_digest,
        old_fixture_public_digest: new_fixture_public_digest,
        old_qualification_public_digest: new_qualification_public_digest,
        old_contract_digest: new_contract_digest,
        old_plan_digest: new_plan_digest,
    }

    generated_json = {
        QUAL_STRUCTURAL.resolve(),
        FIXTURE_PUBLIC.resolve(),
        QUAL_PUBLIC.resolve(),
        CONTRACT.resolve(),
        PLAN.resolve(),
    }
    updated_paths: set[Path] = set(generated_json)
    for path in changed_paths(source_head):
        if not path.is_file() or path.resolve() in generated_json:
            continue
        try:
            text = path.read_text(encoding="utf-8")
        except UnicodeDecodeError:
            continue
        updated = text
        for old, new in replacements.items():
            updated = updated.replace(old, new)
        if updated != text:
            path.write_text(updated, encoding="utf-8")
            updated_paths.add(path.resolve())

    test_text = PROFILE_TEST.read_text(encoding="utf-8")
    marker = "def test_qualification_scope_is_complete_and_cannot_shrink() -> None:"
    if marker not in test_text:
        addition = f'''\n\n{marker}\n    expected = "{NEW_SCOPE}"\n    structural = _schema(QUALIFICATION_PROFILE_STRUCTURAL_SCHEMA_PATH)\n    public = _schema(QUALIFICATION_PROFILE_SCHEMA_PATH)\n    assert structural["properties"]["expected_outcome_scope"] == {{"const": expected}}\n    assert public["properties"]["expected_outcome_scope"] == {{"const": expected}}\n\n    manifest = build_qualification_manifest(\n        dataset_id="increment5-rights-cleared-v1",\n        dataset_manifest_digest=_DIGEST_A,\n    )\n    assert manifest["expected_outcome_scope"] == expected\n    assert all(\n        surface in expected\n        for surface in (\n            "FUSION",\n            "DEDUPLICATION",\n            "HYDRATION",\n            "DEGRADATION",\n            "RECOVERY",\n        )\n    )\n\n    narrowed = deepcopy(manifest)\n    narrowed["expected_outcome_scope"] = "{OLD_SCOPE}"\n    with pytest.raises(Increment5ProfileError, match="schema validation failed"):\n        profiles._check_profile_manifest(narrowed)\n'''
        PROFILE_TEST.write_text(test_text.rstrip() + addition, encoding="utf-8")
        updated_paths.add(PROFILE_TEST.resolve())

    required_surfaces = ("FUSION", "DEDUPLICATION", "HYDRATION", "DEGRADATION", "RECOVERY")
    for surface in required_surfaces:
        if surface not in NEW_SCOPE:
            raise RuntimeError(f"qualification scope omits {surface}")

    remaining: dict[str, list[str]] = {}
    for old in replacements:
        hits: list[str] = []
        for path in changed_paths(source_head):
            if not path.is_file():
                continue
            try:
                text = path.read_text(encoding="utf-8")
            except UnicodeDecodeError:
                continue
            if (
                old == OLD_SCOPE
                and path.resolve() == PROFILE_TEST.resolve()
                and text.count(old) == 1
            ):
                continue
            if old in text:
                hits.append(str(path.relative_to(ROOT)))
        if hits:
            remaining[old] = hits
    if remaining:
        raise RuntimeError(f"stale pre-replacement identities remain: {remaining}")

    result = {
        "schema_version": "newsroom.increment5a.scope-replacement.v1",
        "source_head": source_head,
        "old_scope": OLD_SCOPE,
        "new_scope": NEW_SCOPE,
        "old": {
            "qualification_structural_schema": old_qstruct_digest,
            "fixture_public_schema": old_fixture_public_digest,
            "qualification_public_schema": old_qualification_public_digest,
            "contract": old_contract_digest,
            "evaluation_plan": old_plan_digest,
        },
        "new": {
            "qualification_structural_schema": new_qstruct_digest,
            "fixture_public_schema": new_fixture_public_digest,
            "qualification_public_schema": new_qualification_public_digest,
            "contract": new_contract_digest,
            "contract_payload": contract["payload_digest"],
            "evaluation_plan": new_plan_digest,
        },
        "changed_paths": sorted(
            str(path.relative_to(ROOT)) for path in updated_paths
        ),
    }
    OUTPUT.write_bytes(canonical(result))
    print(json.dumps(result, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
