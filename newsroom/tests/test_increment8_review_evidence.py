from __future__ import annotations

import pytest

from newsroom.increment8.admission import SubstantiveReviewEvidence
from scripts.sdlc.increment8_review_evidence import (
    Increment8ReviewEvidenceError,
    build_review_evidence,
)

_MERGE = "a" * 40
_HEAD = "b" * 40


def _payload(*, resolved: bool = True, reviewed_head: str = _HEAD):
    return {
        "data": {
            "repository": {
                "object": {
                    "associatedPullRequests": {
                        "totalCount": 1,
                        "nodes": [
                            {
                                "number": 484,
                                "merged": True,
                                "headRefOid": _HEAD,
                                "mergeCommit": {"oid": _MERGE},
                                "reviews": {
                                    "totalCount": 1,
                                    "nodes": [
                                        {
                                            "databaseId": 987,
                                            "state": "COMMENTED",
                                            "submittedAt": "2042-01-05T00:00:00.000000Z",
                                            "author": {
                                                "login": "chatgpt-codex-connector"
                                            },
                                            "commit": {"oid": reviewed_head},
                                        }
                                    ],
                                },
                                "reviewThreads": {
                                    "totalCount": 1,
                                    "pageInfo": {"hasNextPage": False},
                                    "nodes": [
                                        {
                                            "isResolved": resolved,
                                            "comments": {
                                                "nodes": [{"body": "P1 Badge"}]
                                            },
                                        }
                                    ],
                                },
                            }
                        ],
                    }
                }
            }
        }
    }


def test_review_evidence_binds_exact_merge_head_review_and_zero_open_threads() -> None:
    evidence = build_review_evidence(
        _payload(), repository="fol2/newsroom", merge_sha=_MERGE
    )
    assert (
        SubstantiveReviewEvidence.from_canonical_bytes(evidence.canonical_bytes)
        == evidence
    )
    assert evidence.merge_sha == _MERGE
    assert evidence.reviewed_head_sha == _HEAD


def test_review_evidence_rejects_unresolved_findings_or_foreign_head() -> None:
    with pytest.raises(Increment8ReviewEvidenceError, match="review evidence"):
        build_review_evidence(
            _payload(resolved=False),
            repository="fol2/newsroom",
            merge_sha=_MERGE,
        )
    with pytest.raises(Increment8ReviewEvidenceError, match="exact-head"):
        build_review_evidence(
            _payload(reviewed_head="c" * 40),
            repository="fol2/newsroom",
            merge_sha=_MERGE,
        )
