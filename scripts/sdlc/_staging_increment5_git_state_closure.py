#!/usr/bin/env python3
"""Materialize the final Git-local-state closure for Increment 5A.

Disposable staging helper. It must never be merged into PR #255 or main.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_HEAD = "969ed0c1fd8666a38616fd68aa6e6a3c5ef92f6e"
CONTRACT_DIGEST = (
    "sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c"
)
PLAN_DIGEST = (
    "sha256:c9d169c46a939573ffc6563704adfae973655f6394293ce591ec689f76a30959"
)

VALIDATOR = ROOT / "scripts/sdlc/increment5_profile_validator.py"
TESTS = ROOT / "newsroom/tests/test_increment5a_profile_semantic_envelope.py"
DECISION = ROOT / (
    "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"
)
EVALUATION = ROOT / (
    "docs/evaluation/2026-08-02-increment-5-retrieval-evaluation-plan-v1.md"
)
OPERATIONS = ROOT / "docs/operations/increment-5-production-retrieval-contract.md"
MANIFEST = ROOT / "increment5a-git-state-closure-manifest.json"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def update_validator() -> None:
    text = VALIDATOR.read_text(encoding="utf-8")
    text = replace_once(
        text,
        """    def command(self, *arguments: str) -> list[str]:
        self.require_unchanged()
        return [str(self.path), "-C", str(_REPOSITORY_ROOT), *arguments]
""",
        """    def command(self, *arguments: str) -> list[str]:
        self.require_unchanged()
        return [
            str(self.path),
            "-C",
            str(_REPOSITORY_ROOT),
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            *arguments,
        ]
""",
        label="closed Git command",
    )
    text = replace_once(
        text,
        """        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
""",
        """        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
""",
        label="replacement-object environment",
    )
    VALIDATOR.write_text(text, encoding="utf-8")


def update_tests() -> None:
    text = TESTS.read_text(encoding="utf-8")

    replacement_test = r'''


def test_git_replace_ref_cannot_substitute_materialized_source(
    tmp_path: Path,
) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)
    marker = tmp_path / "replacement-profile-executed"
    replacement_source = (
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\n"
        "raise RuntimeError('replacement profile blob executed')\n"
    ).encode("utf-8")
    original_blob = _git_text(
        clone,
        "rev-parse",
        "HEAD:newsroom/increment5/profiles.py",
    )
    hashed = subprocess.run(
        ["git", "-C", str(clone), "hash-object", "-w", "--stdin"],
        input=replacement_source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    assert hashed.returncode == 0, hashed.stderr.decode("utf-8")
    replacement_blob = hashed.stdout.decode("ascii", errors="strict").strip()
    replaced = subprocess.run(
        ["git", "-C", str(clone), "replace", original_blob, replacement_blob],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    assert replaced.returncode == 0, replaced.stderr.decode("utf-8")
    assert _code_identity(clone) == (clone_commit, clone_tree)
    assert _git_text(
        clone,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    ) == ""

    raw_archive = subprocess.run(
        [
            "git",
            "-C",
            str(clone),
            "archive",
            "--format=tar",
            clone_commit,
            "--",
            "newsroom/increment5/profiles.py",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    assert raw_archive.returncode == 0, raw_archive.stderr.decode("utf-8")
    assert b"replacement profile blob executed" in raw_archive.stdout

    completed = _run_isolated_bytes(
        canonical_json_bytes(_fixture_manifest()),
        root=clone,
        expected_commit=clone_commit,
        expected_tree=clone_tree,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    assert not marker.exists()
    receipt = json.loads(completed.stdout.decode("utf-8"))
    assert receipt["code_commit_sha"] == clone_commit
    assert receipt["code_tree_sha"] == clone_tree
    assert receipt["validation_code_origin"] == "CACHE_FREE_EXACT_GIT_ARCHIVE"


def test_fsmonitor_hook_cannot_hide_tracked_checkout_change(
    tmp_path: Path,
) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)
    hook = tmp_path / "lying-fsmonitor-v2"
    hook.write_bytes(b"#!/bin/sh\nprintf 'unchanged-token\\000'\n")
    hook.chmod(0o755)
    for name, value in (
        ("core.fsmonitor", str(hook)),
        ("core.fsmonitorHookVersion", "2"),
    ):
        configured = subprocess.run(
            ["git", "-C", str(clone), "config", name, value],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
        )
        assert configured.returncode == 0, configured.stderr.decode("utf-8")

    assert _git_text(
        clone,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    ) == ""
    profile_source = clone / "newsroom/increment5/profiles.py"
    profile_source.write_text(
        profile_source.read_text(encoding="utf-8")
        + "\nraise RuntimeError('fsmonitor-hidden change executed')\n",
        encoding="utf-8",
    )
    assert _git_text(
        clone,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    ) == ""
    assert _git_text(
        clone,
        "-c",
        "core.fsmonitor=false",
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    ) != ""

    completed = _run_isolated_bytes(
        canonical_json_bytes(_fixture_manifest()),
        root=clone,
        expected_commit=clone_commit,
        expected_tree=clone_tree,
    )
    assert completed.returncode == 2
    assert completed.stderr == (
        b"increment5 profile validation failed: "
        b"tracked repository checkout differs from HEAD\n"
    )
    assert completed.stdout == b""
'''
    anchor = "\ndef test_archive_limit_kills_the_producer_before_overflow_reaches_disk(\n"
    text = replace_once(
        text,
        anchor,
        replacement_test + anchor,
        label="Git replacement and fsmonitor regressions",
    )

    text = replace_once(
        text,
        """    assert '_TRUSTED_GIT_EXECUTABLE = Path("/usr/bin/git")' in source
    assert "shutil.which" not in source
""",
        """    assert '_TRUSTED_GIT_EXECUTABLE = Path("/usr/bin/git")' in source
    assert '"--no-replace-objects"' in source
    assert '"GIT_NO_REPLACE_OBJECTS": "1"' in source
    assert '"core.fsmonitor=false"' in source
    assert "shutil.which" not in source
""",
        label="Git-state source assertions",
    )
    TESTS.write_text(text, encoding="utf-8")


def update_docs() -> None:
    decision = DECISION.read_text(encoding="utf-8")
    decision = replace_once(
        decision,
        """binary's device, inode, mode, ownership, size, modification time, and SHA-256
identity are captured and rechecked before and after every operation.
""",
        """binary's device, inode, mode, ownership, size, modification time, and SHA-256
identity are captured and rechecked before and after every operation. Every Git
command also uses `--no-replace-objects`, `GIT_NO_REPLACE_OBJECTS=1`, and the
command-line override `core.fsmonitor=false`; repository replacement refs cannot
alter resolved or archived objects, and a repository-local fsmonitor cannot hide
tracked checkout changes.
""",
        label="decision Git-local-state controls",
    )
    DECISION.write_text(decision, encoding="utf-8")

    evaluation = EVALUATION.read_text(encoding="utf-8")
    evaluation = replace_once(
        evaluation,
        """fixed root-owned `/usr/bin/git` binary, never caller `PATH`; its identity is
rechecked around every operation, and archive bytes are streamed through a hard
64 MiB pre-write cap that terminates the producer on overflow. The receipt's
""",
        """fixed root-owned `/usr/bin/git` binary, never caller `PATH`; its identity is
rechecked around every operation. Replacement objects are disabled through both
the global Git option and environment, repository fsmonitor is disabled through
an exact command-line override, and archive bytes are streamed through a hard
64 MiB pre-write cap that terminates the producer on overflow. The receipt's
""",
        label="evaluation Git-local-state controls",
    )
    EVALUATION.write_text(evaluation, encoding="utf-8")

    operations = OPERATIONS.read_text(encoding="utf-8")
    operations = replace_once(
        operations,
        """other-writable; the binary identity is rechecked around every operation.
Archive stdout and stderr are streamed concurrently, the producer is terminated
""",
        """other-writable; the binary identity is rechecked around every operation. Every
Git invocation disables replacement objects and overrides
`core.fsmonitor=false`, so local replacement refs cannot alter archive bytes and
an fsmonitor hook cannot conceal tracked checkout drift. Archive stdout and
stderr are streamed concurrently, the producer is terminated
""",
        label="operations Git-local-state controls",
    )
    OPERATIONS.write_text(operations, encoding="utf-8")


def main() -> None:
    update_validator()
    update_tests()
    update_docs()
    changed_paths = [
        DECISION.relative_to(ROOT).as_posix(),
        EVALUATION.relative_to(ROOT).as_posix(),
        OPERATIONS.relative_to(ROOT).as_posix(),
        TESTS.relative_to(ROOT).as_posix(),
        VALIDATOR.relative_to(ROOT).as_posix(),
    ]
    manifest = {
        "changed_paths": sorted(changed_paths),
        "contract_digest_unchanged": CONTRACT_DIGEST,
        "evaluation_plan_digest_unchanged": PLAN_DIGEST,
        "git_local_state_boundary": {
            "core_fsmonitor_override": "false",
            "replacement_objects_disabled_by_environment": True,
            "replacement_objects_disabled_by_global_option": True,
        },
        "schema_version": "newsroom.increment5a.git-state-closure.v1",
        "source_head": SOURCE_HEAD,
        "trusted_git_and_streaming_boundaries_unchanged": True,
    }
    MANIFEST.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
