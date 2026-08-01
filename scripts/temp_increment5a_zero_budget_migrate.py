from __future__ import annotations

import hashlib
import json
from pathlib import Path
import subprocess


OLD_SCHEMA_DIGEST = (
    "sha256:1dfdb4de6d2d184efb486d1601a3eb246f1d74352f55955a2b69e962336c31ef"
)
OLD_BODY_DIGEST = (
    "sha256:137f423d2630aec1af065968a6a0afac9283918fdad3f6e0631719f23b97952a"
)
_TEMPORARY_PATHS = {
    Path(".github/workflows/temp-increment5a-zero-budget-schema.yml"),
    Path(".github/workflows/temp-increment5a-zero-budget-pr.yml"),
    Path("scripts/temp_increment5a_zero_budget_migrate.py"),
}


def _tracked_files_with(text: str) -> list[Path]:
    result = subprocess.run(
        ("git", "grep", "-l", "--fixed-strings", text, "--"),
        check=False,
        capture_output=True,
        text=True,
    )
    if result.returncode not in (0, 1):
        raise SystemExit(result.stderr)
    return [
        path
        for item in result.stdout.splitlines()
        if item and (path := Path(item)) not in _TEMPORARY_PATHS
    ]


def _replace_tracked(old: str, new: str, *, label: str) -> None:
    paths = _tracked_files_with(old)
    if not paths:
        raise SystemExit(f"{label}: no tracked references")
    for path in paths:
        source = path.read_text(encoding="utf-8")
        path.write_text(source.replace(old, new), encoding="utf-8")


def _harden_profile_schema_code() -> None:
    path = Path("newsroom/increment5/profiles.py")
    source = path.read_text(encoding="utf-8")
    anchor = (
        "_qualification_common_properties = "
        "deepcopy(_proposal._COMMON_PROPERTIES)\n"
    )
    if source.count(anchor) != 1:
        raise SystemExit("qualification common-property anchor differs")
    replacement = '''_qualification_common_properties = deepcopy(_proposal._COMMON_PROPERTIES)
_qualification_budgets = deepcopy(_qualification_common_properties["budgets"])
assert isinstance(_qualification_budgets, dict)
_budget_properties = _qualification_budgets["properties"]
assert isinstance(_budget_properties, dict)
_budget_properties["max_external_calls_per_request"] = {"const": 0}
_budget_properties["max_gross_cost_microunits_per_request"] = {"const": 0}
_qualification_common_properties["budgets"] = _qualification_budgets
'''
    path.write_text(source.replace(anchor, replacement, 1), encoding="utf-8")


def _harden_schema_artifact() -> tuple[str, bytes]:
    path = Path(
        "newsroom/increment5/data/"
        "increment5_production_qualification_profile_v2.schema.json"
    )
    value = json.loads(path.read_text(encoding="utf-8"))
    properties = value["properties"]["budgets"]["properties"]
    properties["max_external_calls_per_request"] = {"const": 0}
    properties["max_gross_cost_microunits_per_request"] = {"const": 0}
    canonical = json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    path.write_bytes(canonical)
    return "sha256:" + hashlib.sha256(canonical).hexdigest(), canonical


def _write_regression() -> None:
    Path("newsroom/tests/test_increment5a_zero_budget_schema.py").write_text(
        '''from __future__ import annotations

from copy import deepcopy
import json

from jsonschema import Draft202012Validator

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5 import (
    INCREMENT_5A_DECISION_PACKET,
    PRODUCTION_PROFILE_SCHEMA,
    PRODUCTION_PROFILE_SCHEMA_DIGEST,
    PRODUCTION_PROFILE_SCHEMA_PATH,
    PRODUCTION_PROFILE_SCHEMA_VERSION,
    RetrievalProfileKind,
)


def _standalone_manifest() -> dict[str, object]:
    proposal = INCREMENT_5A_DECISION_PACKET
    required_modes = PRODUCTION_PROFILE_SCHEMA["properties"]["required_modes"][
        "const"
    ]
    return {
        "schema_version": PRODUCTION_PROFILE_SCHEMA_VERSION,
        "profile": RetrievalProfileKind.PRODUCTION.value,
        "decision_payload_digest": proposal.payload_digest,
        "proposal_record_digest": proposal.record_digest,
        "contract_bundle_digest": proposal.bundle.contract_digest,
        "approval_attestation_digest": "sha256:" + "a" * 64,
        "effective_contract_digest": "sha256:" + "b" * 64,
        "runtime_authority": "PRODUCTION_QUALIFICATION",
        "qualification_eligible": True,
        "required_modes": required_modes,
        "graph_free_fallback": False,
        "silent_mode_fallback": False,
        "components": {
            kind.value: {
                "contract_id": identity.contract_id,
                "contract_version": identity.contract_version,
                "implementation_version": identity.implementation_version,
                "configuration_digest": identity.configuration_digest,
                "identity_digest": identity.identity_digest,
                "implementation_kind": "REAL_REPOSITORY_NATIVE",
                "approval_status": "APPROVED_BY_ATTESTATION",
            }
            for kind, identity in proposal.bundle.component_by_kind.items()
        },
        "budgets": proposal.budgets.canonical_value(),
        "rights": {
            "protected_content_allowed": False,
            "rights_rechecked_at_hydration": True,
            "purge_required": True,
            "rebuild_must_not_resurrect": True,
        },
    }


def test_public_v2_schema_pins_zero_external_calls_and_spend() -> None:
    budget_schema = PRODUCTION_PROFILE_SCHEMA["properties"]["budgets"][
        "properties"
    ]
    assert budget_schema["max_external_calls_per_request"] == {"const": 0}
    assert budget_schema["max_gross_cost_microunits_per_request"] == {
        "const": 0
    }

    validator = Draft202012Validator(PRODUCTION_PROFILE_SCHEMA)
    manifest = _standalone_manifest()
    assert not tuple(validator.iter_errors(manifest))
    for field in (
        "max_external_calls_per_request",
        "max_gross_cost_microunits_per_request",
    ):
        tampered = deepcopy(manifest)
        budgets = tampered["budgets"]
        assert isinstance(budgets, dict)
        budgets[field] = 1
        assert tuple(validator.iter_errors(tampered))


def test_public_v2_schema_artifact_is_exact_canonical_zero_budget_contract() -> None:
    data = PRODUCTION_PROFILE_SCHEMA_PATH.read_bytes()
    assert data == canonical_json_bytes(json.loads(data.decode("utf-8")))
    assert digest_bytes(data) == PRODUCTION_PROFILE_SCHEMA_DIGEST
''',
        encoding="utf-8",
    )


def main() -> None:
    _harden_profile_schema_code()
    new_schema_digest, _canonical = _harden_schema_artifact()
    _replace_tracked(
        OLD_SCHEMA_DIGEST,
        new_schema_digest,
        label="old effective schema digest",
    )

    from newsroom.authority.canonical import digest_bytes
    from newsroom.increment5 import (
        QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST,
        expected_increment5a_owner_approval_body,
    )

    if QUALIFICATION_PRODUCTION_PROFILE_SCHEMA_DIGEST != new_schema_digest:
        raise SystemExit("runtime schema digest differs from canonical artifact")
    new_body_digest = digest_bytes(
        expected_increment5a_owner_approval_body().encode("utf-8")
    )
    _replace_tracked(
        OLD_BODY_DIGEST,
        new_body_digest,
        label="old owner-statement body digest",
    )
    _write_regression()

    if _tracked_files_with(OLD_SCHEMA_DIGEST):
        raise SystemExit("stale effective schema digest remains")
    if _tracked_files_with(OLD_BODY_DIGEST):
        raise SystemExit("stale owner-body digest remains")
    print(f"effective_schema={new_schema_digest}")
    print(f"owner_body={new_body_digest}")


if __name__ == "__main__":
    main()
