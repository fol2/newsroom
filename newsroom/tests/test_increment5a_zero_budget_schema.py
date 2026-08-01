from __future__ import annotations

from copy import deepcopy
import json

from jsonschema import Draft202012Validator

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.increment5 import (
    INCREMENT_5A_DECISION_PACKET,
    FIXTURE_REPLAY_PROFILE_SCHEMA,
    FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,
    FIXTURE_REPLAY_PROFILE_SCHEMA_PATH,
    FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION,
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


def test_public_fixture_v2_schema_is_standalone_zero_budget_and_unprotected() -> None:
    schema = FIXTURE_REPLAY_PROFILE_SCHEMA
    budgets = schema["properties"]["budgets"]["properties"]
    rights = schema["properties"]["rights"]["properties"]
    assert budgets["max_external_calls_per_request"] == {"const": 0}
    assert budgets[
        "max_gross_cost_microunits_per_request"
    ] == {"const": 0}
    assert rights["protected_content_allowed"] == {"const": False}

    proposal = INCREMENT_5A_DECISION_PACKET
    manifest = {
        "schema_version": FIXTURE_REPLAY_PROFILE_SCHEMA_VERSION,
        "profile": RetrievalProfileKind.FIXTURE_REPLAY.value,
        "decision_payload_digest": proposal.payload_digest,
        "contract_bundle_digest": proposal.bundle.contract_digest,
        "runtime_authority": "CONTRACT_AND_FIXTURE_REPLAY_ONLY",
        "qualification_eligible": False,
        "required_modes": schema["properties"]["required_modes"]["const"],
        "graph_free_fallback": False,
        "silent_mode_fallback": False,
        "components": {
            kind.value: {
                "contract_id": identity.contract_id,
                "contract_version": identity.contract_version,
                "implementation_version": identity.implementation_version,
                "configuration_digest": identity.configuration_digest,
                "identity_digest": identity.identity_digest,
                "implementation_kind": "REPOSITORY_FIXTURE",
                "approval_status": "NON_QUALIFYING",
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
        "fixture": {
            "fixture_id": "fixture-v2",
            "fixture_manifest_digest": "sha256:" + "f" * 64,
            "protected_content_present": False,
            "production_substitution_allowed": False,
        },
    }
    validator = Draft202012Validator(schema)
    assert not tuple(validator.iter_errors(manifest))
    for path, replacement in (
        (("budgets", "max_external_calls_per_request"), 1),
        (("budgets", "max_gross_cost_microunits_per_request"), 1),
        (("rights", "protected_content_allowed"), True),
    ):
        tampered = deepcopy(manifest)
        parent = tampered[path[0]]
        assert isinstance(parent, dict)
        parent[path[1]] = replacement
        assert tuple(validator.iter_errors(tampered))

    data = FIXTURE_REPLAY_PROFILE_SCHEMA_PATH.read_bytes()
    assert data == canonical_json_bytes(
        json.loads(data.decode("utf-8"))
    )
    assert digest_bytes(data) == FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST


def test_public_v2_schema_artifact_is_exact_canonical_zero_budget_contract() -> None:
    data = PRODUCTION_PROFILE_SCHEMA_PATH.read_bytes()
    assert data == canonical_json_bytes(json.loads(data.decode("utf-8")))
    assert digest_bytes(data) == PRODUCTION_PROFILE_SCHEMA_DIGEST
