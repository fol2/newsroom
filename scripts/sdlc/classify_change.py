from __future__ import annotations

import argparse
from dataclasses import dataclass
from functools import lru_cache
import hashlib
import json
from pathlib import Path
import re
import subprocess
import sys
from typing import Iterable, Sequence

from .contracts import ContractError, SdlcContract, load_contract


SCHEMA_VERSION = "newsroom.sdlc.route.v1"
RISK_CLASSIFIER_VERSION = "sdlc-risk-v1"
_PATH_RISKS = {
    "documentation": "R0_DOCUMENTATION",
    "local_code": "R1_LOCAL_CODE",
    "clustering": "R1_LOCAL_CODE",
    "stateful_contract": "R2_STATEFUL_CONTRACT",
    "contract_control": "R3_EXTERNAL_SERVICE_SECURITY",
    "external_service_security": "R3_EXTERNAL_SERVICE_SECURITY",
    "release_operational": "R4_RELEASE_OPERATIONAL",
}


class GitRouteError(RuntimeError):
    """Raised when exact Git identities or a diff cannot be resolved."""


@dataclass(frozen=True, order=True)
class ChangedPath:
    path: str
    status: str = "M"
    old_path: str | None = None

    def classified_paths(self) -> tuple[str, ...]:
        if self.old_path is None or self.old_path == self.path:
            return (self.path,)
        return tuple(sorted({self.old_path, self.path}))


def canonical_json_bytes(value: object) -> bytes:
    """Return the repository's deterministic JSON bytes for routing manifests."""

    return json.dumps(
        value,
        ensure_ascii=False,
        allow_nan=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")


def sha256_identity(value: object) -> str:
    return "sha256:" + hashlib.sha256(canonical_json_bytes(value)).hexdigest()


@lru_cache(maxsize=512)
def _compile_repository_glob(pattern: str) -> re.Pattern[str]:
    """Compile a Git-style path glob where `**/` matches zero or more segments."""

    expression: list[str] = ["^"]
    index = 0
    while index < len(pattern):
        char = pattern[index]
        if char == "*":
            if index + 1 < len(pattern) and pattern[index + 1] == "*":
                index += 2
                if index < len(pattern) and pattern[index] == "/":
                    expression.append("(?:.*/)?")
                    index += 1
                else:
                    expression.append(".*")
                continue
            expression.append("[^/]*")
        elif char == "?":
            expression.append("[^/]")
        else:
            expression.append(re.escape(char))
        index += 1
    expression.append("$")
    return re.compile("".join(expression))


def matches_repository_glob(path: str, pattern: str) -> bool:
    if path.startswith("/") or "\\" in path or "/../" in f"/{path}/":
        return False
    return _compile_repository_glob(pattern).fullmatch(path) is not None


def _matching_groups(contract: SdlcContract, path: str) -> tuple[str, ...]:
    return tuple(
        sorted(
            group
            for group, patterns in contract.path_groups.items()
            if any(matches_repository_glob(path, pattern) for pattern in patterns)
        )
    )


def _service_tests(repo_root: Path) -> tuple[str, ...]:
    tests = sorted(
        path.relative_to(repo_root).as_posix()
        for path in (repo_root / "newsroom" / "tests").glob(
            "test_projection_*_neo4j_service.py"
        )
        if path.is_file()
    )
    return tuple(tests)


def classify_paths(
    contract: SdlcContract,
    changes: Iterable[ChangedPath],
    *,
    base_sha: str,
    head_sha: str,
    base_tree_sha: str,
    head_tree_sha: str,
) -> dict[str, object]:
    ranks = contract.risk_rank
    selected_risk = "R0_DOCUMENTATION"
    reasons: set[str] = set()
    clustering_required = False
    normalized_changes = tuple(sorted(set(changes)))

    if not normalized_changes:
        reasons.add("no_changes")

    for change in normalized_changes:
        for path in change.classified_paths():
            groups = _matching_groups(contract, path)
            if not groups:
                risk = contract.unknown_path_risk
                reasons.add(f"unknown_path:{path}:{risk}")
                if ranks[risk] > ranks[selected_risk]:
                    selected_risk = risk
                continue
            for group in groups:
                if group == "clustering":
                    clustering_required = True
                risk = _PATH_RISKS.get(group)
                if risk is None:
                    risk = str(contract.classification["classifier_error"])
                    reasons.add(f"unknown_path_group:{group}:{risk}")
                else:
                    reasons.add(f"path:{path}:{group}:{risk}")
                if ranks[risk] > ranks[selected_risk]:
                    selected_risk = risk

    core_tests = ("newsroom/tests",)
    service_required = contract.service_required(selected_risk)
    service_tests = _service_tests(contract.repo_root) if service_required else ()
    manifest = {
        "core_tests": list(core_tests),
        "service_tests": list(service_tests),
        "sentinels": list(contract.sentinels),
    }
    route: dict[str, object] = {
        "schema_version": SCHEMA_VERSION,
        "contract_version": contract.contract_version,
        "base_sha": base_sha,
        "head_sha": head_sha,
        "base_tree_sha": base_tree_sha,
        "head_tree_sha": head_tree_sha,
        "risk_tier": selected_risk,
        "reasons": sorted(reasons),
        "core_required": True,
        "service_required": service_required,
        "clustering_required": clustering_required,
        "owner_authority_required": contract.owner_authority_required(selected_risk),
        "core_tests": list(core_tests),
        "service_tests": list(service_tests),
        "sentinels": list(contract.sentinels),
        "selected_test_manifest_digest": sha256_identity(manifest),
    }
    return route


def _git(repo_root: Path, *arguments: str) -> bytes:
    completed = subprocess.run(
        ("git", *arguments),
        cwd=repo_root,
        check=False,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
    )
    if completed.returncode != 0:
        message = completed.stderr.decode("utf-8", errors="replace").strip()
        raise GitRouteError(f"git {' '.join(arguments)} failed: {message}")
    return completed.stdout


def resolve_commit(repo_root: Path, reference: str) -> str:
    value = _git(repo_root, "rev-parse", "--verify", f"{reference}^{{commit}}").decode().strip()
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise GitRouteError(f"reference did not resolve to a full commit SHA: {reference}")
    return value


def resolve_tree(repo_root: Path, commit_sha: str) -> str:
    value = _git(repo_root, "rev-parse", "--verify", f"{commit_sha}^{{tree}}").decode().strip()
    if re.fullmatch(r"[0-9a-f]{40}", value) is None:
        raise GitRouteError(f"commit did not resolve to a full tree SHA: {commit_sha}")
    return value


def parse_name_status(payload: bytes) -> tuple[ChangedPath, ...]:
    fields = payload.split(b"\0")
    if fields and fields[-1] == b"":
        fields.pop()
    changes: list[ChangedPath] = []
    index = 0
    while index < len(fields):
        status = fields[index].decode("ascii", errors="strict")
        index += 1
        if index >= len(fields):
            raise GitRouteError("truncated git name-status output")
        if status.startswith(("R", "C")):
            if index + 1 >= len(fields):
                raise GitRouteError("truncated git rename/copy output")
            old_path = fields[index].decode("utf-8", errors="strict")
            new_path = fields[index + 1].decode("utf-8", errors="strict")
            index += 2
            changes.append(ChangedPath(new_path, status, old_path))
        else:
            path = fields[index].decode("utf-8", errors="strict")
            index += 1
            changes.append(ChangedPath(path, status))
    return tuple(changes)


def changed_paths(repo_root: Path, base_sha: str, head_sha: str) -> tuple[ChangedPath, ...]:
    output = _git(
        repo_root,
        "diff",
        "--name-status",
        "-z",
        "--find-renames",
        f"{base_sha}...{head_sha}",
        "--",
    )
    return parse_name_status(output)


def build_git_route(
    repo_root: str | Path, *, base_reference: str, head_reference: str
) -> dict[str, object]:
    root = Path(repo_root).resolve()
    contract = load_contract(root)
    base_sha = resolve_commit(root, base_reference)
    head_sha = resolve_commit(root, head_reference)
    return classify_paths(
        contract,
        changed_paths(root, base_sha, head_sha),
        base_sha=base_sha,
        head_sha=head_sha,
        base_tree_sha=resolve_tree(root, base_sha),
        head_tree_sha=resolve_tree(root, head_sha),
    )


def _parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(description="Classify an exact Newsroom change")
    parser.add_argument("--repo-root", default=".")
    parser.add_argument("--base", required=True, help="exact base commit or resolvable ref")
    parser.add_argument("--head", required=True, help="exact head commit or resolvable ref")
    parser.add_argument("--output", help="write route JSON to this path")
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    arguments = _parser().parse_args(argv)
    try:
        route = build_git_route(
            arguments.repo_root,
            base_reference=arguments.base,
            head_reference=arguments.head,
        )
    except (ContractError, GitRouteError, OSError, UnicodeError) as exc:
        print(f"CLASSIFIER_ERROR:{exc}", file=sys.stderr)
        return 2
    rendered = canonical_json_bytes(route).decode("utf-8") + "\n"
    if arguments.output:
        Path(arguments.output).write_text(rendered, encoding="utf-8")
    else:
        sys.stdout.write(rendered)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
