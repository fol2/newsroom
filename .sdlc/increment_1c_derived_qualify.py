from __future__ import annotations

from pathlib import Path


def replace_exact(path: str, old: str, new: str) -> None:
    target = Path(path)
    text = target.read_text(encoding="utf-8")
    if text.count(old) != 1 or new in text:
        raise SystemExit(f"qualifier source mismatch in {path}: {old}")
    target.write_text(text.replace(old, new), encoding="utf-8")


def main() -> None:
    store_path = "newsroom/authority/_integrated_store.py"
    replace_exact(
        store_path,
        '''import json
import sqlite3''',
        '''from dataclasses import asdict
import json
import sqlite3''',
    )
    replace_exact(
        store_path,
        '''            for row in conn.execute(
                "SELECT * FROM candidate_admission_decisions"
            ).fetchall():
                self._validate_decision_row(conn, row)

    def _validate_context_row(''',
        '''            for row in conn.execute(
                "SELECT * FROM candidate_admission_decisions"
            ).fetchall():
                self._validate_decision_row(conn, row)
            for row in conn.execute(
                "SELECT * FROM story_candidates"
            ).fetchall():
                self._validate_candidate_identity_row(conn, row)

    def _validate_candidate_identity_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> None:
        collision = str(row["semantic_collision_digest"])
        validate_sha256_digest(
            collision,
            field="candidate_semantic_collision_digest",
        )
        versions = conn.execute(
            "SELECT candidate_version_id,version_number,recorded_at "
            "FROM story_candidate_versions WHERE candidate_id=? "
            "ORDER BY version_number",
            (str(row["candidate_id"]),),
        ).fetchall()
        admitted = conn.execute(
            "SELECT candidate_version_id,recorded_at "
            "FROM candidate_admission_decisions "
            "WHERE candidate_id=? AND outcome='ADMITTED' "
            "ORDER BY recorded_at",
            (str(row["candidate_id"]),),
        ).fetchall()
        if (
            not versions
            or int(versions[0]["version_number"]) != 1
            or len(admitted) != 1
            or str(admitted[0]["candidate_version_id"])
            != str(versions[0]["candidate_version_id"])
            or str(row["created_at"]) != str(versions[0]["recorded_at"])
            or str(row["created_at"]) != str(admitted[0]["recorded_at"])
        ):
            raise AuthorityPersistenceError(
                "story candidate identity lacks one exact ADMITTED immutable version"
            )
        UtcTimestamp.parse(str(row["created_at"]))

    def _validate_context_row(''',
    )
    replace_exact(
        store_path,
        '''        promotion = conn.execute(
            "SELECT 1 FROM projection_generation_promotions "
            "WHERE generation_id=? AND checkpoint_ledger_seq=? LIMIT 1",
            (
                str(row["generation_id"]),
                int(row["projected_through_ledger_seq"]),
            ),
        ).fetchone()''',
        '''        promotion = conn.execute(
            "SELECT 1 FROM projection_generation_promotions "
            "WHERE generation_id=? AND checkpoint_ledger_seq<=? LIMIT 1",
            (
                str(row["generation_id"]),
                int(row["projected_through_ledger_seq"]),
            ),
        ).fetchone()''',
    )
    replace_exact(
        store_path,
        '''            canonical_id = str(index_row["canonical_id"])
            if index_value != expected_index.get(canonical_id):
                raise AuthorityPersistenceError(
                    "integrated exact index differs from context evidence"
                )''',
        '''            canonical_id = str(index_row["canonical_id"])
            if index_value != expected_index.get(canonical_id):
                raise AuthorityPersistenceError(
                    "integrated exact index differs from context evidence"
                )
            source = self._source_event(
                conn,
                int(index_row["first_ledger_seq"]),
            )
            if (
                source.event_id != str(index_row["first_source_event_id"])
                or digest_canonical(asdict(source))
                != str(index_row["first_source_event_digest"])
            ):
                raise AuthorityPersistenceError(
                    "integrated exact index source event differs from ledger authority"
                )''',
    )

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
