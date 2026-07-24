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
        "newsroom/authority/_integrated_store.py",
        '''    def _validate_candidate_version_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> None:
        value = self._canonical_row_value(
            row, identity="story candidate version"
        )
        if (
            value.get("contract") != _CANDIDATE_VERSION_CONTRACT
            or value.get("candidate_id") != str(row["candidate_id"])
            or value.get("candidate_version_id")
            != str(row["candidate_version_id"])
            or value.get("version_number") != int(row["version_number"])
            or value.get("fixture_id") != str(row["fixture_id"])
            or value.get("signal_id") != str(row["signal_id"])
            or value.get("lead_id") != str(row["lead_id"])
            or value.get("hypothesis_version_id")
            != str(row["hypothesis_version_id"])
            or value.get("route") != str(row["route"])
            or value.get("retrieval_context_id")
            != str(row["retrieval_context_id"])
            or value.get("manifest_digest") != str(row["manifest_digest"])
        ):
            raise AuthorityPersistenceError(
                "story candidate version columns differ from canonical evidence"
            )
        candidate = conn.execute(
            "SELECT semantic_collision_digest FROM story_candidates "
            "WHERE candidate_id=?",
            (str(row["candidate_id"]),),
        ).fetchone()
        if candidate is None:
            raise AuthorityPersistenceError(
                "story candidate version lacks stable candidate identity"
            )
        validate_sha256_digest(
            str(candidate["semantic_collision_digest"]),
            field="candidate_semantic_collision_digest",
        )

    def _validate_decision_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> None:
        value = self._canonical_row_value(
            row, identity="candidate admission decision"
        )
        expected = {
            "decision_id": str(row["decision_id"]),
            "proposal_id": str(row["proposal_id"]),
            "outcome": str(row["outcome"]),
            "candidate_id": str(row["candidate_id"]),
            "candidate_version_id": str(row["candidate_version_id"]),
            "route": str(row["route"]),
            "fixture_id": str(row["fixture_id"]),
            "retrieval_context_id": str(row["retrieval_context_id"]),
            "retrieval_context_digest": str(
                row["retrieval_context_digest"]
            ),
            "manifest_digest": str(row["manifest_digest"]),
            "semantic_collision_digest": str(
                row["semantic_collision_digest"]
            ),
            "authority_event_id": str(row["authority_event_id"]),
            "authority_aggregate_version": int(
                row["authority_aggregate_version"]
            ),
        }
        if value.get("contract") != _DECISION_CONTRACT or any(
            value.get(key) != item for key, item in expected.items()
        ):
            raise AuthorityPersistenceError(
                "candidate admission decision columns differ from canonical evidence"
            )
        event = conn.execute(
            "SELECT event_type,aggregate_type,aggregate_id,aggregate_version "
            "FROM ledger_events WHERE event_id=?",
            (str(row["authority_event_id"]),),
        ).fetchone()
        if (
            event is None
            or str(event["event_type"]) != "candidate.admission.decided"
            or str(event["aggregate_type"])
            != str(row["proposal_aggregate_type"])
            or str(event["aggregate_id"]) != str(row["proposal_id"])
            or int(event["aggregate_version"])
            != int(row["authority_aggregate_version"])
        ):
            raise AuthorityPersistenceError(
                "candidate admission decision lacks exact authority event"
            )''',
        '''    def _validate_candidate_version_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> None:
        value = self._canonical_row_value(
            row, identity="story candidate version"
        )
        manifest = value.get("manifest")
        if not isinstance(manifest, dict):
            raise AuthorityPersistenceError(
                "story candidate version lacks a canonical fixture manifest"
            )
        if (
            value.get("contract") != _CANDIDATE_VERSION_CONTRACT
            or value.get("candidate_id") != str(row["candidate_id"])
            or value.get("candidate_version_id")
            != str(row["candidate_version_id"])
            or value.get("version_number") != int(row["version_number"])
            or value.get("fixture_id") != str(row["fixture_id"])
            or value.get("signal_id") != str(row["signal_id"])
            or value.get("lead_id") != str(row["lead_id"])
            or value.get("hypothesis_version_id")
            != str(row["hypothesis_version_id"])
            or value.get("route") != str(row["route"])
            or value.get("hypothesis_trust_scope")
            != str(row["hypothesis_trust_scope"])
            or value.get("retrieval_context_id")
            != str(row["retrieval_context_id"])
            or value.get("manifest_digest") != str(row["manifest_digest"])
        ):
            raise AuthorityPersistenceError(
                "story candidate version columns differ from canonical evidence"
            )

        context = conn.execute(
            "SELECT fixture_id,fixture_event_id,admission_id,context_digest,"
            "manifest_digest FROM integrated_retrieval_contexts "
            "WHERE context_id=?",
            (str(row["retrieval_context_id"]),),
        ).fetchone()
        if (
            context is None
            or str(context["fixture_id"]) != str(row["fixture_id"])
            or str(context["manifest_digest"])
            != str(row["manifest_digest"])
            or value.get("fixture_event_id")
            != str(context["fixture_event_id"])
            or value.get("admission_id") != str(context["admission_id"])
            or value.get("retrieval_context_digest")
            != str(context["context_digest"])
        ):
            raise AuthorityPersistenceError(
                "story candidate version differs from retained retrieval context"
            )

        manifest_digest = digest_canonical(manifest)
        if (
            manifest.get("contract")
            != "newsroom-integrated-fixture-manifest-v1"
            or manifest_digest != str(row["manifest_digest"])
            or manifest.get("fixture_id") != str(row["fixture_id"])
            or manifest.get("signal_id") != str(row["signal_id"])
            or manifest.get("lead_id") != str(row["lead_id"])
            or manifest.get("hypothesis_version_id")
            != str(row["hypothesis_version_id"])
            or manifest.get("hypothesis_trust_scope") != "PROPOSED"
            or value.get("hypothesis_trust_scope") != "PROPOSED"
        ):
            raise AuthorityPersistenceError(
                "story candidate version manifest identity is inconsistent"
            )

        candidate = conn.execute(
            "SELECT semantic_collision_digest FROM story_candidates "
            "WHERE candidate_id=?",
            (str(row["candidate_id"]),),
        ).fetchone()
        if candidate is None:
            raise AuthorityPersistenceError(
                "story candidate version lacks stable candidate identity"
            )
        expected_collision = digest_canonical(
            {
                "contract": _COLLISION_CONTRACT,
                "fixture_id": str(row["fixture_id"]),
                "fixture_event_id": str(context["fixture_event_id"]),
                "signal_id": str(row["signal_id"]),
                "lead_id": str(row["lead_id"]),
                "hypothesis_version_id": str(row["hypothesis_version_id"]),
                "route": str(row["route"]),
                "manifest_digest": str(row["manifest_digest"]),
            }
        )
        collision = str(candidate["semantic_collision_digest"])
        validate_sha256_digest(
            collision,
            field="candidate_semantic_collision_digest",
        )
        if collision != expected_collision:
            raise AuthorityPersistenceError(
                "story candidate semantic collision differs from immutable version"
            )

    def _validate_decision_row(
        self,
        conn: sqlite3.Connection,
        row: sqlite3.Row,
    ) -> None:
        value = self._canonical_row_value(
            row, identity="candidate admission decision"
        )
        expected = {
            "decision_id": str(row["decision_id"]),
            "proposal_id": str(row["proposal_id"]),
            "outcome": str(row["outcome"]),
            "candidate_id": str(row["candidate_id"]),
            "candidate_version_id": str(row["candidate_version_id"]),
            "route": str(row["route"]),
            "fixture_id": str(row["fixture_id"]),
            "retrieval_context_id": str(row["retrieval_context_id"]),
            "retrieval_context_digest": str(
                row["retrieval_context_digest"]
            ),
            "manifest_digest": str(row["manifest_digest"]),
            "semantic_collision_digest": str(
                row["semantic_collision_digest"]
            ),
            "authority_event_id": str(row["authority_event_id"]),
            "authority_aggregate_version": int(
                row["authority_aggregate_version"]
            ),
        }
        if value.get("contract") != _DECISION_CONTRACT or any(
            value.get(key) != item for key, item in expected.items()
        ):
            raise AuthorityPersistenceError(
                "candidate admission decision columns differ from canonical evidence"
            )

        candidate = conn.execute(
            "SELECT semantic_collision_digest FROM story_candidates "
            "WHERE candidate_id=?",
            (str(row["candidate_id"]),),
        ).fetchone()
        version = conn.execute(
            "SELECT candidate_id,fixture_id,route,retrieval_context_id,"
            "manifest_digest FROM story_candidate_versions "
            "WHERE candidate_version_id=?",
            (str(row["candidate_version_id"]),),
        ).fetchone()
        context = conn.execute(
            "SELECT context_digest FROM integrated_retrieval_contexts "
            "WHERE context_id=?",
            (str(row["retrieval_context_id"]),),
        ).fetchone()
        if (
            candidate is None
            or version is None
            or context is None
            or str(candidate["semantic_collision_digest"])
            != str(row["semantic_collision_digest"])
            or str(version["candidate_id"]) != str(row["candidate_id"])
            or str(version["fixture_id"]) != str(row["fixture_id"])
            or str(version["route"]) != str(row["route"])
            or str(version["retrieval_context_id"])
            != str(row["retrieval_context_id"])
            or str(version["manifest_digest"])
            != str(row["manifest_digest"])
            or str(context["context_digest"])
            != str(row["retrieval_context_digest"])
        ):
            raise AuthorityPersistenceError(
                "candidate admission decision cross-record identity is inconsistent"
            )

        event = conn.execute(
            "SELECT event_type,aggregate_type,aggregate_id,aggregate_version,"
            "payload_digest,object_admission_id,trust_scope,security_scope,"
            "retention_scope FROM ledger_events WHERE event_id=?",
            (str(row["authority_event_id"]),),
        ).fetchone()
        event_payload_digest = digest_canonical(
            {
                "proposal_id": str(row["proposal_id"]),
                "route": str(row["route"]),
                "fixture_id": str(row["fixture_id"]),
                "retrieval_context_digest": str(
                    row["retrieval_context_digest"]
                ),
                "manifest_digest": str(row["manifest_digest"]),
                "semantic_collision_digest": str(
                    row["semantic_collision_digest"]
                ),
            }
        )
        if (
            event is None
            or str(event["event_type"]) != "candidate.admission.decided"
            or str(event["aggregate_type"])
            != str(row["proposal_aggregate_type"])
            or str(event["aggregate_id"]) != str(row["proposal_id"])
            or int(event["aggregate_version"])
            != int(row["authority_aggregate_version"])
            or str(event["payload_digest"]) != event_payload_digest
            or event["object_admission_id"] is not None
            or str(event["trust_scope"]) != "ADMITTED"
            or str(event["security_scope"]) != "authority.integrated"
            or str(event["retention_scope"]) != "authority.audit"
        ):
            raise AuthorityPersistenceError(
                "candidate admission decision lacks exact authority event"
            )''',
    )


if __name__ == "__main__":
    main()
