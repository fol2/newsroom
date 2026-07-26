from __future__ import annotations

from dataclasses import dataclass
import json
from pathlib import Path
from typing import Any

from jsonschema import Draft202012Validator

from newsroom.authority.canonical import canonical_json_bytes, digest_bytes
from newsroom.authority.types import UtcTimestamp, require_token

from .models import (
    IntegratedFixtureV2BindingId,
    RelationContractError,
    RelationEndpoint,
    RelationPredicate,
    RelationProducer,
    RelationProducerKind,
    RelationProposalId,
    RelationProposalRequest,
    RelationRecordType,
    RelationTemporalScope,
)


_FIXTURE_ROOT = Path(__file__).resolve().parent.parent / "fixtures"
_FIXTURE_PATH = _FIXTURE_ROOT / "integrated_fixture_v2.json"
_SCHEMA_PATH = _FIXTURE_ROOT / "integrated_fixture_v2.schema.json"


INTEGRATED_FIXTURE_V2_BINDING_ID = IntegratedFixtureV2BindingId.parse(
    "00000000-0000-4000-8000-000000002101"
)


@dataclass(frozen=True, slots=True)
class IntegratedFixtureV2Passage:
    passage_id: str
    revision_id: str | None
    language: str
    text: str
    expected_lifecycle: str
    eligible_for_relation_evidence: bool

    def __post_init__(self) -> None:
        require_token(self.passage_id, field="fixture_passage_id")
        if self.language not in {"en-GB", "zh-HK"}:
            raise RelationContractError("fixture passage language is unsupported")
        if (
            not isinstance(self.text, str)
            or not self.text
            or self.text != self.text.strip()
        ):
            raise RelationContractError("fixture passage text must be canonical")
        if self.expected_lifecycle not in {"ACTIVE", "TOMBSTONED"}:
            raise RelationContractError("fixture passage lifecycle is invalid")
        if not isinstance(self.eligible_for_relation_evidence, bool):
            raise RelationContractError(
                "fixture passage evidence eligibility must be boolean"
            )

    @property
    def canonical_bytes(self) -> bytes:
        return self.text.encode("utf-8")

    @property
    def blob_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)


@dataclass(frozen=True, slots=True)
class IntegratedFixtureV2RelationTemplate:
    subject: RelationEndpoint
    predicate: RelationPredicate
    object: RelationEndpoint
    temporal_scope: RelationTemporalScope
    producer: RelationProducer
    statement: str
    uncertainties: tuple[str, ...]
    evidence_passage_ids: tuple[str, ...]

    def request(
        self,
        *,
        proposal_id: RelationProposalId,
        fixture_binding_id: IntegratedFixtureV2BindingId,
        idempotency_key: str,
    ) -> RelationProposalRequest:
        return RelationProposalRequest(
            proposal_id=proposal_id,
            fixture_binding_id=fixture_binding_id,
            subject=self.subject,
            predicate=self.predicate,
            object=self.object,
            temporal_scope=self.temporal_scope,
            evidence_passage_ids=self.evidence_passage_ids,
            producer=self.producer,
            statement=self.statement,
            uncertainties=self.uncertainties,
            idempotency_key=idempotency_key,
        )


@dataclass(frozen=True, slots=True)
class IntegratedFixtureV2:
    fixture_id: str
    schema_version: str
    fixture_family: str
    canonical_bytes: bytes
    passages: tuple[IntegratedFixtureV2Passage, ...]
    aliases: tuple[tuple[str, str], ...]
    relation: IntegratedFixtureV2RelationTemplate
    distractor_predicate: RelationPredicate
    prior_candidate_version_id: str

    def __post_init__(self) -> None:
        if self.schema_version != "integrated_fixture_v2":
            raise RelationContractError("fixture schema identity is invalid")
        if self.fixture_family != "integrated_fixture_v2":
            raise RelationContractError("fixture family identity is invalid")
        if not isinstance(self.canonical_bytes, bytes) or not self.canonical_bytes:
            raise RelationContractError("fixture canonical bytes are required")
        passage_ids = tuple(item.passage_id for item in self.passages)
        if passage_ids != tuple(sorted(set(passage_ids))):
            raise RelationContractError(
                "fixture passages must be sorted and globally unique"
            )
        languages = {language for language, _ in self.aliases}
        if languages != {"en-GB", "zh-HK"}:
            raise RelationContractError(
                "fixture must retain English and Hong Kong Traditional Chinese aliases"
            )
        eligible = {
            item.passage_id
            for item in self.passages
            if item.eligible_for_relation_evidence
            and item.expected_lifecycle == "ACTIVE"
        }
        if not set(self.relation.evidence_passage_ids).issubset(eligible):
            raise RelationContractError(
                "fixture relation evidence must use active eligible passages"
            )
        if self.distractor_predicate is not RelationPredicate.SAME_EVENT_AS:
            raise RelationContractError(
                "fixture proposal-only distractor predicate is invalid"
            )

    @property
    def manifest_digest(self) -> str:
        return digest_bytes(self.canonical_bytes)

    @property
    def passage_by_id(self) -> dict[str, IntegratedFixtureV2Passage]:
        return {item.passage_id: item for item in self.passages}

    @property
    def expected_passage_digests(self) -> dict[str, str]:
        return {item.passage_id: item.blob_digest for item in self.passages}

    @property
    def tombstoned_negative_passage_id(self) -> str:
        matches = [
            item.passage_id
            for item in self.passages
            if item.expected_lifecycle == "TOMBSTONED"
        ]
        if len(matches) != 1:
            raise RelationContractError(
                "fixture requires one exact tombstoned negative passage"
            )
        return matches[0]


def _read_json(path: Path) -> Any:
    try:
        return json.loads(path.read_text(encoding="utf-8"))
    except (OSError, UnicodeError, json.JSONDecodeError) as exc:
        raise RelationContractError(f"cannot load fixture contract: {path.name}") from exc


def load_integrated_fixture_v2() -> IntegratedFixtureV2:
    schema = _read_json(_SCHEMA_PATH)
    value = _read_json(_FIXTURE_PATH)
    validator = Draft202012Validator(schema)
    errors = sorted(validator.iter_errors(value), key=lambda item: list(item.path))
    if errors:
        first = errors[0]
        location = "/".join(str(item) for item in first.path) or "<root>"
        raise RelationContractError(
            f"integrated_fixture_v2 schema failure at {location}: {first.message}"
        )
    if not isinstance(value, dict):
        raise RelationContractError("fixture root must be an object")

    passages: list[IntegratedFixtureV2Passage] = []
    revisions = value["revisions"]
    for revision in revisions:
        revision_id = str(revision["source_revision_id"])
        for passage in revision["passages"]:
            passages.append(
                IntegratedFixtureV2Passage(
                    passage_id=str(passage["passage_id"]),
                    revision_id=revision_id,
                    language=str(passage["language"]),
                    text=str(passage["text"]),
                    expected_lifecycle=str(passage["expected_lifecycle"]),
                    eligible_for_relation_evidence=bool(
                        passage["eligible_for_relation_evidence"]
                    ),
                )
            )
    for passage in value["negative_passages"]:
        passages.append(
            IntegratedFixtureV2Passage(
                passage_id=str(passage["passage_id"]),
                revision_id=None,
                language=str(passage["language"]),
                text=str(passage["text"]),
                expected_lifecycle=str(passage["expected_lifecycle"]),
                eligible_for_relation_evidence=bool(
                    passage["eligible_for_relation_evidence"]
                ),
            )
        )

    relation = value["governed_relation"]
    template = IntegratedFixtureV2RelationTemplate(
        subject=RelationEndpoint(
            RelationRecordType(str(relation["subject_type"])),
            str(relation["subject_id"]),
        ),
        predicate=RelationPredicate(str(relation["predicate"])),
        object=RelationEndpoint(
            RelationRecordType(str(relation["object_type"])),
            str(relation["object_id"]),
        ),
        temporal_scope=RelationTemporalScope(
            valid_from=UtcTimestamp.parse(str(relation["valid_from"])),
            valid_until=(
                None
                if relation["valid_until"] is None
                else UtcTimestamp.parse(str(relation["valid_until"]))
            ),
        ),
        producer=RelationProducer(
            kind=RelationProducerKind(str(relation["producer_kind"])),
            producer_id=str(relation["producer_id"]),
            producer_version=str(relation["producer_version"]),
            rule_version=str(relation["rule_version"]),
        ),
        statement=str(relation["statement"]),
        uncertainties=tuple(sorted(str(item) for item in relation["uncertainties"])),
        evidence_passage_ids=tuple(
            sorted(str(item) for item in relation["evidence_passage_ids"])
        ),
    )
    aliases = tuple(
        sorted(
            (
                str(item["language"]),
                str(item["value"]),
            )
            for item in value["formal_process"]["aliases"]
        )
    )
    return IntegratedFixtureV2(
        fixture_id=str(value["fixture_id"]),
        schema_version=str(value["schema_version"]),
        fixture_family=str(value["fixture_family"]),
        canonical_bytes=canonical_json_bytes(value),
        passages=tuple(sorted(passages, key=lambda item: item.passage_id)),
        aliases=aliases,
        relation=template,
        distractor_predicate=RelationPredicate(
            str(value["proposal_only_distractor"]["predicate"])
        ),
        prior_candidate_version_id=str(value["prior_candidate_version_id"]),
    )


INTEGRATED_FIXTURE_V2 = load_integrated_fixture_v2()
INTEGRATED_FIXTURE_V2_DIGEST = INTEGRATED_FIXTURE_V2.manifest_digest


__all__ = [
    "INTEGRATED_FIXTURE_V2",
    "INTEGRATED_FIXTURE_V2_BINDING_ID",
    "INTEGRATED_FIXTURE_V2_DIGEST",
    "IntegratedFixtureV2",
    "IntegratedFixtureV2Passage",
    "IntegratedFixtureV2RelationTemplate",
    "load_integrated_fixture_v2",
]
