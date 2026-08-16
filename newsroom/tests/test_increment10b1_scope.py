import pytest
from newsroom.increment10.scope import FROZEN_SCOPE

def test_exact_cohort_destination_and_prospective_window():
    s=FROZEN_SCOPE.scope
    assert s["candidate_version_ids"] == tuple(f"candidate-version:increment10-fixture-{i:03d}" for i in range(1,4))
    assert (s["denominator"],s["exposure_min"],s["exposure_max"]) == (3,3,3)
    assert s["prospective_window"]["closes_after_terminal_outcome"] is True

def test_rights_sensitive_review_and_credentials_complete():
    assert all(FROZEN_SCOPE.rights_sensitive[k] == "SYNTHETIC_ONLY" for k in ("personal_data","children","courts","high_risk_allegations"))
    assert FROZEN_SCOPE.review["blinding"].startswith("HIDE_EXPECTED")
    assert FROZEN_SCOPE.review["live_evidence_access"] is False
    assert FROZEN_SCOPE.credentials_egress["credential_classes"] == ()
    assert FROZEN_SCOPE.credentials_egress["allowed_hosts"] == ()

def test_budgets_retention_and_operational_differences_are_closed_world():
    assert FROZEN_SCOPE.budgets["gross_gbp_minor_units_max"] == 0
    assert FROZEN_SCOPE.budgets["storage_bytes_max"] == 10485760
    assert FROZEN_SCOPE.retention["no_resurrection"] is True
    assert "NO_LIVE_SOURCE" in FROZEN_SCOPE.operational_profile["differences"]
    assert FROZEN_SCOPE.permits_runtime is False

def test_early_stop_precedence_is_deterministic():
    assert FROZEN_SCOPE.stop_reason({"BUDGET_EXHAUSTION","RIGHTS_BREACH"}) == "RIGHTS_OR_CREDENTIAL"
    assert FROZEN_SCOPE.stop_reason({"IMPOSSIBLE_COVERAGE","PUBLIC_EFFECT"}) == "PUBLIC_OR_PRODUCTION_EFFECT"
    assert FROZEN_SCOPE.stop_reason(set()) is None

def test_material_change_requires_distinct_new_content_addressed_plan():
    assert not FROZEN_SCOPE.permits_material_change(None)
    assert not FROZEN_SCOPE.permits_material_change(FROZEN_SCOPE.plan_digest)
    assert FROZEN_SCOPE.permits_material_change("sha256:"+"f"*64)

def test_nested_scope_is_immutable():
    with pytest.raises(TypeError): FROZEN_SCOPE.scope["denominator"]=4  # type: ignore[index]
    with pytest.raises(TypeError): FROZEN_SCOPE.scope["prospective_window"]["closes_after_terminal_outcome"]=False  # type: ignore[index]
