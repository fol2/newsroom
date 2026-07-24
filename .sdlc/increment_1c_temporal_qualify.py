from __future__ import annotations

from pathlib import Path


def main() -> None:
    path = Path("newsroom/authority/_integrated_system.py")
    text = path.read_text(encoding="utf-8")
    old = '''        expected_metadata = (
            metadata.family.family_id,
            metadata.family.definition_version,
            metadata.family.projector_version,
            metadata.family.ontology_contract_digest,
            metadata.family.mapping_contract_digest,
            metadata.generation.generation_id,
            metadata.generation.state,
            metadata.contiguous_ledger_seq,
            metadata.open_gap_count,
            metadata.dead_letter_count,
            metadata.serving_time,
        )
        retained_metadata = (
            context.metadata.family_id,
            context.metadata.family_definition_version,
            context.metadata.projector_version,
            context.metadata.ontology_contract_digest,
            context.metadata.mapping_contract_digest,
            context.metadata.generation_id,
            context.metadata.generation_state,
            context.metadata.contiguous_ledger_seq,
            context.metadata.open_gap_count,
            context.metadata.dead_letter_count,
            context.metadata.serving_time,
        )
        if expected_metadata != retained_metadata:
            raise IntegratedStateError(
                "retrieval context is stale against active projection authority"
            )'''
    new = '''        expected_metadata = (
            metadata.family.family_id,
            metadata.family.definition_version,
            metadata.family.projector_version,
            metadata.family.ontology_contract_digest,
            metadata.family.mapping_contract_digest,
            metadata.generation.generation_id,
            metadata.generation.state,
            metadata.contiguous_ledger_seq,
            metadata.open_gap_count,
            metadata.dead_letter_count,
        )
        retained_metadata = (
            context.metadata.family_id,
            context.metadata.family_definition_version,
            context.metadata.projector_version,
            context.metadata.ontology_contract_digest,
            context.metadata.mapping_contract_digest,
            context.metadata.generation_id,
            context.metadata.generation_state,
            context.metadata.contiguous_ledger_seq,
            context.metadata.open_gap_count,
            context.metadata.dead_letter_count,
        )
        if (
            expected_metadata != retained_metadata
            or metadata.serving_time.value
            < context.metadata.serving_time.value
        ):
            raise IntegratedStateError(
                "retrieval context is stale against active projection authority"
            )'''
    if text.count(old) != 1 or new in text:
        raise SystemExit("integrated serving-time source differs from expected")
    path.write_text(text.replace(old, new), encoding="utf-8")


if __name__ == "__main__":
    main()
