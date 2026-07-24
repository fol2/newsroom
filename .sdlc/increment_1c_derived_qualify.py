from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1 or new in text:
        raise SystemExit(f"qualifier source mismatch in {path}: {old}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    model_path = "newsroom/integrated/models.py"
    replace_exact(
        model_path,
        '''        graph_ids = {item.canonical_id for item in self.nodes}
        if set(indexed) != graph_ids:
            raise IntegratedContractError(
                "integrated exact index must cover the returned graph nodes exactly"
            )
        if not any(''',
        '''        graph_ids = {item.canonical_id for item in self.nodes}
        if set(indexed) != graph_ids:
            raise IntegratedContractError(
                "integrated exact index must cover the returned graph nodes exactly"
            )
        graph_nodes = {item.canonical_id: item for item in self.nodes}
        if any(
            (
                entry.node_type,
                entry.first_ledger_seq,
                entry.first_source_event_id,
                entry.first_source_event_digest,
            )
            != (
                graph_nodes[entry.canonical_id].node_type,
                graph_nodes[entry.canonical_id].first_ledger_seq,
                graph_nodes[entry.canonical_id].first_source_event_id,
                graph_nodes[entry.canonical_id].first_source_event_digest,
            )
            for entry in self.exact_index
        ):
            raise IntegratedContractError(
                "integrated exact index must match each returned graph node"
            )
        if any(
            node.first_ledger_seq > self.metadata.contiguous_ledger_seq
            for node in self.nodes
        ) or any(
            relation.ledger_seq > self.metadata.contiguous_ledger_seq
            for relation in self.relations
        ):
            raise IntegratedStateError(
                "integrated graph evidence exceeds the authority watermark"
            )
        if not any(''',
    )
    replace_exact(
        model_path,
        '''        for field_name in (
            "hydrated_blob_digest",
            "hydration_policy_contract_digest",
            "manifest_digest",
            "query_digest",
        ):
            validate_sha256_digest(getattr(self, field_name), field=field_name)
        if not isinstance(''',
        '''        for field_name in (
            "hydrated_blob_digest",
            "hydration_policy_contract_digest",
            "manifest_digest",
            "query_digest",
        ):
            validate_sha256_digest(getattr(self, field_name), field=field_name)
        if self.hydrated_blob_digest != self.manifest_digest:
            raise IntegratedStateError(
                "integrated hydrated blob must equal the canonical manifest"
            )
        if not isinstance(''',
    )


if __name__ == "__main__":
    main()
