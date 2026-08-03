#!/usr/bin/env python3
"""Materialize the final trusted-Git and streaming-archive Increment 5A boundary.

Disposable staging helper. It must never be merged into PR #255 or main.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_HEAD = "26afbee4c9e180a5925603041a7a4af783f3357c"
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
MANIFEST = ROOT / "increment5a-trusted-git-streaming-manifest.json"


def replace_once(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def replace_section(
    text: str,
    start_marker: str,
    end_marker: str,
    replacement: str,
    *,
    label: str,
) -> str:
    start = text.find(start_marker)
    if start < 0:
        raise RuntimeError(f"{label}: missing start marker")
    end = text.find(end_marker, start)
    if end < 0:
        raise RuntimeError(f"{label}: missing end marker")
    if text.find(start_marker, start + 1) >= 0:
        raise RuntimeError(f"{label}: start marker is not unique")
    return text[:start] + replacement + text[end:]


def update_validator() -> None:
    text = VALIDATOR.read_text(encoding="utf-8")
    text = replace_once(
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
        label="validator imports",
    )
    text = replace_once(
        text,
        """_MAX_ARCHIVE_BYTES = 67_108_864
_MAX_ARCHIVE_MEMBER_BYTES = 16_777_216
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
""",
        """_MAX_ARCHIVE_BYTES = 67_108_864
_MAX_ARCHIVE_MEMBER_BYTES = 16_777_216
_STREAM_CHUNK_BYTES = 65_536
_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_GIT_EXECUTABLE = Path("/usr/bin/git")
_TRUSTED_GIT_PARENTS = (Path("/usr"), Path("/usr/bin"))
""",
        label="validator constants",
    )

    trusted_git_block = r'''class _TrustedGitProducer:
    """Exact root-owned Git producer; never selected from caller PATH."""

    __slots__ = ("path", "_identity")

    def __init__(self) -> None:
        self.path = _TRUSTED_GIT_EXECUTABLE
        self._identity = self._capture_identity()

    @staticmethod
    def _require_root_owned_path(path: Path, *, directory: bool) -> os.stat_result:
        try:
            info = path.lstat()
        except OSError as exc:
            raise ProfileInputError("trusted Git producer is unavailable") from exc
        if stat.S_ISLNK(info.st_mode):
            raise ProfileInputError("trusted Git producer path cannot be a symlink")
        expected_type = stat.S_ISDIR if directory else stat.S_ISREG
        if not expected_type(info.st_mode):
            raise ProfileInputError("trusted Git producer path has the wrong type")
        if info.st_uid != 0 or info.st_gid != 0:
            raise ProfileInputError("trusted Git producer path is not root owned")
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ProfileInputError("trusted Git producer path is writable")
        return info

    @staticmethod
    def _binary_identity(path: Path) -> tuple[int, int, int, int, int, int, int, str]:
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ProfileInputError("trusted Git producer cannot be opened") from exc
        try:
            info = os.fstat(descriptor)
            if not stat.S_ISREG(info.st_mode):
                raise ProfileInputError("trusted Git producer is not a regular file")
            if info.st_uid != 0 or info.st_gid != 0:
                raise ProfileInputError("trusted Git producer is not root owned")
            if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
                raise ProfileInputError("trusted Git producer is writable")
            if not info.st_mode & (stat.S_IXUSR | stat.S_IXGRP | stat.S_IXOTH):
                raise ProfileInputError("trusted Git producer is not executable")
            digest = hashlib.sha256()
            while True:
                chunk = os.read(descriptor, 1_048_576)
                if not chunk:
                    break
                digest.update(chunk)
            return (
                info.st_dev,
                info.st_ino,
                stat.S_IMODE(info.st_mode),
                info.st_uid,
                info.st_gid,
                info.st_size,
                info.st_mtime_ns,
                digest.hexdigest(),
            )
        finally:
            os.close(descriptor)

    def _capture_identity(self) -> tuple[int, int, int, int, int, int, int, str]:
        for parent in _TRUSTED_GIT_PARENTS:
            self._require_root_owned_path(parent, directory=True)
        self._require_root_owned_path(self.path, directory=False)
        return self._binary_identity(self.path)

    def require_unchanged(self) -> None:
        if self._capture_identity() != self._identity:
            raise ProfileInputError("trusted Git producer identity changed")

    def command(self, *arguments: str) -> list[str]:
        self.require_unchanged()
        return [str(self.path), "-C", str(_REPOSITORY_ROOT), *arguments]


def _git_environment() -> dict[str, str]:
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_PAGER": "cat",
        "GIT_TERMINAL_PROMPT": "0",
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "PAGER": "cat",
        "PATH": "/usr/bin:/bin",
    }


def _run_git(git: _TrustedGitProducer, *arguments: str) -> bytes:
    try:
        completed = subprocess.run(
            git.command(*arguments),
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=10,
            env=_git_environment(),
        )
    except (OSError, subprocess.TimeoutExpired) as exc:
        raise ProfileInputError("cannot inspect the exact Git code tree") from exc
    finally:
        git.require_unchanged()
    if (
        completed.returncode != 0
        or len(completed.stdout) > _MAX_GIT_OUTPUT_BYTES
        or len(completed.stderr) > _MAX_GIT_OUTPUT_BYTES
    ):
        raise ProfileInputError("cannot inspect the exact Git code tree")
    return completed.stdout


'''
    text = replace_section(
        text,
        "def _git_executable() -> Path:\n",
        "def _git_sha(",
        trusted_git_block,
        label="trusted Git producer boundary",
    )
    text = replace_once(
        text,
        "def _git_sha(git: Path, revision: str, field: str) -> str:\n",
        "def _git_sha(\n    git: _TrustedGitProducer,\n    revision: str,\n    field: str,\n) -> str:\n",
        label="git sha type",
    )
    text = replace_once(
        text,
        """    git = _git_executable()
    actual_commit = _git_sha(git, "HEAD^{commit}", "code commit SHA")
""",
        """    git = _TrustedGitProducer()
    actual_commit = _git_sha(git, "HEAD^{commit}", "code commit SHA")
""",
        label="trusted Git construction",
    )
    text = replace_once(
        text,
        ") -> tuple[Path, str, str]:\n",
        ") -> tuple[_TrustedGitProducer, str, str]:\n",
        label="exact tree return type",
    )

    archive_block = r'''def _terminate_process(process: subprocess.Popen[bytes]) -> None:
    if process.poll() is None:
        process.kill()
    try:
        process.wait(timeout=5)
    except subprocess.TimeoutExpired:
        pass
    for stream in (process.stdout, process.stderr):
        if stream is not None:
            stream.close()


def _stream_bounded_process_to_file(
    command: list[str],
    output_path: Path,
    *,
    env: dict[str, str],
    timeout_seconds: float,
    max_stdout_bytes: int,
    max_stderr_bytes: int,
    failure_message: str,
) -> bytes:
    """Stream both pipes and kill before stdout can exceed the disk cap."""

    process: subprocess.Popen[bytes] | None = None
    try:
        process = subprocess.Popen(
            command,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            stdin=subprocess.DEVNULL,
            bufsize=0,
            env=env,
        )
        if process.stdout is None or process.stderr is None:
            raise ProfileInputError(failure_message)
        deadline = time.monotonic() + timeout_seconds
        stderr = bytearray()
        written = 0
        with output_path.open("xb", buffering=0) as output:
            with selectors.DefaultSelector() as selector:
                for stream, stream_name in (
                    (process.stdout, "stdout"),
                    (process.stderr, "stderr"),
                ):
                    os.set_blocking(stream.fileno(), False)
                    selector.register(stream, selectors.EVENT_READ, stream_name)
                while selector.get_map():
                    remaining = deadline - time.monotonic()
                    if remaining <= 0:
                        raise ProfileInputError(failure_message)
                    events = selector.select(min(remaining, 0.25))
                    if not events:
                        continue
                    for key, _ in events:
                        try:
                            chunk = os.read(key.fd, _STREAM_CHUNK_BYTES)
                        except BlockingIOError:
                            continue
                        if not chunk:
                            selector.unregister(key.fileobj)
                            continue
                        if key.data == "stdout":
                            if written + len(chunk) > max_stdout_bytes:
                                raise ProfileInputError(
                                    "Git archive exceeds the generation limit"
                                )
                            output.write(chunk)
                            written += len(chunk)
                        else:
                            if len(stderr) + len(chunk) > max_stderr_bytes:
                                raise ProfileInputError(failure_message)
                            stderr.extend(chunk)
        wait_remaining = deadline - time.monotonic()
        if wait_remaining <= 0:
            raise ProfileInputError(failure_message)
        try:
            return_code = process.wait(timeout=wait_remaining)
        except subprocess.TimeoutExpired as exc:
            raise ProfileInputError(failure_message) from exc
        if return_code != 0 or written == 0:
            raise ProfileInputError(failure_message)
        return bytes(stderr)
    except ProfileInputError:
        if process is not None:
            _terminate_process(process)
        output_path.unlink(missing_ok=True)
        raise
    except (OSError, subprocess.SubprocessError) as exc:
        if process is not None:
            _terminate_process(process)
        output_path.unlink(missing_ok=True)
        raise ProfileInputError(failure_message) from exc
    finally:
        if process is not None and process.poll() is None:
            _terminate_process(process)


def _write_git_archive(
    git: _TrustedGitProducer,
    commit: str,
    archive_path: Path,
) -> None:
    git.require_unchanged()
    try:
        _stream_bounded_process_to_file(
            git.command(
                "archive",
                "--format=tar",
                commit,
                "--",
                "newsroom",
            ),
            archive_path,
            env=_git_environment(),
            timeout_seconds=30,
            max_stdout_bytes=_MAX_ARCHIVE_BYTES,
            max_stderr_bytes=_MAX_GIT_OUTPUT_BYTES,
            failure_message="cannot materialize the exact Git code tree",
        )
    finally:
        git.require_unchanged()


'''
    text = replace_section(
        text,
        "def _write_git_archive(",
        "def _canonical_archive_name(",
        archive_block,
        label="streaming Git archive boundary",
    )
    text = replace_once(
        text,
        """def _materialized_repository_api(
    git: Path,
    commit: str,
""",
        """def _materialized_repository_api(
    git: _TrustedGitProducer,
    commit: str,
""",
        label="materialized API producer type",
    )
    VALIDATOR.write_text(text, encoding="utf-8")


def update_tests() -> None:
    text = TESTS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        """import ctypes
from copy import deepcopy
import inspect
""",
        """import ctypes
from copy import deepcopy
import importlib.util
import inspect
""",
        label="test imports",
    )
    text = replace_once(
        text,
        """def _run_isolated_bytes(
    raw: bytes,
    *,
    root: Path = _REPOSITORY_ROOT,
    expected_commit: str | None = None,
    expected_tree: str | None = None,
) -> subprocess.CompletedProcess[bytes]:
""",
        """def _run_isolated_bytes(
    raw: bytes,
    *,
    root: Path = _REPOSITORY_ROOT,
    expected_commit: str | None = None,
    expected_tree: str | None = None,
    environment: dict[str, str] | None = None,
) -> subprocess.CompletedProcess[bytes]:
""",
        label="isolated runner signature",
    )
    text = replace_once(
        text,
        """        cwd=root,
        env=_validator_environment(),
        timeout=30,
""",
        """        cwd=root,
        env=environment or _validator_environment(),
        timeout=30,
""",
        label="isolated runner environment",
    )

    new_tests = r'''


def test_path_selected_fake_git_cannot_supply_the_archive(tmp_path: Path) -> None:
    fake_directory = tmp_path / "fake-bin"
    fake_directory.mkdir()
    marker = tmp_path / "fake-git-invoked"
    fake_git = fake_directory / "git"
    fake_git.write_text(
        "#!/usr/bin/python3\n"
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('invoked', encoding='utf-8')\n"
        "raise SystemExit(71)\n",
        encoding="utf-8",
    )
    fake_git.chmod(0o755)

    environment = _validator_environment()
    environment["PATH"] = f"{fake_directory}:{environment['PATH']}"
    completed = _run_isolated_bytes(
        canonical_json_bytes(_fixture_manifest()),
        environment=environment,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    assert not marker.exists()
    receipt = json.loads(completed.stdout.decode("utf-8"))
    assert receipt["validation_code_origin"] == "CACHE_FREE_EXACT_GIT_ARCHIVE"


def _load_validator_module() -> Any:
    spec = importlib.util.spec_from_file_location(
        "increment5_profile_validator_streaming_test",
        _VALIDATOR_SCRIPT,
    )
    assert spec is not None and spec.loader is not None
    module = importlib.util.module_from_spec(spec)
    spec.loader.exec_module(module)
    return module


def test_archive_limit_kills_the_producer_before_overflow_reaches_disk(
    tmp_path: Path,
) -> None:
    validator = _load_validator_module()
    marker = tmp_path / "producer-completed"
    emitter = tmp_path / "emit-large-archive.py"
    emitter.write_text(
        "from pathlib import Path\n"
        "import os\n"
        "import sys\n"
        "import time\n"
        "os.write(sys.stdout.fileno(), b'x' * 8192)\n"
        "time.sleep(10)\n"
        f"Path({str(marker)!r}).write_text('completed', encoding='utf-8')\n",
        encoding="utf-8",
    )
    archive = tmp_path / "bounded.tar"

    with pytest.raises(
        validator.ProfileInputError,
        match="Git archive exceeds the generation limit",
    ):
        validator._stream_bounded_process_to_file(
            [sys.executable, str(emitter)],
            archive,
            env={"LC_ALL": "C", "PYTHONUTF8": "1"},
            timeout_seconds=20,
            max_stdout_bytes=1024,
            max_stderr_bytes=1024,
            failure_message="cannot materialize the exact Git code tree",
        )

    assert not archive.exists()
    assert not marker.exists()
'''
    anchor = "\ndef test_validator_materializes_exact_tree_before_repository_import() -> None:\n"
    text = replace_once(
        text,
        anchor,
        new_tests + anchor,
        label="new trusted producer and streaming tests",
    )
    text = replace_once(
        text,
        """    assert '"--untracked-files=no"' in source
    assert '"--untracked-files=all"' not in source
""",
        """    assert '"--untracked-files=no"' in source
    assert '"--untracked-files=all"' not in source
    assert '_TRUSTED_GIT_EXECUTABLE = Path("/usr/bin/git")' in source
    assert "shutil.which" not in source
    assert "selectors.DefaultSelector()" in source
    assert "stdout=subprocess.PIPE" in source
""",
        label="source boundary assertions",
    )
    TESTS.write_text(text, encoding="utf-8")


def update_docs() -> None:
    decision = DECISION.read_text(encoding="utf-8")
    decision = replace_once(
        decision,
        """Before importing any Newsroom module, the validator resolves the actual Git
commit and tree, requires them to equal the caller-supplied identities, and
rejects staged or tracked differences. Ignored and untracked runtime artefacts
are never used as code. The validator creates a bounded temporary `git archive`
materialization from the exact commit, rejects unsafe paths, non-regular entries
and tracked bytecode, disables bytecode writes, removes checkout paths from the
import search path, and verifies that every loaded `newsroom.*` module came from
that cache-free materialization.
""",
        """Before importing any Newsroom module, the validator resolves the actual Git
commit and tree, requires them to equal the caller-supplied identities, and
rejects staged or tracked differences. Git is never selected from caller
`PATH`: the producer is fixed to `/usr/bin/git`, and `/usr`, `/usr/bin`, and the
binary must be non-symlink, root-owned, and not group- or other-writable. The
binary's device, inode, mode, ownership, size, modification time, and SHA-256
identity are captured and rechecked before and after every operation.

Ignored and untracked runtime artefacts are never used as code. Archive stdout
and stderr are consumed concurrently through the validator; no stdout chunk
that would cross the 64 MiB generation cap is written, and the producer is
terminated immediately on overflow, timeout, or stderr-limit failure. The
bounded archive is then extracted with unsafe paths, non-regular entries,
oversized members, and tracked bytecode rejected. Bytecode writes are disabled,
checkout paths are removed from the import search path, and every loaded
`newsroom.*` module must come from that cache-free exact-commit materialization.
""",
        label="decision trusted producer boundary",
    )
    DECISION.write_text(decision, encoding="utf-8")

    evaluation = EVALUATION.read_text(encoding="utf-8")
    evaluation = replace_once(
        evaluation,
        """Cross-Epoch pooling is prohibited. A missing or mismatched Epoch is
`NOT_EVALUATED`. Every profile-validation receipt is v3, binds the actual Git
commit and tree, and records that staged/tracked checkout state was clean and
that all Newsroom imports came from a cache-free exact-commit materialization
rather than checkout or ignored bytecode. Its `code_tree_sha` must equal the
Epoch's frozen `code_tree_sha`; a missing, dirty, non-materialized, or mismatched
code tree is `NOT_EVALUATED`. Superseded Epoch Runs remain retained. The Epoch
record binds the plan digest externally at Run creation, so the machine plan
does not contain a self-referential digest.
""",
        """Cross-Epoch pooling is prohibited. A missing or mismatched Epoch is
`NOT_EVALUATED`. Every profile-validation receipt is v3, binds the actual Git
commit and tree, and records that staged/tracked checkout state was clean and
that all Newsroom imports came from a cache-free exact-commit materialization
rather than checkout or ignored bytecode. The materialization producer is the
fixed root-owned `/usr/bin/git` binary, never caller `PATH`; its identity is
rechecked around every operation, and archive bytes are streamed through a hard
64 MiB pre-write cap that terminates the producer on overflow. The receipt's
`code_tree_sha` must equal the Epoch's frozen `code_tree_sha`; a missing, dirty,
untrusted-producer, unbounded, non-materialized, or mismatched code tree is
`NOT_EVALUATED`. Superseded Epoch Runs remain retained. The Epoch record binds
the plan digest externally at Run creation, so the machine plan does not contain
a self-referential digest.
""",
        label="evaluation trusted producer boundary",
    )
    EVALUATION.write_text(evaluation, encoding="utf-8")

    operations = OPERATIONS.read_text(encoding="utf-8")
    operations = replace_once(
        operations,
        """The validator verifies the supplied Git commit and tree and rejects staged or
tracked differences before importing any Newsroom module. It imports validation
code only from a bounded cache-free `git archive` materialization of that exact
commit; ignored bytecode, untracked runtime artefacts and checkout paths are not
used. Receipt v3 binds the manifest digest, profile kind, `code_commit_sha`,
`code_tree_sha`, `tracked_checkout_clean=true`,
""",
        """The validator verifies the supplied Git commit and tree and rejects staged or
tracked differences before importing any Newsroom module. It ignores caller
`PATH` and accepts only the fixed `/usr/bin/git` producer after checking that it
and its parent directories are non-symlink, root-owned, and not group- or
other-writable; the binary identity is rechecked around every operation.
Archive stdout and stderr are streamed concurrently, the producer is terminated
before any byte crossing the 64 MiB cap can reach disk, and only that bounded
cache-free exact-commit materialization supplies validation imports. Ignored
bytecode, untracked runtime artefacts and checkout paths are not used. Receipt
v3 binds the manifest digest, profile kind, `code_commit_sha`,
`code_tree_sha`, `tracked_checkout_clean=true`,
""",
        label="operations trusted producer boundary",
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
        "producer_boundary": {
            "binary": "/usr/bin/git",
            "caller_path_used": False,
            "identity_rechecked": True,
            "root_owned_nonwritable_path_required": True,
        },
        "schema_version": "newsroom.increment5a.trusted-git-streaming.v1",
        "source_head": SOURCE_HEAD,
        "streaming_boundary": {
            "archive_cap_bytes": 67_108_864,
            "concurrent_stdout_stderr": True,
            "kill_before_overflow_write": True,
            "post_exit_only_size_check": False,
        },
    }
    MANIFEST.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
