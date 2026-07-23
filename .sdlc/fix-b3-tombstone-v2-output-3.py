from __future__ import annotations

from pathlib import Path


path = Path("newsroom/authority/_projection_store.py")
value = path.read_text(encoding="utf-8")
old_import = "from .types import EventId, TrustScope, UtcTimestamp\n"
new_import = (
    "from .types import (\n"
    "    EventId,\n"
    "    ObjectAdmissionId,\n"
    "    PayloadMode,\n"
    "    TrustScope,\n"
    "    UtcTimestamp,\n"
    ")\n"
)
if value.count(old_import) != 1:
    raise SystemExit("projection store object-reference import mismatch")
value = value.replace(old_import, new_import)
marker = '''    def _migrate_or_validate(self) -> None:
'''
method = '''    @staticmethod
    def _validate_object_admission_payload_record(
        conn: sqlite3.Connection, row: sqlite3.Row
    ) -> None:
        """Validate an immutable A2b reference without reactivating current rights."""

        if row["payload_bytes"] is not None:
            raise AuthorityPersistenceError(
                "object admission payload cannot embed bytes"
            )
        if row["object_admission_id"] is None:
            raise AuthorityPersistenceError(
                "object admission payload lacks admission identity"
            )
        admission_id = ObjectAdmissionId.parse(
            str(row["object_admission_id"])
        )
        validate_sha256_digest(
            str(row["payload_digest"]), field="object_payload_digest"
        )
        admission = conn.execute(
            "SELECT a.blob_digest,v.state,v.event_id "
            "FROM object_admissions a "
            "JOIN object_admission_versions v "
            "ON v.admission_id=a.admission_id "
            "AND v.lifecycle_version=1 "
            "WHERE a.admission_id=?",
            (str(admission_id),),
        ).fetchone()
        if admission is None or str(admission["state"]) != "ACTIVE":
            raise AuthorityPersistenceError(
                "object admission payload lacks immutable activation authority"
            )
        if admission["event_id"] is None:
            raise AuthorityPersistenceError(
                "object admission activation lacks authority event identity"
            )
        if str(admission["blob_digest"]) != str(row["payload_digest"]):
            raise AuthorityPersistenceError(
                "object payload digest differs from admitted blob"
            )
        contract = conn.execute(
            "SELECT schema_version,payload_mode,contract_version,"
            "canonicalizer_implementation_version "
            "FROM payload_schema_contracts WHERE contract_digest=?",
            (str(row["schema_contract_digest"]),),
        ).fetchone()
        if contract is None:
            raise AuthorityPersistenceError(
                "object payload schema contract is missing"
            )
        if (
            str(contract["schema_version"]) != str(row["schema_version"])
            or str(contract["payload_mode"])
            != PayloadMode.OBJECT_ADMISSION.value
            or str(contract["contract_version"])
            != str(row["schema_contract_version"])
            or str(contract["canonicalizer_implementation_version"])
            != str(row["canonicalizer_implementation_version"])
        ):
            raise AuthorityPersistenceError(
                "object payload does not match its immutable schema contract"
            )

'''
if value.count(marker) != 1:
    raise SystemExit("projection store validator insertion mismatch")
path.write_text(value.replace(marker, method + marker), encoding="utf-8")
