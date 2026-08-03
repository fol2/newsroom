#!/usr/bin/env python3
"""Materialize the pinned-Git, streaming-capped Increment 5A validator.

This helper is staging-only. The product candidate is rebuilt separately as one
helper-free replacement commit over the fixed Increment 5A base.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SOURCE_HEAD = "26afbee4c9e180a5925603041a7a4af783f3357c"
VALIDATOR = ROOT / "scripts/sdlc/increment5_profile_validator.py"
TEST = ROOT / "newsroom/tests/test_increment5a_profile_semantic_envelope.py"
DECISION = ROOT / (
    "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"
)
OPERATIONS = ROOT / "docs/operations/increment-5-production-retrieval-contract.md"
EVALUATION = ROOT / (
    "docs/evaluation/2026-08-02-increment-5-retrieval-evaluation-plan-v1.md"
)
OUTPUT = ROOT / "increment5a-pinned-git-stream-manifest.json"


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label} replacement count differs: {count}")
    return text.replace(old, new, 1)


def _require_source_boundary() -> None:
    paths = [VALIDATOR, TEST, DECISION, OPERATIONS, EVALUATION]
    relative = [str(path.relative_to(ROOT)) for path in paths]
    ancestor = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "merge-base",
            "--is-ancestor",
            SOURCE_HEAD,
            "HEAD",
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    unchanged = subprocess.run(
        [
            "git",
            "-C",
            str(ROOT),
            "diff",
            "--quiet",
            SOURCE_HEAD,
            "--",
            *relative,
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=10,
    )
    if ancestor.returncode != 0 or unchanged.returncode != 0:
        raise RuntimeError("staging source differs from reviewed predecessor")


def _transform_validator(text: str) -> str:
    text = _replace_once(
        text,
        """from contextlib import contextmanager
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import shutil
import subprocess
import sys
import tarfile
import tempfile
from typing import Any, Iterator
""",
        """from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import stat
import subprocess
import sys
import tarfile
import tempfile
import time
from typing import Any, Iterator
""",
        "validator imports",
    )
    text = _replace_once(
        text,
        """_MAX_ARCHIVE_BYTES = 67_108_864
_MAX_ARCHIVE_MEMBER_BYTES = 16_777_216
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
""",
        """_MAX_ARCHIVE_BYTES = 67_108_864
_MAX_ARCHIVE_MEMBER_BYTES = 16_777_216
_MAX_GIT_EXECUTABLE_BYTES = 268_435_456
_ARCHIVE_READ_CHUNK_BYTES = 65_536
_ARCHIVE_TIMEOUT_SECONDS = 30.0
_PROCESS_STOP_TIMEOUT_SECONDS = 2.0
_TRUSTED_GIT_CANDIDATES = (Path("/usr/bin/git"), Path("/bin/git"))
_TRUSTED_SYSTEM_PATH = "/usr/bin:/bin"
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
""",
        "validator constants",
    )

    old_git_boundary = '''def _git_executable() -> Path:
    raw = shutil.which("git")
    if raw is None:
        raise ProfileInputError("Git is unavailable for exact code-tree validation")
    path = Path(raw).resolve()
    if not path.is_file():
        raise ProfileInputError("Git executable is not a regular file")
    try:
        path.relative_to(_REPOSITORY_ROOT)
    except ValueError:
        return path
    raise ProfileInputError("Git executable cannot come from the repository checkout")


def _git_environment(git: Path) -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": str(git.parent),
    }


def _run_git(git: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            [str(git), "-C", str(_REPOSITORY_ROOT), *arguments],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
            env=_git_environment(git),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProfileInputError("cannot inspect the exact Git code tree") from exc
    if (
        completed.returncode != 0
        or len(completed.stdout) > _MAX_GIT_OUTPUT_BYTES
        or len(completed.stderr) > _MAX_GIT_OUTPUT_BYTES
    ):
        raise ProfileInputError("cannot inspect the exact Git code tree")
    return completed.stdout
'''
    new_git_boundary = '''def _root_owned_non_writable(path: Path) -> bool:
    try:
        candidates = (path, *path.parents)
        for candidate in candidates:
            metadata = candidate.stat()
            if metadata.st_uid != 0:
                return False
            if metadata.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                return False
    except OSError:
        return False
    return True


def _digest_trusted_file(path: Path) -> str:
    try:
        metadata = path.stat()
        if (
            not stat.S_ISREG(metadata.st_mode)
            or metadata.st_size <= 0
            or metadata.st_size > _MAX_GIT_EXECUTABLE_BYTES
        ):
            raise ProfileInputError("trusted Git executable has an invalid size")
        digest = hashlib.sha256()
        remaining = metadata.st_size
        with path.open("rb") as source:
            while remaining:
                chunk = source.read(min(1_048_576, remaining))
                if not chunk:
                    raise ProfileInputError("trusted Git executable is truncated")
                digest.update(chunk)
                remaining -= len(chunk)
            if source.read(1):
                raise ProfileInputError("trusted Git executable changed while reading")
    except OSError as exc:
        raise ProfileInputError("cannot digest the trusted Git executable") from exc
    return "sha256:" + digest.hexdigest()


def _git_executable() -> tuple[Path, str]:
    if os.name != "posix":
        raise ProfileInputError("exact code-tree validation requires POSIX")
    seen: set[Path] = set()
    for candidate in _TRUSTED_GIT_CANDIDATES:
        try:
            path = candidate.resolve(strict=True)
        except OSError:
            continue
        if path in seen:
            continue
        seen.add(path)
        try:
            path.relative_to(_REPOSITORY_ROOT)
        except ValueError:
            pass
        else:
            continue
        try:
            metadata = path.stat()
        except OSError:
            continue
        if not stat.S_ISREG(metadata.st_mode) or not os.access(path, os.X_OK):
            continue
        if not _root_owned_non_writable(path):
            continue
        return path, _digest_trusted_file(path)
    raise ProfileInputError(
        "no root-owned non-writable system Git executable is available"
    )


def _git_environment(git: Path) -> dict[str, str]:
    return {
        "GIT_ATTR_NOSYSTEM": "1",
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_LITERAL_PATHSPECS": "1",
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": _TRUSTED_SYSTEM_PATH,
    }


def _git_command(git: Path, *arguments: str) -> list[str]:
    git_directory = _REPOSITORY_ROOT / ".git"
    if not git_directory.is_dir():
        raise ProfileInputError("repository Git directory is unavailable")
    return [
        str(git),
        f"--git-dir={git_directory}",
        f"--work-tree={_REPOSITORY_ROOT}",
        "-c",
        "core.attributesFile=/dev/null",
        "-c",
        "core.fsmonitor=false",
        "-c",
        "core.hooksPath=/dev/null",
        "-c",
        "core.untrackedCache=false",
        "-c",
        "protocol.file.allow=never",
        *arguments,
    ]


def _run_git(git: Path, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            _git_command(git, *arguments),
            stdin=subprocess.DEVNULL,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            close_fds=True,
            timeout=10,
            env=_git_environment(git),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProfileInputError("cannot inspect the exact Git code tree") from exc
    if (
        completed.returncode != 0
        or len(completed.stdout) > _MAX_GIT_OUTPUT_BYTES
        or len(completed.stderr) > _MAX_GIT_OUTPUT_BYTES
    ):
        raise ProfileInputError("cannot inspect the exact Git code tree")
    return completed.stdout
'''
    text = _replace_once(
        text,
        old_git_boundary,
        new_git_boundary,
        "trusted Git boundary",
    )

    text = _replace_once(
        text,
        '''def _require_exact_code_tree(
    expected_commit: str,
    expected_tree: str,
) -> tuple[Path, str, str]:
    """Bind HEAD and reject tracked changes before repository imports exist."""

    git = _git_executable()
''',
        '''def _require_exact_code_tree(
    expected_commit: str,
    expected_tree: str,
) -> tuple[Path, str, str, str]:
    """Bind HEAD and reject tracked changes before repository imports exist."""

    git, git_digest = _git_executable()
''',
        "exact tree return type",
    )
    text = _replace_once(
        text,
        "    return git, actual_commit, actual_tree\n\n\ndef _write_git_archive",
        "    return git, git_digest, actual_commit, actual_tree\n\n\ndef _stop_process(process: subprocess.Popen[bytes]) -> None:\n    if process.poll() is not None:\n        return\n    try:\n        process.terminate()\n    except ProcessLookupError:\n        return\n    try:\n        process.wait(timeout=_PROCESS_STOP_TIMEOUT_SECONDS)\n        return\n    except subprocess.TimeoutExpired:\n        pass\n    try:\n        process.kill()\n    except ProcessLookupError:\n        return\n    try:\n        process.wait(timeout=_PROCESS_STOP_TIMEOUT_SECONDS)\n    except subprocess.TimeoutExpired as exc:\n        raise ProfileInputError(\"cannot stop Git archive generation\") from exc\n\n\ndef _write_git_archive",
        "exact tree return and process stop",
    )

    old_archive = '''def _write_git_archive(git: Path, commit: str, archive_path: Path) -> None:
    try:
        with archive_path.open("xb") as output:
            completed = subprocess.run(
                [
                    str(git),
                    "-C",
                    str(_REPOSITORY_ROOT),
                    "archive",
                    "--format=tar",
                    commit,
                    "--",
                    "newsroom",
                ],
                stdout=output,
                stderr=subprocess.PIPE,
                check=False,
                timeout=30,
                env=_git_environment(git),
            )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProfileInputError("cannot materialize the exact Git code tree") from exc
    if (
        completed.returncode != 0
        or len(completed.stderr) > _MAX_GIT_OUTPUT_BYTES
        or not archive_path.is_file()
        or archive_path.stat().st_size > _MAX_ARCHIVE_BYTES
    ):
        raise ProfileInputError("cannot materialize the exact Git code tree")
'''
    new_archive = '''def _write_git_archive(git: Path, commit: str, archive_path: Path) -> None:
    process: subprocess.Popen[bytes] | None = None
    selector: selectors.BaseSelector | None = None
    try:
        with archive_path.open("xb") as output:
            process = subprocess.Popen(
                _git_command(
                    git,
                    "archive",
                    "--format=tar",
                    commit,
                    "--",
                    "newsroom",
                ),
                stdin=subprocess.DEVNULL,
                stdout=subprocess.PIPE,
                stderr=subprocess.DEVNULL,
                close_fds=True,
                start_new_session=True,
                env=_git_environment(git),
            )
            if process.stdout is None:
                raise ProfileInputError("Git archive stdout is unavailable")
            selector = selectors.DefaultSelector()
            selector.register(process.stdout, selectors.EVENT_READ)
            deadline = time.monotonic() + _ARCHIVE_TIMEOUT_SECONDS
            total = 0
            while selector.get_map():
                remaining_time = deadline - time.monotonic()
                if remaining_time <= 0:
                    raise ProfileInputError("Git archive generation timed out")
                events = selector.select(timeout=remaining_time)
                if not events:
                    raise ProfileInputError("Git archive generation timed out")
                for key, _ in events:
                    chunk = os.read(key.fd, _ARCHIVE_READ_CHUNK_BYTES)
                    if not chunk:
                        selector.unregister(key.fileobj)
                        continue
                    if total + len(chunk) > _MAX_ARCHIVE_BYTES:
                        raise ProfileInputError(
                            "Git archive exceeds the streaming generation limit"
                        )
                    output.write(chunk)
                    total += len(chunk)
            remaining_time = deadline - time.monotonic()
            if remaining_time <= 0:
                raise ProfileInputError("Git archive generation timed out")
            return_code = process.wait(timeout=remaining_time)
            if return_code != 0 or total == 0:
                raise ProfileInputError("Git archive generation failed")
            output.flush()
            os.fsync(output.fileno())
    except ProfileInputError:
        if process is not None:
            _stop_process(process)
        archive_path.unlink(missing_ok=True)
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        if process is not None:
            _stop_process(process)
        archive_path.unlink(missing_ok=True)
        raise ProfileInputError("cannot materialize the exact Git code tree") from exc
    finally:
        if selector is not None:
            selector.close()
        if process is not None:
            _stop_process(process)
            if process.stdout is not None:
                process.stdout.close()
'''
    text = _replace_once(text, old_archive, new_archive, "streaming archive")

    text = _replace_once(
        text,
        '''        git, actual_commit, actual_tree = _require_exact_code_tree(
            expected_commit,
            expected_tree,
        )
''',
        '''        git, git_digest, actual_commit, actual_tree = _require_exact_code_tree(
            expected_commit,
            expected_tree,
        )
''',
        "main trusted Git result",
    )
    text = _replace_once(
        text,
        '''                "authority_effect": "NONE",
                "code_commit_sha": actual_commit,
                "code_tree_sha": actual_tree,
                "manifest_digest": digest_bytes(raw),
''',
        '''                "archive_stream_limit_bytes": _MAX_ARCHIVE_BYTES,
                "archive_streaming_enforced": True,
                "authority_effect": "NONE",
                "code_commit_sha": actual_commit,
                "code_tree_sha": actual_tree,
                "git_executable_digest": git_digest,
                "git_executable_path": str(git),
                "git_producer_policy": "ROOT_OWNED_NON_WRITABLE_SYSTEM_PATH",
                "manifest_digest": digest_bytes(raw),
''',
        "receipt producer fields",
    )
    text = _replace_once(
        text,
        '"schema_version": "newsroom.increment5.profile-validation-receipt.v3",',
        '"schema_version": "newsroom.increment5.profile-validation-receipt.v4",',
        "receipt schema v4",
    )
    return text


def _transform_test(text: str) -> str:
    text = _replace_once(
        text,
        '''import ctypes
from copy import deepcopy
import inspect
import json
import os
from pathlib import Path
''',
        '''import ctypes
from copy import deepcopy
import hashlib
import importlib.util
import inspect
import json
import os
from pathlib import Path
''',
        "test imports",
    )
    text = _replace_once(
        text,
        '''_CODE_COMMIT_SHA, _CODE_TREE_SHA = _code_identity(_REPOSITORY_ROOT)


def _fixture_manifest()''',
        '''_CODE_COMMIT_SHA, _CODE_TREE_SHA = _code_identity(_REPOSITORY_ROOT)


def _trusted_git_identity() -> tuple[str, str]:
    seen: set[Path] = set()
    for candidate in (Path("/usr/bin/git"), Path("/bin/git")):
        try:
            path = candidate.resolve(strict=True)
        except OSError:
            continue
        if path in seen:
            continue
        seen.add(path)
        if not path.is_file() or not os.access(path, os.X_OK):
            continue
        digest = hashlib.sha256(path.read_bytes()).hexdigest()
        return str(path), "sha256:" + digest
    raise AssertionError("trusted system Git is unavailable")


_TRUSTED_GIT_PATH, _TRUSTED_GIT_DIGEST = _trusted_git_identity()


def _fixture_manifest()''',
        "trusted Git test identity",
    )
    text = _replace_once(
        text,
        '''def _validator_environment() -> dict[str, str]:
    return {
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", os.defpath),
        "PYTHONUTF8": "1",
    }
''',
        '''def _validator_environment(path_override: str | None = None) -> dict[str, str]:
    return {
        "LC_ALL": "C",
        "PATH": path_override or os.environ.get("PATH", os.defpath),
        "PYTHONUTF8": "1",
    }
''',
        "validator test environment",
    )
    text = _replace_once(
        text,
        '''    expected_commit: str | None = None,
    expected_tree: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
''',
        '''    expected_commit: str | None = None,
    expected_tree: str | None = None,
    path_override: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
''',
        "isolated path parameter",
    )
    text = _replace_once(
        text,
        '        env=_validator_environment(),\n        timeout=30,\n',
        '        env=_validator_environment(path_override),\n        timeout=30,\n',
        "isolated environment call",
    )
    text = _replace_once(
        text,
        '''    assert receipt == {
        "authority_effect": "NONE",
        "code_commit_sha": _CODE_COMMIT_SHA,
        "code_tree_sha": _CODE_TREE_SHA,
        "manifest_digest": digest_bytes(canonical_json_bytes(manifest)),
''',
        '''    assert receipt == {
        "archive_stream_limit_bytes": 67_108_864,
        "archive_streaming_enforced": True,
        "authority_effect": "NONE",
        "code_commit_sha": _CODE_COMMIT_SHA,
        "code_tree_sha": _CODE_TREE_SHA,
        "git_executable_digest": _TRUSTED_GIT_DIGEST,
        "git_executable_path": _TRUSTED_GIT_PATH,
        "git_producer_policy": "ROOT_OWNED_NON_WRITABLE_SYSTEM_PATH",
        "manifest_digest": digest_bytes(canonical_json_bytes(manifest)),
''',
        "receipt expectation producer fields",
    )
    text = _replace_once(
        text,
        '"schema_version": "newsroom.increment5.profile-validation-receipt.v3",',
        '"schema_version": "newsroom.increment5.profile-validation-receipt.v4",',
        "test receipt schema v4",
    )

    insertion_marker = '''def test_validator_materializes_exact_tree_before_repository_import() -> None:
'''
    new_tests = r'''def test_caller_path_cannot_replace_trusted_git_producer(
    tmp_path: Path,
) -> None:
    fake_bin = tmp_path / "fake-bin"
    fake_bin.mkdir()
    marker = tmp_path / "fake-git-invoked"
    fake_git = fake_bin / "git"
    fake_git.write_text(
        "#!/bin/sh\n"
        f"printf invoked > {marker!s}\n"
        "exit 97\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)

    completed = _run_isolated_bytes(
        canonical_json_bytes(_fixture_manifest()),
        path_override=str(fake_bin),
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    assert not marker.exists()
    receipt = json.loads(completed.stdout.decode("utf-8"))
    assert receipt["git_executable_path"] == _TRUSTED_GIT_PATH
    assert receipt["git_executable_digest"] == _TRUSTED_GIT_DIGEST
    assert receipt["git_producer_policy"] == (
        "ROOT_OWNED_NON_WRITABLE_SYSTEM_PATH"
    )


def test_archive_limit_stops_generation_before_disk_can_exceed_cap(
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    spec = importlib.util.spec_from_file_location(
        "increment5_profile_validator_stream_test",
        _VALIDATOR_SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)

    git, _ = module._git_executable()
    archive = tmp_path / "bounded-tree.tar"
    monkeypatch.setattr(module, "_MAX_ARCHIVE_BYTES", 1_024)
    with pytest.raises(
        module.ProfileInputError,
        match="streaming generation limit",
    ):
        module._write_git_archive(git, _CODE_COMMIT_SHA, archive)
    assert not archive.exists()


'''
    text = _replace_once(
        text,
        insertion_marker,
        new_tests + insertion_marker,
        "producer and streaming tests",
    )
    text = _replace_once(
        text,
        '''    assert '"--untracked-files=no"' in source
    assert '"--untracked-files=all"' not in source
''',
        '''    assert '"--untracked-files=no"' in source
    assert '"--untracked-files=all"' not in source
    assert "shutil.which" not in source
    assert "_TRUSTED_GIT_CANDIDATES" in source
    assert "ROOT_OWNED_NON_WRITABLE_SYSTEM_PATH" in source
    assert "subprocess.Popen" in source
    assert "selectors.DefaultSelector" in source
    assert "os.read" in source
    assert "stdout=output" not in source
    assert "archive_path.stat().st_size > _MAX_ARCHIVE_BYTES" not in source
''',
        "source boundary assertions",
    )
    return text


def _transform_decision(text: str) -> str:
    old = '''Before importing any Newsroom module, the validator resolves the actual Git
commit and tree, requires them to equal the caller-supplied identities, and
rejects staged or tracked differences. Ignored and untracked runtime artefacts
are never used as code. The validator creates a bounded temporary `git archive`
materialization from the exact commit, rejects unsafe paths, non-regular entries
and tracked bytecode, disables bytecode writes, removes checkout paths from the
import search path, and verifies that every loaded `newsroom.*` module came from
that cache-free materialization.

It then rejects non-canonical JSON, duplicate names, identity drift, wrong
profile/eligibility pairs, widened budgets or effects, fixture substitution,
unsafe dataset state, and missing actual-service requirements. Its canonical v3
receipt binds the manifest digest, profile kind, `code_commit_sha`,
`code_tree_sha`, `tracked_checkout_clean=true`,
`validation_code_origin=CACHE_FREE_EXACT_GIT_ARCHIVE`, and
`worktree_imports_used=false` while stating:
'''
    new = '''Before importing any Newsroom module, the validator resolves the actual Git
commit and tree, requires them to equal the caller-supplied identities, and
rejects staged or tracked differences. It does not resolve Git through caller
`PATH`. It selects only an allow-listed root-owned system executable whose file
and directory chain are not group- or world-writable, uses an absolute path,
neutralizes replacement refs, external attributes, hooks, fsmonitor and mutable
global/system configuration, and records the exact executable path and SHA-256
digest.

Ignored and untracked runtime artefacts are never used as code. The validator
streams a temporary `git archive` materialization from the exact commit through
a bounded pipe, terminates the producer before writing any byte beyond
67,108,864 bytes, removes partial output on every failure, rejects unsafe paths,
non-regular entries and tracked bytecode, disables bytecode writes, removes
checkout paths from the import search path, and verifies that every loaded
`newsroom.*` module came from the cache-free materialization.

It then rejects non-canonical JSON, duplicate names, identity drift, wrong
profile/eligibility pairs, widened budgets or effects, fixture substitution,
unsafe dataset state, and missing actual-service requirements. Its canonical v4
receipt binds the manifest digest, profile kind, `code_commit_sha`,
`code_tree_sha`, trusted Git path and digest,
`git_producer_policy=ROOT_OWNED_NON_WRITABLE_SYSTEM_PATH`,
`archive_streaming_enforced=true`, `archive_stream_limit_bytes=67108864`,
`tracked_checkout_clean=true`,
`validation_code_origin=CACHE_FREE_EXACT_GIT_ARCHIVE`, and
`worktree_imports_used=false` while stating:
'''
    text = _replace_once(text, old, new, "decision producer boundary")
    text = _replace_once(
        text,
        '''The receipt is necessary profile evidence, never sufficient qualification
evidence. Its `code_tree_sha` must equal the frozen Epoch `code_tree_sha`; a
missing or mismatched tree is `NOT_EVALUATED`. It grants no component, source,
model, provider, spend, write, production, or public-effect authority.
''',
        '''The receipt is necessary profile evidence, never sufficient qualification
evidence. Its `code_tree_sha` must equal the frozen Epoch `code_tree_sha`, and
5E must freeze and compare the Git executable path/digest, producer policy and
archive limit inside the Epoch policy set. A missing or mismatched tree or
producer identity is `NOT_EVALUATED`. It grants no component, source, model,
provider, spend, write, production, or public-effect authority.
''',
        "decision epoch producer binding",
    )
    return text


def _transform_operations(text: str) -> str:
    old = '''The validator verifies the supplied Git commit and tree and rejects staged or
tracked differences before importing any Newsroom module. It imports validation
code only from a bounded cache-free `git archive` materialization of that exact
commit; ignored bytecode, untracked runtime artefacts and checkout paths are not
used. Receipt v3 binds the manifest digest, profile kind, `code_commit_sha`,
`code_tree_sha`, `tracked_checkout_clean=true`,
`validation_code_origin=CACHE_FREE_EXACT_GIT_ARCHIVE`, and
`worktree_imports_used=false` while stating `authority_effect=NONE`,
`qualification_authority_granted=false`, and
`production_activation_authorized=false`. The receipt tree must equal the
frozen Epoch tree; mismatch is `NOT_EVALUATED`. It is necessary profile
evidence, never sufficient qualification evidence.
'''
    new = '''The validator verifies the supplied Git commit and tree and rejects staged or
tracked differences before importing any Newsroom module. Git is selected only
from fixed root-owned, non-group/world-writable system paths; caller `PATH` is
ignored, mutable Git replacement/attribute/hook/configuration surfaces are
neutralized, and the exact Git executable path and SHA-256 digest are retained.

Validation code is streamed from an exact-commit `git archive` through a hard
67,108,864-byte generation cap. The producer is terminated before an overflow
chunk is written, partial output is removed, and ignored bytecode, untracked
runtime artefacts and checkout paths are never imported. Receipt v4 binds the
manifest, profile, commit/tree, trusted Git path/digest and producer policy,
`archive_streaming_enforced=true`, the exact archive limit,
`tracked_checkout_clean=true`,
`validation_code_origin=CACHE_FREE_EXACT_GIT_ARCHIVE`, and
`worktree_imports_used=false` while stating `authority_effect=NONE`,
`qualification_authority_granted=false`, and
`production_activation_authorized=false`. The receipt tree and producer policy
identities must equal the frozen Epoch; mismatch is `NOT_EVALUATED`. It is
necessary profile evidence, never sufficient qualification evidence.
'''
    return _replace_once(text, old, new, "operations producer boundary")


def _transform_evaluation(text: str) -> str:
    old = '''Cross-Epoch pooling is prohibited. A missing or mismatched Epoch is
`NOT_EVALUATED`. Every profile-validation receipt is v3, binds the actual Git
commit and tree, and records that staged/tracked checkout state was clean and
that all Newsroom imports came from a cache-free exact-commit materialization
rather than checkout or ignored bytecode. Its `code_tree_sha` must equal the
Epoch's frozen `code_tree_sha`; a missing, dirty, non-materialized, or mismatched
code tree is `NOT_EVALUATED`. Superseded Epoch Runs remain retained. The Epoch
record binds the plan digest externally at Run creation, so the machine plan
does not contain a self-referential digest.
'''
    new = '''Cross-Epoch pooling is prohibited. A missing or mismatched Epoch is
`NOT_EVALUATED`. Every profile-validation receipt is v4, binds the actual Git
commit and tree, the root-owned system Git executable path and SHA-256 digest,
the exact producer policy, and the streaming archive limit. It records that
staged/tracked checkout state was clean and that all Newsroom imports came from
a cache-free exact-commit materialization rather than checkout or ignored
bytecode. The Epoch policy-set digest must freeze those producer identities and
limits before execution. Its `code_tree_sha` must equal the Epoch's frozen
`code_tree_sha`; a missing, dirty, non-materialized, producer-mismatched, or
code-tree-mismatched receipt is `NOT_EVALUATED`. Superseded Epoch Runs remain
retained. The Epoch record binds the plan digest externally at Run creation, so
the machine plan does not contain a self-referential digest.
'''
    return _replace_once(text, old, new, "evaluation producer boundary")


def main() -> int:
    _require_source_boundary()
    validator = VALIDATOR.read_text(encoding="utf-8")
    if "profile-validation-receipt.v3" not in validator:
        raise RuntimeError("source validator is not the reviewed v3 predecessor")
    VALIDATOR.write_text(_transform_validator(validator), encoding="utf-8")
    TEST.write_text(_transform_test(TEST.read_text(encoding="utf-8")), encoding="utf-8")
    DECISION.write_text(
        _transform_decision(DECISION.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    OPERATIONS.write_text(
        _transform_operations(OPERATIONS.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
    EVALUATION.write_text(
        _transform_evaluation(EVALUATION.read_text(encoding="utf-8")),
        encoding="utf-8",
    )

    manifest = {
        "archive_stream_limit_bytes": 67_108_864,
        "archive_streaming_enforced": True,
        "changed_paths": [
            str(DECISION.relative_to(ROOT)),
            str(EVALUATION.relative_to(ROOT)),
            str(OPERATIONS.relative_to(ROOT)),
            str(TEST.relative_to(ROOT)),
            str(VALIDATOR.relative_to(ROOT)),
        ],
        "contract_digest_unchanged": (
            "sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c"
        ),
        "evaluation_plan_digest_unchanged": (
            "sha256:c9d169c46a939573ffc6563704adfae973655f6394293ce591ec689f76a30959"
        ),
        "git_path_lookup_allowed": False,
        "git_producer_policy": "ROOT_OWNED_NON_WRITABLE_SYSTEM_PATH",
        "receipt_schema_version": "newsroom.increment5.profile-validation-receipt.v4",
        "schema_version": "newsroom.increment5a.pinned-git-stream.v1",
        "source_head": SOURCE_HEAD,
    }
    OUTPUT.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
