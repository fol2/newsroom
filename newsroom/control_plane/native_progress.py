"""Native revision continuation in the existing append-only Control Plane ledger.

Load once at daemon start; append only changed state. Source bytes are retained
once, never copied into each stage receipt. No additional database or schema.
The journal records work, not evidence/publication authority.
"""

from __future__ import annotations

import json
import sqlite3
from dataclasses import asdict, dataclass

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.effective_revision import EffectiveRevisionIdentity

from .corpus import CorpusAuthorityBinding, CorpusIngestUnit
from .store import append_ledger

LAND = "NATIVE_REVISION_LANDED"
STATE = "NATIVE_REVISION_PROGRESS"
PORTFOLIO = "NATIVE_SOURCE_PORTFOLIO"

_RETRIEVAL_FIELDS = ("retrieval_binding", "retrieval_rights_inventory")


def _pair_digest(facts: dict) -> str | None:
    if not all(key in facts for key in _RETRIEVAL_FIELDS):
        return None
    return digest_bytes(canonical_json_bytes({key: facts[key] for key in _RETRIEVAL_FIELDS}))


def _state_digest(stage: str, facts: dict, pair_digest: str | None) -> str:
    # The verified pair digest avoids re-serialising large referenced values on
    # replay. Keep every other fact inline, including embedding evidence.
    remaining = {key: value for key, value in facts.items()
                 if pair_digest is None or key not in _RETRIEVAL_FIELDS}
    return digest_bytes(canonical_json_bytes(
        {"stage": stage, "facts": remaining, "retrieval_pair_digest": pair_digest}
    ))


@dataclass(frozen=True, slots=True)
class _ProgressRecord:
    seq: int
    payload_digest: str
    ordinal: int
    pair_digest: str | None
    state_digest: str

    def reference(self) -> dict:
        return {"seq": self.seq, "payload_digest": self.payload_digest,
                "ordinal": self.ordinal}


def _unit(value: dict, bodies: dict[str, str]) -> CorpusIngestUnit:
    value = dict(value)
    value["body"] = bodies.setdefault(value["body"], value["body"])
    value["effective_revision"] = EffectiveRevisionIdentity(**value["effective_revision"])
    authority = dict(value["authority"])
    authority["records"] = tuple(authority["records"])
    value["authority"] = CorpusAuthorityBinding(**authority)
    return CorpusIngestUnit(**value)


class NativeRevisionJournal:
    def __init__(self, connection: sqlite3.Connection) -> None:
        self._connection = connection
        self.units: dict[str, tuple[CorpusIngestUnit, ...]] = {}
        self.progress: dict[str, dict] = {}
        self._records: dict[str, _ProgressRecord] = {}
        self.portfolio: tuple[dict, ...] = ()
        self.observations: dict[str, tuple[str, str, str, str]] = {}
        # ponytail: one startup replay; an indexed snapshot is warranted only
        # after measured native history makes this bounded-kind scan material.
        for seq, kind, raw, payload_digest in connection.execute(
            "SELECT seq,kind,payload_json,payload_digest FROM ledger "
            "WHERE kind IN (?,?,?) ORDER BY seq", (LAND, STATE, PORTFOLIO),
        ):
            if digest_bytes(raw.encode()) != payload_digest:
                raise ValueError("native progress ledger payload differs")
            value = json.loads(raw)
            if canonical_json_bytes(value).decode() != raw:
                raise ValueError("native progress ledger is not canonical")
            self._apply(kind, value, seq=seq, payload_digest=payload_digest)

    def _apply(self, kind: str, value: dict, *, seq: int, payload_digest: str) -> None:
        if kind == LAND:
            # Chunk receipts repeat the full source body. Share exact-equal text
            # in this revision only; retain and validate the original ledger bytes.
            bodies: dict[str, str] = {}
            units = tuple(_unit(item, bodies) for item in value["units"])
            self._validate_units(units)
            revision_id = units[0].revision_id
            if value["revision_id"] != revision_id:
                raise ValueError("native progress revision identity differs")
            prior = self.units.get(revision_id)
            if prior is not None and prior != units:
                raise ValueError("native progress retained units changed")
            self.units[revision_id] = units
        elif kind == STATE:
            revision_id = value["revision_id"]
            if revision_id not in self.units:
                raise ValueError("native progress lacks its landed revision")
            previous = self._records.get(revision_id)
            ordinal = value["ordinal"]
            if type(ordinal) is not int or ordinal != (previous.ordinal if previous else 0) + 1:
                raise ValueError("native progress ordinal has a gap")
            facts = dict(value["facts"])
            if "retrieval_facts_ref" in value:
                reference = value["retrieval_facts_ref"]
                if (
                    type(reference) is not dict
                    or previous is None or previous.pair_digest is None
                    or type(reference.get("seq")) is not int
                    or type(reference.get("ordinal")) is not int
                    or reference != previous.reference()
                    or reference["seq"] >= seq
                    or any(key in facts for key in _RETRIEVAL_FIELDS)
                ):
                    raise ValueError("native retrieval facts reference differs")
                prior_facts = self.progress[revision_id]["facts"]
                facts.update({key: prior_facts[key] for key in _RETRIEVAL_FIELDS})
                pair_digest = previous.pair_digest
            else:
                pair_digest = _pair_digest(facts)
            logical = {key: item for key, item in value.items() if key != "retrieval_facts_ref"}
            logical["facts"] = facts
            self._records[revision_id] = _ProgressRecord(
                seq, payload_digest, ordinal, pair_digest,
                _state_digest(value["stage"], facts, pair_digest),
            )
            self.progress[revision_id] = logical
        elif kind == PORTFOLIO:
            self.portfolio = tuple(value["sources"])
            for source in self.portfolio:
                for raw in source.get("observations", ()):
                    observation = tuple(raw)
                    if len(observation) != 4 or any(type(item) is not str or not item for item in observation):
                        raise ValueError("native source observation reference differs")
                    # Retain the first exact observation, also after a page
                    # leaves the feed. This is a reference, not a second copy.
                    self.observations.setdefault(observation[1], observation)

    @staticmethod
    def _validate_units(units: tuple[CorpusIngestUnit, ...]) -> None:
        if not units or any(type(unit) is not CorpusIngestUnit or unit.authority is None for unit in units):
            raise ValueError("native progress needs exact governed units")
        first = units[0]
        if (
            tuple(unit.chunk_ordinal for unit in units) != tuple(range(1, first.chunk_count + 1))
            or any(unit.revision_id != first.revision_id or unit.chunk_count != first.chunk_count for unit in units)
            or any(not unit.proving_run_id.startswith("native-source:") for unit in units)
            or any(unit.revision_digest != first.revision_digest for unit in units)
        ):
            raise ValueError("native progress revision chunk coverage differs")

    def _retain(self, kind: str, value: dict) -> None:
        # Existing store writer/chain semantics own the atomic append. Apply
        # only after commit; an interrupted commit is reconstructed on reopen.
        try:
            append_ledger(self._connection, kind, value)
            seq, payload_digest = self._connection.execute(
                "SELECT seq,payload_digest FROM ledger WHERE seq=last_insert_rowid()"
            ).fetchone()
            self._connection.commit()
        except BaseException:
            self._connection.rollback()
            raise
        self._apply(kind, value, seq=seq, payload_digest=payload_digest)

    def land(self, units: tuple[CorpusIngestUnit, ...]) -> None:
        units = tuple(sorted(units, key=lambda unit: unit.chunk_ordinal))
        self._validate_units(units)
        revision_id = units[0].revision_id
        prior = self.units.get(revision_id)
        if prior is not None:
            # Re-observation HTTP/access receipts may change; retained source
            # and representation identities may not silently change here.
            if tuple((unit.ingest_id, unit.authority.representation_id) for unit in prior) != tuple((unit.ingest_id, unit.authority.representation_id) for unit in units):
                raise ValueError("native progress revision was rebound")
            return
        self._retain(LAND, {"revision_id": revision_id, "units": [asdict(unit) for unit in units]})

    def advance(self, revision_id: str, *, stage: str, facts: dict) -> dict:
        if revision_id not in self.units or not stage:
            raise ValueError("native progress stage lacks a landed revision")
        previous = self._records.get(revision_id)
        facts = json.loads(canonical_json_bytes(facts))
        pair_digest = _pair_digest(facts)
        logical = {"revision_id": revision_id, "ordinal": previous.ordinal if previous else 0,
                   "stage": stage, "facts": facts}
        if previous and _state_digest(stage, facts, pair_digest) == previous.state_digest:
            # Public logical facts may have been mutated by a caller. Restore
            # the detached, verified input instead of returning that mutation.
            self.progress[revision_id] = logical
            return logical
        logical["ordinal"] += 1
        encoded = logical
        if (
            previous and pair_digest is not None and pair_digest == previous.pair_digest
            and _pair_digest(self.progress[revision_id]["facts"]) == previous.pair_digest
        ):
            encoded = {**logical,
                       "facts": {key: item for key, item in facts.items() if key not in _RETRIEVAL_FIELDS},
                       "retrieval_facts_ref": previous.reference()}
        self._retain(STATE, encoded)
        return self.progress[revision_id]

    def sources(self, dispositions: tuple) -> None:
        values = tuple({
            "source_id": item.source_id, "status": item.status,
            "reason_code": item.reason_code,
            "revision_ids": sorted({unit.revision_id for unit in item.units}),
            "observations": [list(value) for value in getattr(item, "observations", ())],
            "item_holds": [list(value) for value in getattr(item, "item_holds", ())],
        } for item in dispositions)
        if values != self.portfolio:
            self._retain(PORTFOLIO, {"sources": list(values)})
