from __future__ import annotations

import json

from .canonical import canonical_json_bytes, digest_bytes, validate_sha256_digest
from .models import CommittedCommand
from .store_base import AuthorityStoreError
from .types import AggregateVersion


class AuthorityStoreResultsMixin:
    def _next_ledger_seq(self) -> int:
        sequence_row = self._conn.execute(
            "SELECT seq FROM sqlite_sequence WHERE name = 'ledger_events'"
        ).fetchone()
        sequence_value = 0 if sequence_row is None else int(sequence_row["seq"])
        maximum = int(
            self._conn.execute(
                "SELECT COALESCE(MAX(ledger_seq), 0) FROM ledger_events"
            ).fetchone()[0]
        )
        return max(sequence_value, maximum) + 1

    def _decode_result(
        self, result_bytes: bytes, expected_digest: str, *, replayed: bool
    ) -> CommittedCommand:
        if digest_bytes(result_bytes) != validate_sha256_digest(
            expected_digest, field="result_digest"
        ):
            raise AuthorityStoreError("stored command result digest mismatch")
        try:
            value = json.loads(result_bytes.decode("utf-8"))
        except (UnicodeDecodeError, json.JSONDecodeError) as exc:
            raise AuthorityStoreError("stored command result is invalid JSON") from exc
        if canonical_json_bytes(value) != result_bytes:
            raise AuthorityStoreError("stored command result is not canonical")
        return CommittedCommand(
            command_id=str(value["command_id"]),
            aggregate_type=str(value["aggregate_type"]),
            aggregate_id=str(value["aggregate_id"]),
            aggregate_version=AggregateVersion(int(value["aggregate_version"])),
            ledger_seq=int(value["ledger_seq"]),
            event_id=str(value["event_id"]),
            result_digest=expected_digest,
            replayed=replayed,
        )
