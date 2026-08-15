"""Derive retained Increment 8 substantive-review evidence from GitHub authority."""

from __future__ import annotations

import argparse
import json
import os
import re
import sys
import urllib.error
import urllib.request
from collections.abc import Mapping, Sequence
from pathlib import Path
from typing import Any

from newsroom.increment8.admission import AdmissionError, SubstantiveReviewEvidence

_GRAPHQL = """
query($owner:String!,$name:String!,$oid:GitObjectID!){
  repository(owner:$owner,name:$name){
    object(oid:$oid){
      ... on Commit{
        associatedPullRequests(first:10){
          totalCount
          nodes{
            number merged headRefOid mergeCommit{oid}
            reviews(last:100){
              totalCount
              nodes{databaseId state submittedAt author{login} commit{oid}}
            }
            comments(last:100){
              totalCount
              nodes{databaseId createdAt body author{login}}
            }
            reviewThreads(first:100){
              totalCount pageInfo{hasNextPage}
              nodes{isResolved comments(first:1){nodes{body}}}
            }
          }
        }
      }
    }
  }
}
"""
_PROVIDER = "chatgpt-codex-connector"


class Increment8ReviewEvidenceError(ValueError):
    """GitHub review authority differs from the exact merged source."""


def _mapping(value: object, field: str) -> Mapping[str, Any]:
    if not isinstance(value, Mapping):
        raise Increment8ReviewEvidenceError(f"{field} differs")
    return value


def _nodes(value: object, field: str) -> list[Mapping[str, Any]]:
    container = _mapping(value, field)
    nodes = container.get("nodes")
    if not isinstance(nodes, list) or any(
        not isinstance(item, Mapping) for item in nodes
    ):
        raise Increment8ReviewEvidenceError(f"{field} differs")
    return list(nodes)


def build_review_evidence(
    payload: Mapping[str, Any], *, repository: str, merge_sha: str
) -> SubstantiveReviewEvidence:
    try:
        owner, name = repository.split("/", 1)
    except ValueError as exc:
        raise Increment8ReviewEvidenceError("repository differs") from exc
    repository_value = _mapping(payload.get("data"), "data").get("repository")
    commit = _mapping(_mapping(repository_value, "repository").get("object"), "commit")
    associated = _mapping(
        commit.get("associatedPullRequests"), "associated pull requests"
    )
    pull_requests = _nodes(associated, "associated pull requests")
    matches = [
        item
        for item in pull_requests
        if item.get("merged") is True
        and isinstance(item.get("mergeCommit"), Mapping)
        and item["mergeCommit"].get("oid") == merge_sha
    ]
    if len(matches) != 1:
        raise Increment8ReviewEvidenceError("exact merged pull request differs")
    pull_request = matches[0]
    head_sha = pull_request.get("headRefOid")
    reviews = _mapping(pull_request.get("reviews"), "reviews")
    if not isinstance(reviews.get("totalCount"), int) or reviews["totalCount"] > 100:
        raise Increment8ReviewEvidenceError("review inventory is incomplete")
    authorities = [
        {
            **item,
            "authorityKind": "PULL_REQUEST_REVIEW",
            "authorityAt": item.get("submittedAt"),
        }
        for item in _nodes(reviews, "reviews")
        if isinstance(item.get("author"), Mapping)
        and item["author"].get("login") == _PROVIDER
        and isinstance(item.get("commit"), Mapping)
        and item["commit"].get("oid") == head_sha
        and item.get("state") in {"APPROVED", "COMMENTED"}
    ]
    comments = _mapping(pull_request.get("comments"), "review comments")
    if not isinstance(comments.get("totalCount"), int) or comments["totalCount"] > 100:
        raise Increment8ReviewEvidenceError("review comment inventory is incomplete")
    reviewed_prefix = str(head_sha)[:10]
    reviewed_pattern = re.compile(
        rf"\*\*Reviewed commit:\*\*\s*`{re.escape(reviewed_prefix)}`"
    )
    authorities.extend(
        {
            **item,
            "authorityKind": "ISSUE_COMMENT",
            "authorityAt": item.get("createdAt"),
        }
        for item in _nodes(comments, "review comments")
        if isinstance(item.get("author"), Mapping)
        and item["author"].get("login") == _PROVIDER
        and isinstance(item.get("body"), str)
        and "Didn't find any major issues." in item["body"]
        and reviewed_pattern.search(item["body"]) is not None
    )
    if not authorities:
        raise Increment8ReviewEvidenceError("exact-head substantive review is absent")
    exact_review = max(authorities, key=lambda item: str(item.get("authorityAt", "")))

    threads = _mapping(pull_request.get("reviewThreads"), "review threads")
    page_info = _mapping(threads.get("pageInfo"), "review thread page info")
    if page_info.get("hasNextPage") is not False:
        raise Increment8ReviewEvidenceError("review thread inventory is incomplete")
    thread_nodes = _nodes(threads, "review threads")
    if threads.get("totalCount") != len(thread_nodes):
        raise Increment8ReviewEvidenceError("review thread inventory differs")
    unresolved = [item for item in thread_nodes if item.get("isResolved") is False]
    p1 = 0
    p2 = 0
    other = 0
    for thread in unresolved:
        comments = _nodes(thread.get("comments"), "review thread comments")
        body = str(comments[0].get("body", "")) if comments else ""
        if "P1 Badge" in body:
            p1 += 1
        elif "P2 Badge" in body:
            p2 += 1
        else:
            other += 1
    try:
        return SubstantiveReviewEvidence.build(
            repository=f"{owner}/{name}",
            pull_request_number=pull_request["number"],
            merge_sha=merge_sha,
            reviewed_head_sha=head_sha,
            review_provider=_PROVIDER,
            review_authority_kind=exact_review["authorityKind"],
            review_database_id=exact_review["databaseId"],
            review_submitted_at=exact_review["authorityAt"],
            unresolved_thread_count=len(unresolved),
            p1_finding_count=p1,
            material_p2_finding_count=p2,
            other_unresolved_thread_count=other,
        )
    except (KeyError, TypeError, AdmissionError) as exc:
        raise Increment8ReviewEvidenceError("review evidence differs") from exc


def fetch_review_evidence(
    *, repository: str, merge_sha: str, token: str
) -> SubstantiveReviewEvidence:
    owner, separator, name = repository.partition("/")
    if not separator or not owner or not name or not token:
        raise Increment8ReviewEvidenceError("GitHub authority input differs")
    request = urllib.request.Request(
        "https://api.github.com/graphql",
        data=json.dumps(
            {
                "query": _GRAPHQL,
                "variables": {"owner": owner, "name": name, "oid": merge_sha},
            },
            separators=(",", ":"),
        ).encode("utf-8"),
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {token}",
            "Content-Type": "application/json",
            "User-Agent": "newsroom-increment8-review-evidence",
            "X-GitHub-Api-Version": "2022-11-28",
        },
        method="POST",
    )
    try:
        with urllib.request.urlopen(request, timeout=30) as response:
            payload = json.load(response)
    except (OSError, urllib.error.URLError, json.JSONDecodeError) as exc:
        raise Increment8ReviewEvidenceError("GitHub review query failed") from exc
    if not isinstance(payload, Mapping) or payload.get("errors"):
        raise Increment8ReviewEvidenceError("GitHub review query differs")
    return build_review_evidence(payload, repository=repository, merge_sha=merge_sha)


def main(argv: Sequence[str] | None = None) -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--repository", required=True)
    parser.add_argument("--merge-sha", required=True)
    parser.add_argument("--output", required=True, type=Path)
    arguments = parser.parse_args(sys.argv[1:] if argv is None else argv)
    try:
        evidence = fetch_review_evidence(
            repository=arguments.repository,
            merge_sha=arguments.merge_sha,
            token=os.environ.get("GITHUB_TOKEN", ""),
        )
        arguments.output.parent.mkdir(parents=True, exist_ok=True)
        if arguments.output.exists():
            raise Increment8ReviewEvidenceError("review evidence output already exists")
        arguments.output.write_bytes(evidence.canonical_bytes)
    except (OSError, ValueError) as exc:
        print(f"EVIDENCE_MISMATCH:increment8-review:{exc}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
