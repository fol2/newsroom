from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1 or new in text:
        raise SystemExit(f"qualifier source mismatch in {path}: {old}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    path = "newsroom/authority/_integrated_store.py"
    replace_exact(
        path,
        '''        value = self._canonical_row_value(
            row, identity="integrated retrieval context"
        )
        canonical_digest = str(row["canonical_digest"])''',
        '''        value = self._canonical_row_value(
            row, identity="integrated retrieval context"
        )
        context = self._context_from_row(row)
        canonical_digest = str(row["canonical_digest"])''',
    )
    replace_exact(
        path,
        '''        event = conn.execute(
            "SELECT aggregate_type,aggregate_id,object_admission_id,payload_digest "
            "FROM ledger_events WHERE event_id=?",
            (str(row["fixture_event_id"]),),
        ).fetchone()
        if (
            event is None
            or str(event["aggregate_type"]) != "integrated_fixture"
            or str(event["aggregate_id"]) != str(row["fixture_aggregate_id"])
            or str(event["object_admission_id"]) != str(row["admission_id"])
            or str(event["payload_digest"]) != str(row["manifest_digest"])
        ):
            raise AuthorityPersistenceError(
                "integrated retrieval context lacks exact fixture authority"
            )''',
        '''        event = conn.execute(
            "SELECT event_type,aggregate_type,aggregate_id,object_admission_id,"
            "payload_digest,trust_scope,security_scope,retention_scope "
            "FROM ledger_events WHERE event_id=?",
            (str(row["fixture_event_id"]),),
        ).fetchone()
        if (
            event is None
            or str(event["event_type"]) != "authority.aggregate.versioned"
            or str(event["aggregate_type"]) != "integrated_fixture"
            or str(event["aggregate_id"]) != str(row["fixture_aggregate_id"])
            or str(event["object_admission_id"]) != str(row["admission_id"])
            or str(event["payload_digest"]) != str(row["manifest_digest"])
            or context.hydrated_blob_digest != str(row["manifest_digest"])
            or str(event["trust_scope"]) != "OBSERVED"
            or str(event["security_scope"]) != "authority.protected"
            or str(event["retention_scope"]) != "source.short"
        ):
            raise AuthorityPersistenceError(
                "integrated retrieval context lacks exact fixture authority"
            )''',
    )
    replace_exact(
        path,
        '''        access_value = self._canonical_row_value(
            access, identity="integrated hydration decision"
        )
        if (
            str(access["admission_id"]) != str(row["admission_id"])
            or access_value.get("admission_id") != str(row["admission_id"])
        ):
            raise AuthorityPersistenceError(
                "integrated hydration decision belongs to another admission"
            )

        nodes = value.get("nodes")''',
        '''        access_value = self._canonical_row_value(
            access, identity="integrated hydration decision"
        )
        cutoff = access_value.get("state_cutoff")
        if not isinstance(cutoff, dict):
            raise AuthorityPersistenceError(
                "integrated hydration decision lacks an exact state cutoff"
            )
        if (
            str(access["admission_id"]) != str(row["admission_id"])
            or access_value.get("admission_id") != str(row["admission_id"])
            or str(access["hydration_policy_contract_digest"])
            != context.hydration_policy_contract_digest
            or access_value.get("policy_contract_digest")
            != context.hydration_policy_contract_digest
            or int(access["byte_offset"]) != 0
            or int(access["allowed_bytes"]) <= 0
            or cutoff.get("admission_id") != str(row["admission_id"])
            or cutoff.get("blob_digest") != context.hydrated_blob_digest
            or cutoff.get("admission_state") != "ACTIVE"
            or cutoff.get("blob_state") != "ACTIVE"
            or cutoff.get("blob_integrity_state") != "VERIFIED"
            or cutoff.get("deletion_state") is not None
            or cutoff.get("offset") != 0
            or cutoff.get("length") != int(access["allowed_bytes"])
        ):
            raise AuthorityPersistenceError(
                "integrated hydration decision differs from retained context"
            )

        generation = conn.execute(
            "SELECT g.family_id,d.definition_version,d.projector_version,"
            "d.ontology_contract_digest,d.mapping_contract_digest "
            "FROM projection_generations g "
            "JOIN projection_families f ON f.family_id=g.family_id "
            "JOIN projection_family_definitions d "
            "ON d.definition_digest=f.definition_digest "
            "WHERE g.generation_id=?",
            (str(row["generation_id"]),),
        ).fetchone()
        active_version = conn.execute(
            "SELECT 1 FROM projection_generation_versions "
            "WHERE generation_id=? AND state='ACTIVE' LIMIT 1",
            (str(row["generation_id"]),),
        ).fetchone()
        checkpoint = conn.execute(
            "SELECT 1 FROM projection_checkpoint_versions "
            "WHERE generation_id=? AND contiguous_ledger_seq=? LIMIT 1",
            (
                str(row["generation_id"]),
                int(row["projected_through_ledger_seq"]),
            ),
        ).fetchone()
        validation = conn.execute(
            "SELECT 1 FROM projection_generation_validations "
            "WHERE generation_id=? AND checkpoint_ledger_seq=? "
            "AND ontology_contract_digest=? AND mapping_contract_digest=? "
            "AND projector_version=? LIMIT 1",
            (
                str(row["generation_id"]),
                int(row["projected_through_ledger_seq"]),
                context.metadata.ontology_contract_digest,
                context.metadata.mapping_contract_digest,
                context.metadata.projector_version,
            ),
        ).fetchone()
        promotion = conn.execute(
            "SELECT 1 FROM projection_generation_promotions "
            "WHERE generation_id=? AND checkpoint_ledger_seq=? LIMIT 1",
            (
                str(row["generation_id"]),
                int(row["projected_through_ledger_seq"]),
            ),
        ).fetchone()
        if (
            generation is None
            or str(generation["family_id"]) != context.metadata.family_id
            or str(generation["definition_version"])
            != context.metadata.family_definition_version
            or str(generation["projector_version"])
            != context.metadata.projector_version
            or str(generation["ontology_contract_digest"])
            != context.metadata.ontology_contract_digest
            or str(generation["mapping_contract_digest"])
            != context.metadata.mapping_contract_digest
            or active_version is None
            or checkpoint is None
            or validation is None
            or promotion is None
        ):
            raise AuthorityPersistenceError(
                "integrated retrieval context lacks retained ACTIVE projection evidence"
            )

        nodes = value.get("nodes")''',
    )


if __name__ == "__main__":
    main()
