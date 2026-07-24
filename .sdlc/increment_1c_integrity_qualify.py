from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1 or new in text:
        raise SystemExit(f"qualifier source mismatch in {path}: {old}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    replace_exact(
        "newsroom/integrated/proof.py",
        '''                raise IntegratedStateError(
                    "fixture event differs from committed governed authority"
                )
            return IntegratedFixtureAuthority(''',
        '''                raise IntegratedStateError(
                    "fixture event differs from committed governed authority"
                )
            hydrated = system.objects.hydrate(
                HydrationRequest(
                    admission.admission.admission_id,
                    self._environment.fixture_hydration_purpose,
                ),
                proof=proof,
            )
            self._require_hydrated_manifest(hydrated, manifest)
            return IntegratedFixtureAuthority(''',
    )
    replace_exact(
        "newsroom/integrated/proof.py",
        '                    keys.value("family-register"),',
        '                    f"integrated-family-register:{self._environment.family_id}",',
    )
    replace_exact(
        "newsroom/integrated/models.py",
        '''            "query_valid_time": self.metadata.query_valid_time.to_text(),
            "authoritative_system": self.metadata.authoritative_system,''',
        '''            "query_valid_time": self.metadata.query_valid_time.to_text(),
            "serving_time": self.metadata.serving_time.to_text(),
            "authoritative_system": self.metadata.authoritative_system,''',
    )
    replace_exact(
        "newsroom/authority/_integrated_store.py",
        '''        access_value = self._canonical_row_value(
            access, identity="candidate hydration decision"
        )
        if (
            str(access["admission_id"]) != str(context.admission_id)
            or str(access["hydration_policy_contract_digest"])
            != context.hydration_policy_contract_digest
            or int(access["byte_offset"]) != 0
            or int(access["allowed_bytes"]) <= 0
            or access_value.get("admission_id") != str(context.admission_id)
            or access_value.get("policy_contract_digest")
            != context.hydration_policy_contract_digest
        ):
            raise IntegratedStateError(
                "hydration decision differs from retrieval context"
            )''',
        '''        access_value = self._canonical_row_value(
            access, identity="candidate hydration decision"
        )
        access_cutoff = access_value.get("state_cutoff")
        if not isinstance(access_cutoff, dict):
            raise IntegratedStateError(
                "hydration decision lacks an exact authority state cutoff"
            )
        if (
            str(access["admission_id"]) != str(context.admission_id)
            or str(access["hydration_policy_contract_digest"])
            != context.hydration_policy_contract_digest
            or int(access["byte_offset"]) != 0
            or int(access["allowed_bytes"]) <= 0
            or access_value.get("admission_id") != str(context.admission_id)
            or access_value.get("policy_contract_digest")
            != context.hydration_policy_contract_digest
            or access_cutoff.get("admission_id")
            != str(context.admission_id)
            or access_cutoff.get("blob_digest") != manifest.manifest_digest
            or access_cutoff.get("admission_state") != "ACTIVE"
            or access_cutoff.get("blob_state") != "ACTIVE"
            or access_cutoff.get("blob_integrity_state") != "VERIFIED"
            or access_cutoff.get("deletion_state") is not None
            or access_cutoff.get("offset") != 0
            or access_cutoff.get("length") != int(access["allowed_bytes"])
        ):
            raise IntegratedStateError(
                "hydration decision differs from retrieval context"
            )''',
    )
    replace_exact(
        "newsroom/tests/test_integrated_c1_proof_integrity.py",
        '''    HydrationPolicyRegistry,
    ObjectHydrationDenied,
    ObjectLimits,''',
        '''    HydrationPolicyRegistry,
    ObjectAdmissionDenied,
    ObjectHydrationDenied,
    ObjectLimits,''',
    )
    replace_exact(
        "newsroom/tests/test_integrated_c1_proof_integrity.py",
        "    with pytest.raises(ObjectHydrationDenied):",
        "    with pytest.raises((ObjectAdmissionDenied, ObjectHydrationDenied)):",
    )


if __name__ == "__main__":
    main()
