from __future__ import annotations

import sqlite3
from dataclasses import dataclass

from newsroom.authority.persistence import AuthoritySchemaError
from newsroom.authority.types import UtcTimestamp
from newsroom.relations.editorial_models import (
    EditorialRelationAssertion,
    EditorialRelationCurrentView,
)
from newsroom.relations.editorial_types import (
    EditorialRelationAssertionId,
    EditorialRelationAssertionLifecycle,
    EditorialRelationDecisionId,
)


_LIFECYCLE_BY_ACTION = {
    "ACCEPT": EditorialRelationAssertionLifecycle.ACTIVE,
    "INVALIDATE": EditorialRelationAssertionLifecycle.INVALIDATED,
    "REVOKE": EditorialRelationAssertionLifecycle.REVOKED,
    "SUPERSEDE": EditorialRelationAssertionLifecycle.SUPERSEDED,
}


@dataclass(frozen=True, slots=True)
class _ExpectedEditorialCurrentProjection:
    assertion: EditorialRelationAssertion
    lifecycle: EditorialRelationAssertionLifecycle
    current_decision_id: EditorialRelationDecisionId
    current_decision_version: int
    updated_at: UtcTimestamp

    @property
    def current_view(self) -> EditorialRelationCurrentView:
        return EditorialRelationCurrentView(
            assertion=self.assertion,
            lifecycle=self.lifecycle,
            current_decision_id=self.current_decision_id,
            current_decision_version=self.current_decision_version,
            updated_at=self.updated_at,
        )


class _EditorialRelationProjectionMixin:
    def _expected_editorial_current_projection(
        self, conn: sqlite3.Connection
    ) -> tuple[_ExpectedEditorialCurrentProjection, ...]:
        expected: list[_ExpectedEditorialCurrentProjection] = []
        for assertion_row in conn.execute(
            "SELECT * FROM editorial_relation_assertions ORDER BY assertion_id"
        ).fetchall():
            assertion = self._editorial_assertion_from_row(conn, assertion_row)
            decision_row = conn.execute(
                "SELECT * FROM editorial_relation_decisions "
                "WHERE assertion_id=? OR target_assertion_id=? "
                "ORDER BY authority_ledger_seq DESC,decision_id DESC LIMIT 1",
                (str(assertion.assertion_id), str(assertion.assertion_id)),
            ).fetchone()
            if decision_row is None:
                raise AuthoritySchemaError(
                    "editorial relation assertion lacks retained decision authority"
                )
            action = str(decision_row["action"])
            lifecycle = _LIFECYCLE_BY_ACTION.get(action)
            if lifecycle is None:
                raise AuthoritySchemaError(
                    "editorial relation assertion latest decision is not a lifecycle action"
                )
            if action == "ACCEPT":
                if str(decision_row["assertion_id"]) != str(assertion.assertion_id):
                    raise AuthoritySchemaError(
                        "editorial relation assertion accept decision differs"
                    )
            elif str(decision_row["target_assertion_id"]) != str(
                assertion.assertion_id
            ):
                raise AuthoritySchemaError(
                    "editorial relation assertion lifecycle target differs"
                )

            latest_event = conn.execute(
                "SELECT * FROM editorial_relation_projection_events "
                "WHERE assertion_id=? "
                "ORDER BY source_ledger_seq DESC,projection_event_id DESC LIMIT 1",
                (str(assertion.assertion_id),),
            ).fetchone()
            if latest_event is None:
                raise AuthoritySchemaError(
                    "editorial relation assertion lacks immutable projection event"
                )
            expected_action = "UPSERT" if lifecycle.value == "ACTIVE" else "REMOVE"
            if (
                str(latest_event["source_event_id"])
                != str(decision_row["authority_event_id"])
                or int(latest_event["source_ledger_seq"])
                != int(decision_row["authority_ledger_seq"])
                or str(latest_event["action"]) != expected_action
                or str(latest_event["lifecycle"]) != lifecycle.value
            ):
                raise AuthoritySchemaError(
                    "editorial relation projection event differs from latest decision"
                )
            self._editorial_projection_event_from_row(conn, latest_event)
            expected.append(
                _ExpectedEditorialCurrentProjection(
                    assertion=assertion,
                    lifecycle=lifecycle,
                    current_decision_id=EditorialRelationDecisionId.parse(
                        str(decision_row["decision_id"])
                    ),
                    current_decision_version=int(decision_row["decision_version"]),
                    updated_at=UtcTimestamp.parse(str(decision_row["recorded_at"])),
                )
            )
        return tuple(expected)

    @staticmethod
    def _editorial_current_projection_row_matches(
        row: sqlite3.Row, expected: _ExpectedEditorialCurrentProjection
    ) -> bool:
        return (
            str(row["assertion_id"]) == str(expected.assertion.assertion_id)
            and str(row["lifecycle"]) == expected.lifecycle.value
            and str(row["current_decision_id"])
            == str(expected.current_decision_id)
            and int(row["current_decision_version"])
            == expected.current_decision_version
            and str(row["updated_at"]) == expected.updated_at.to_text()
        )

    def rebuild_editorial_current_projection(
        self,
    ) -> tuple[EditorialRelationCurrentView, ...]:
        """Recreate missing assertion heads from immutable relation decisions.

        Existing divergent rows are never overwritten. Every assertion's complete
        endpoint, extraction-evidence and entity-resolution provenance is rights-
        revalidated before the first insert, so rebuild cannot resurrect prohibited
        relation material or partially repair an invalid authority database.
        """

        if not self._allow_editorial_relation_projection_rebuild:
            raise PermissionError(
                "editorial relation current projection rebuild is not enabled"
            )
        with self._lock, self._transaction() as conn:
            expected = self._expected_editorial_current_projection(conn)
            for item in expected:
                self._require_editorial_assertion_rights_current(
                    conn, item.assertion.assertion_id
                )

            existing_rows = {
                str(row["assertion_id"]): row
                for row in conn.execute(
                    "SELECT * FROM editorial_relation_assertion_heads "
                    "ORDER BY assertion_id"
                ).fetchall()
            }
            expected_ids = {
                str(item.assertion.assertion_id) for item in expected
            }
            if set(existing_rows) - expected_ids:
                raise AuthoritySchemaError(
                    "editorial relation current projection contains unknown assertions"
                )
            for item in expected:
                assertion_id = str(item.assertion.assertion_id)
                existing = existing_rows.get(assertion_id)
                if existing is not None:
                    if not self._editorial_current_projection_row_matches(
                        existing, item
                    ):
                        raise AuthoritySchemaError(
                            "existing editorial relation current projection differs from rebuild"
                        )
                    continue
                conn.execute(
                    "INSERT INTO editorial_relation_assertion_heads("
                    "assertion_id,lifecycle,current_decision_id,"
                    "current_decision_version,updated_at) VALUES(?,?,?,?,?)",
                    (
                        assertion_id,
                        item.lifecycle.value,
                        str(item.current_decision_id),
                        item.current_decision_version,
                        item.updated_at.to_text(),
                    ),
                )
            return tuple(
                item.current_view
                for item in expected
                if item.lifecycle is EditorialRelationAssertionLifecycle.ACTIVE
            )


__all__ = ["_EditorialRelationProjectionMixin"]
