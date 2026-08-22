"""Source-safe gold fixtures for NewsroomCombinedTemporalExtractionV1."""

from __future__ import annotations

from dataclasses import dataclass
from typing import Any

from newsroom.authority.canonical import digest_bytes
from newsroom.graphiti_adapter.combined_temporal_extraction import (
    CombinedTemporalFailureCode,
    SourceRevisionInput,
)
from newsroom.graphiti_adapter.identity import MAX_EPISODE_BYTES

PAIR_BODY = (
    "The Legislative Council asked about the Technology and Living curriculum."
)
REFERENCE_TIME = "2026-08-21T00:00:00Z"
INGESTED_AT = "2026-08-22T12:00:00Z"
GROUP_ID = "newsroom-combined-temporal-v1"
SOURCE_ID = "newsroom-fixture"


def _pair_entities() -> list[dict[str, Any]]:
    return [
        {
            "local_id": 0,
            "name": "Legislative Council",
            "entity_type_id": 0,
            "evidence_segment_ids": [0],
        },
        {
            "local_id": 1,
            "name": "Technology and Living curriculum",
            "entity_type_id": 0,
            "evidence_segment_ids": [0],
        },
    ]


def _pair_fact(
    *,
    valid_at: str | None,
    invalid_at: str | None,
    fact: str = PAIR_BODY,
) -> dict[str, Any]:
    return {
        "source_local_id": 0,
        "target_local_id": 1,
        "relation_type": "ASKED_ABOUT",
        "fact": fact,
        "valid_at": valid_at,
        "invalid_at": invalid_at,
        "evidence_segment_ids": [0],
    }


def _revision(
    body: str,
    *,
    revision_id: str,
    reference_time: str = REFERENCE_TIME,
    ingested_at: str = INGESTED_AT,
    predecessor_revision_id: str | None = None,
    predecessor_body: str | None = None,
) -> SourceRevisionInput:
    return SourceRevisionInput(
        body=body,
        revision_id=revision_id,
        source_id=SOURCE_ID,
        item_key=revision_id,
        representation_digest=digest_bytes(body.encode("utf-8")),
        published_at=reference_time,
        updated_at=None,
        observed_at=reference_time,
        ingested_at=ingested_at,
        predecessor_revision_id=predecessor_revision_id,
        predecessor_body=predecessor_body,
        group_id=GROUP_ID,
    )


def long_retained_chunk() -> str:
    seed = (PAIR_BODY + " ").encode("utf-8")
    return (seed * ((MAX_EPISODE_BYTES // len(seed)) + 1))[:MAX_EPISODE_BYTES].decode(
        "ascii"
    )


@dataclass(frozen=True, slots=True)
class GoldFixture:
    name: str
    revision: SourceRevisionInput
    gold: dict[str, Any]


@dataclass(frozen=True, slots=True)
class MalformedCase:
    name: str
    revision: SourceRevisionInput
    payload: object
    failure_code: CombinedTemporalFailureCode


_PAIR_REVISION = _revision(PAIR_BODY, revision_id="rev-pair-current")

FIXTURES: tuple[GoldFixture, ...] = (
    GoldFixture(
        "pair-current",
        _PAIR_REVISION,
        {"entities": _pair_entities(), "facts": [_pair_fact(valid_at=None, invalid_at=None)]},
    ),
    GoldFixture(
        "several-relations",
        _revision(
            "The Legislative Council asked the Education Bureau about the "
            "Technology and Living curriculum. The Education Bureau administers "
            "the Technology and Living curriculum.",
            revision_id="rev-several",
        ),
        {
            "entities": [
                {
                    "local_id": 0,
                    "name": "Legislative Council",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0],
                },
                {
                    "local_id": 1,
                    "name": "Education Bureau",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0, 1],
                },
                {
                    "local_id": 2,
                    "name": "Technology and Living curriculum",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0, 1],
                },
            ],
            "facts": [
                {
                    "source_local_id": 0,
                    "target_local_id": 1,
                    "relation_type": "ASKED",
                    "fact": (
                        "The Legislative Council asked the Education Bureau about "
                        "the Technology and Living curriculum."
                    ),
                    "valid_at": None,
                    "invalid_at": None,
                    "evidence_segment_ids": [0],
                },
                {
                    "source_local_id": 1,
                    "target_local_id": 2,
                    "relation_type": "ADMINISTERS",
                    "fact": (
                        "The Education Bureau administers the Technology and "
                        "Living curriculum."
                    ),
                    "valid_at": None,
                    "invalid_at": None,
                    "evidence_segment_ids": [1],
                },
            ],
        },
    ),
    GoldFixture(
        "explicit-valid-at",
        _revision(
            "On 20 August 2026 the Legislative Council asked about the "
            "Technology and Living curriculum.",
            revision_id="rev-valid-at",
        ),
        {
            "entities": _pair_entities(),
            "facts": [
                _pair_fact(
                    valid_at="2026-08-20T00:00:00Z",
                    invalid_at=None,
                    fact=(
                        "On 20 August 2026 the Legislative Council asked about "
                        "the Technology and Living curriculum."
                    ),
                )
            ],
        },
    ),
    GoldFixture(
        "explicit-invalid-at",
        _revision(
            "The Legislative Council asked about the Technology and Living "
            "curriculum until 31 March 2026.",
            revision_id="rev-invalid-at",
        ),
        {
            "entities": _pair_entities(),
            "facts": [
                _pair_fact(
                    valid_at=None,
                    invalid_at="2026-03-31T00:00:00Z",
                    fact=(
                        "The Legislative Council asked about the Technology and "
                        "Living curriculum until 31 March 2026."
                    ),
                )
            ],
        },
    ),
    GoldFixture(
        "relative-date",
        _revision(
            "Yesterday the Legislative Council asked about the Technology and "
            "Living curriculum.",
            revision_id="rev-relative",
        ),
        {
            "entities": _pair_entities(),
            "facts": [
                _pair_fact(
                    valid_at="2026-08-20T00:00:00Z",
                    invalid_at=None,
                    fact=(
                        "Yesterday the Legislative Council asked about the "
                        "Technology and Living curriculum."
                    ),
                )
            ],
        },
    ),
    GoldFixture(
        "null-temporal",
        _revision(
            "The Education Bureau administers the Technology and Living curriculum.",
            revision_id="rev-null-temporal",
        ),
        {
            "entities": [
                {
                    "local_id": 0,
                    "name": "Education Bureau",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0],
                },
                {
                    "local_id": 1,
                    "name": "Technology and Living curriculum",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0],
                },
            ],
            "facts": [
                {
                    "source_local_id": 0,
                    "target_local_id": 1,
                    "relation_type": "ADMINISTERS",
                    "fact": (
                        "The Education Bureau administers the Technology and "
                        "Living curriculum."
                    ),
                    "valid_at": None,
                    "invalid_at": None,
                    "evidence_segment_ids": [0],
                }
            ],
        },
    ),
    GoldFixture(
        "zero-result",
        _revision(
            "A routine administrative reminder with no named people, "
            "organisations, places or policies.",
            revision_id="rev-zero",
        ),
        {"entities": [], "facts": []},
    ),
    GoldFixture(
        "long-8192",
        _revision(long_retained_chunk(), revision_id="rev-long-8192"),
        {"entities": _pair_entities(), "facts": [_pair_fact(valid_at=None, invalid_at=None)]},
    ),
    GoldFixture(
        "correction-revision",
        _revision(
            "Correction: the Legislative Council asked about Design and Applied "
            "Technology.",
            revision_id="rev-correction",
            predecessor_revision_id="rev-pair-current",
            predecessor_body=PAIR_BODY,
        ),
        {
            "entities": [
                {
                    "local_id": 0,
                    "name": "Legislative Council",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0],
                },
                {
                    "local_id": 1,
                    "name": "Design and Applied Technology",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0],
                },
            ],
            "facts": [
                {
                    "source_local_id": 0,
                    "target_local_id": 1,
                    "relation_type": "ASKED_ABOUT",
                    "fact": (
                        "the Legislative Council asked about Design and Applied "
                        "Technology."
                    ),
                    "valid_at": None,
                    "invalid_at": None,
                    "evidence_segment_ids": [0],
                }
            ],
        },
    ),
    GoldFixture(
        "same-name",
        _revision(
            "At the morning hearing, Lee asked the Bureau about the curriculum. "
            "At the afternoon session, Lee answered the Bureau.",
            revision_id="rev-same-name",
        ),
        {
            "entities": [
                {
                    "local_id": 0,
                    "name": "Lee",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0],
                },
                {
                    "local_id": 1,
                    "name": "Bureau",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0, 1],
                },
                {
                    "local_id": 2,
                    "name": "Lee",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [1],
                },
            ],
            "facts": [
                {
                    "source_local_id": 0,
                    "target_local_id": 1,
                    "relation_type": "ASKED_ABOUT",
                    "fact": "Lee asked the Bureau about the curriculum.",
                    "valid_at": None,
                    "invalid_at": None,
                    "evidence_segment_ids": [0],
                },
                {
                    "source_local_id": 2,
                    "target_local_id": 1,
                    "relation_type": "ANSWERED",
                    "fact": "Lee answered the Bureau.",
                    "valid_at": None,
                    "invalid_at": None,
                    "evidence_segment_ids": [1],
                },
            ],
        },
    ),
    GoldFixture(
        "no-implied-relation",
        _revision(
            "Ms Chan attended the briefing. The Education Bureau hosted the briefing.",
            revision_id="rev-no-implied",
        ),
        {
            "entities": [
                {
                    "local_id": 0,
                    "name": "Ms Chan",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0],
                },
                {
                    "local_id": 1,
                    "name": "Education Bureau",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [1],
                },
                {
                    "local_id": 2,
                    "name": "briefing",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0, 1],
                },
            ],
            "facts": [
                {
                    "source_local_id": 0,
                    "target_local_id": 2,
                    "relation_type": "ATTENDED",
                    "fact": "Ms Chan attended the briefing.",
                    "valid_at": None,
                    "invalid_at": None,
                    "evidence_segment_ids": [0],
                },
                {
                    "source_local_id": 1,
                    "target_local_id": 2,
                    "relation_type": "HOSTED",
                    "fact": "The Education Bureau hosted the briefing.",
                    "valid_at": None,
                    "invalid_at": None,
                    "evidence_segment_ids": [1],
                },
            ],
        },
    ),
)


def fixture(name: str) -> GoldFixture:
    matches = [item for item in FIXTURES if item.name == name]
    if len(matches) != 1:
        raise KeyError(name)
    return matches[0]


MALFORMED_CASES: tuple[MalformedCase, ...] = (
    MalformedCase(
        "duplicate-local-id",
        _PAIR_REVISION,
        {
            "entities": _pair_entities()
            + [
                {
                    "local_id": 0,
                    "name": "Education Bureau",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0],
                }
            ],
            "facts": [_pair_fact(valid_at=None, invalid_at=None)],
        },
        CombinedTemporalFailureCode.IDENTITY_INVALID,
    ),
    MalformedCase(
        "missing-target",
        _PAIR_REVISION,
        {
            "entities": _pair_entities()[:1],
            "facts": [_pair_fact(valid_at=None, invalid_at=None)],
        },
        CombinedTemporalFailureCode.IDENTITY_INVALID,
    ),
    MalformedCase(
        "same-source-target",
        _PAIR_REVISION,
        {
            "entities": _pair_entities()[:1],
            "facts": [
                {
                    "source_local_id": 0,
                    "target_local_id": 0,
                    "relation_type": "ASKED_ABOUT",
                    "fact": PAIR_BODY,
                    "valid_at": None,
                    "invalid_at": None,
                    "evidence_segment_ids": [0],
                }
            ],
        },
        CombinedTemporalFailureCode.IDENTITY_INVALID,
    ),
    MalformedCase(
        "orphan-entity",
        _PAIR_REVISION,
        {"entities": _pair_entities(), "facts": []},
        CombinedTemporalFailureCode.IDENTITY_INVALID,
    ),
    MalformedCase(
        "segment-out-of-range",
        _PAIR_REVISION,
        {
            "entities": [
                {
                    "local_id": 0,
                    "name": "Legislative Council",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [9],
                },
                {
                    "local_id": 1,
                    "name": "Technology and Living curriculum",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0],
                },
            ],
            "facts": [_pair_fact(valid_at=None, invalid_at=None)],
        },
        CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
    ),
    MalformedCase(
        "duplicate-evidence-ids",
        _PAIR_REVISION,
        {
            "entities": [
                {
                    "local_id": 0,
                    "name": "Legislative Council",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0, 0],
                },
                {
                    "local_id": 1,
                    "name": "Technology and Living curriculum",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0],
                },
            ],
            "facts": [_pair_fact(valid_at=None, invalid_at=None)],
        },
        CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
    ),
    MalformedCase(
        "bad-timestamp",
        _PAIR_REVISION,
        {
            "entities": _pair_entities(),
            "facts": [_pair_fact(valid_at="not-a-date", invalid_at=None)],
        },
        CombinedTemporalFailureCode.TEMPORAL_INVALID,
    ),
    MalformedCase(
        "valid-after-invalid",
        _PAIR_REVISION,
        {
            "entities": _pair_entities(),
            "facts": [
                _pair_fact(
                    valid_at="2026-08-21T00:00:00Z",
                    invalid_at="2026-08-20T00:00:00Z",
                )
            ],
        },
        CombinedTemporalFailureCode.TEMPORAL_INVALID,
    ),
    MalformedCase(
        "extra-keys",
        _PAIR_REVISION,
        {
            "entities": _pair_entities(),
            "facts": [_pair_fact(valid_at=None, invalid_at=None)],
            "commentary": "planning residue",
        },
        CombinedTemporalFailureCode.MALFORMED_OBJECT,
    ),
    MalformedCase(
        "wrapping-prose",
        _PAIR_REVISION,
        "Here is the JSON:\n" + '{"entities":[],"facts":[]}',
        CombinedTemporalFailureCode.MALFORMED_OBJECT,
    ),
    MalformedCase(
        "bad-relation-type",
        _PAIR_REVISION,
        {
            "entities": _pair_entities(),
            "facts": [
                {
                    "source_local_id": 0,
                    "target_local_id": 1,
                    "relation_type": "asked about",
                    "fact": PAIR_BODY,
                    "valid_at": None,
                    "invalid_at": None,
                    "evidence_segment_ids": [0],
                }
            ],
        },
        CombinedTemporalFailureCode.MALFORMED_OBJECT,
    ),
    MalformedCase(
        "unknown-entity-type",
        _PAIR_REVISION,
        {
            "entities": [
                {
                    "local_id": 0,
                    "name": "Legislative Council",
                    "entity_type_id": 999,
                    "evidence_segment_ids": [0],
                },
                {
                    "local_id": 1,
                    "name": "Technology and Living curriculum",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0],
                },
            ],
            "facts": [_pair_fact(valid_at=None, invalid_at=None)],
        },
        CombinedTemporalFailureCode.IDENTITY_INVALID,
    ),
    MalformedCase(
        "duplicate-facts",
        _PAIR_REVISION,
        {
            "entities": _pair_entities(),
            "facts": [
                _pair_fact(valid_at=None, invalid_at=None),
                _pair_fact(valid_at=None, invalid_at=None),
            ],
        },
        CombinedTemporalFailureCode.IDENTITY_INVALID,
    ),
    MalformedCase(
        "ungrounded-2030",
        _PAIR_REVISION,
        {
            "entities": _pair_entities(),
            "facts": [_pair_fact(valid_at="2030-01-01T00:00:00Z", invalid_at=None)],
        },
        CombinedTemporalFailureCode.TEMPORAL_INVALID,
    ),
    MalformedCase(
        "relative-date-misresolved",
        _revision(
            "Yesterday the Legislative Council asked about the Technology and "
            "Living curriculum.",
            revision_id="rev-relative-misresolved",
        ),
        {
            "entities": _pair_entities(),
            "facts": [
                _pair_fact(
                    valid_at="2030-01-01T00:00:00Z",
                    invalid_at=None,
                    fact=(
                        "Yesterday the Legislative Council asked about the "
                        "Technology and Living curriculum."
                    ),
                )
            ],
        },
        CombinedTemporalFailureCode.TEMPORAL_INVALID,
    ),
    MalformedCase(
        "assertion-and-correction",
        _revision(
            "The Legislative Council asked about the Technology and Living "
            "curriculum. Correction: the Legislative Council asked about "
            "Design and Applied Technology.",
            revision_id="rev-span-correction",
        ),
        {
            "entities": _pair_entities(),
            "facts": [
                {
                    "source_local_id": 0,
                    "target_local_id": 1,
                    "relation_type": "ASKED_ABOUT",
                    "fact": PAIR_BODY,
                    "valid_at": None,
                    "invalid_at": None,
                    "evidence_segment_ids": [0, 1],
                }
            ],
        },
        CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
    ),
    MalformedCase(
        "same-fact-text-different-endpoints",
        _revision(
            "The Legislative Council asked the Education Bureau about the "
            "Technology and Living curriculum. The Education Bureau administers "
            "the Technology and Living curriculum.",
            revision_id="rev-same-fact-text",
        ),
        {
            "entities": [
                {
                    "local_id": 0,
                    "name": "Legislative Council",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0],
                },
                {
                    "local_id": 1,
                    "name": "Education Bureau",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0],
                },
                {
                    "local_id": 2,
                    "name": "Technology and Living curriculum",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0],
                },
            ],
            "facts": [
                {
                    "source_local_id": 0,
                    "target_local_id": 1,
                    "relation_type": "ASKED",
                    "fact": (
                        "The Legislative Council asked the Education Bureau about "
                        "the Technology and Living curriculum."
                    ),
                    "valid_at": None,
                    "invalid_at": None,
                    "evidence_segment_ids": [0],
                },
                {
                    "source_local_id": 0,
                    "target_local_id": 2,
                    "relation_type": "ASKED",
                    "fact": (
                        "The Legislative Council asked the Education Bureau about "
                        "the Technology and Living curriculum."
                    ),
                    "valid_at": None,
                    "invalid_at": None,
                    "evidence_segment_ids": [0],
                },
            ],
        },
        CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
    ),
    MalformedCase(
        "duplicate-facts-key",
        _PAIR_REVISION,
        '{"entities":[],"facts":[{"bad":true}],"facts":[]}',
        CombinedTemporalFailureCode.MALFORMED_OBJECT,
    ),
    MalformedCase(
        "missing-temporal-keys",
        _PAIR_REVISION,
        {
            "entities": _pair_entities(),
            "facts": [
                {
                    "source_local_id": 0,
                    "target_local_id": 1,
                    "relation_type": "ASKED_ABOUT",
                    "fact": PAIR_BODY,
                    "evidence_segment_ids": [0],
                }
            ],
        },
        CombinedTemporalFailureCode.MALFORMED_OBJECT,
    ),
    MalformedCase(
        "float-entity-type",
        _PAIR_REVISION,
        {
            "entities": [
                {
                    "local_id": 0,
                    "name": "Legislative Council",
                    "entity_type_id": 0.0,
                    "evidence_segment_ids": [0],
                },
                {
                    "local_id": 1,
                    "name": "Technology and Living curriculum",
                    "entity_type_id": 0,
                    "evidence_segment_ids": [0],
                },
            ],
            "facts": [_pair_fact(valid_at=None, invalid_at=None)],
        },
        CombinedTemporalFailureCode.IDENTITY_INVALID,
    ),
    MalformedCase(
        "lowercase-correction-span",
        _revision(
            "The Legislative Council asked about the Technology and Living "
            "curriculum. correction: the Legislative Council asked about "
            "Design and Applied Technology.",
            revision_id="rev-span-correction-lower",
        ),
        {
            "entities": _pair_entities(),
            "facts": [
                {
                    "source_local_id": 0,
                    "target_local_id": 1,
                    "relation_type": "ASKED_ABOUT",
                    "fact": PAIR_BODY,
                    "valid_at": None,
                    "invalid_at": None,
                    "evidence_segment_ids": [0, 1],
                }
            ],
        },
        CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
    ),
    MalformedCase(
        "same-fact-two-relations",
        _PAIR_REVISION,
        {
            "entities": _pair_entities(),
            "facts": [
                _pair_fact(valid_at=None, invalid_at=None),
                {
                    "source_local_id": 0,
                    "target_local_id": 1,
                    "relation_type": "ABOUT",
                    "fact": PAIR_BODY,
                    "valid_at": None,
                    "invalid_at": None,
                    "evidence_segment_ids": [0],
                },
            ],
        },
        CombinedTemporalFailureCode.EVIDENCE_UNRESOLVED,
    ),
    MalformedCase(
        "list-payload",
        _PAIR_REVISION,
        [],
        CombinedTemporalFailureCode.MALFORMED_OBJECT,
    ),
)


__all__ = [
    "FIXTURES",
    "GROUP_ID",
    "INGESTED_AT",
    "GoldFixture",
    "MALFORMED_CASES",
    "MalformedCase",
    "PAIR_BODY",
    "REFERENCE_TIME",
    "fixture",
    "long_retained_chunk",
]
