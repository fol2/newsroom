#!/usr/bin/env python3
"""Generate and test the outer-authenticated Increment 5A validator candidate.

Disposable support helper. Never merge this file into PR #255 or main.
"""
from __future__ import annotations

import json
from pathlib import Path

ROOT = Path(__file__).resolve().parents[2]
VALIDATOR = ROOT / "scripts/sdlc/increment5_profile_validator.py"
TESTS = ROOT / "newsroom/tests/test_increment5a_profile_semantic_envelope.py"
DECISION = ROOT / "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"
EVALUATION = ROOT / "docs/evaluation/2026-08-02-increment-5-retrieval-evaluation-plan-v1.md"
OPERATIONS = ROOT / "docs/operations/increment-5-production-retrieval-contract.md"
MANIFEST = ROOT / "increment5a-outer-git-blob-launcher-manifest.json"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def replace_section(text: str, start: str, end: str, new: str, label: str) -> str:
    first = text.find(start)
    if first < 0:
        raise RuntimeError(f"{label}: start marker missing")
    second = text.find(end, first)
    if second < 0:
        raise RuntimeError(f"{label}: end marker missing")
    if text.find(start, first + 1) >= 0:
        raise RuntimeError(f"{label}: start marker is not unique")
    return text[:first] + new + text[second:]


validator = VALIDATOR.read_text(encoding="utf-8")
validator = replace_once(
    validator,
    '''"""Validate one canonical Increment 5 profile without external Python packages.

The executable is an evidence boundary. It uses only the Python standard
library, binds one explicit Git directory/index/work tree, reads exact reviewed
contract and schema blobs from the supplied commit, and emits a non-authoritative
receipt only after the repository state is revalidated at completion.
"""''',
    '''"""Validate one canonical Increment 5 profile from an exact Git blob.

The signed outer launcher—not this Python process—authenticates and streams the
validator bytes from the expected commit before Python executes them. This
stdlib-only inner process then binds the exact repository, validator blob,
manifest bytes, runtime, and completion-time state into a non-authoritative
receipt. The receipt cannot authenticate its own executed source and grants no
authority without the separately signed outer-launch evidence.
"""''',
    "validator docstring",
)
validator = replace_once(
    validator,
    '''if not sys.flags.isolated or not sys.flags.no_site:
    sys.stderr.write(
        "increment5 profile validation failed: trusted isolated Python with "
        "site initialization disabled is required\\n"
    )
    raise SystemExit(2)
''',
    '''if (
    not sys.flags.isolated
    or not sys.flags.no_site
    or sys.argv[0] != "-"
):
    sys.stderr.write(
        "increment5 profile validation failed: signed outer Git-blob launcher "
        "with trusted isolated no-site Python is required\\n"
    )
    raise SystemExit(2)
''',
    "validator bootstrap",
)
validator = replace_once(
    validator,
    '''_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
_TRUSTED_PYTHON_EXECUTABLE = Path("/usr/bin/python3")
_TRUSTED_PYTHON_PARENTS = (Path("/usr"), Path("/usr/bin"))
_TRUSTED_GIT_EXECUTABLE = Path("/usr/bin/git")
_TRUSTED_GIT_PARENTS = (Path("/usr"), Path("/usr/bin"))
_EXPECTED_FLAGS = frozenset(
    {
        "--expected-code-commit-sha",
        "--expected-code-tree-sha",
    }
)
_CONTRACT_PATH = "newsroom/increment5/data/increment5a_retrieval_contract_v1.json"
''',
    '''_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")
_TRUSTED_PYTHON_EXECUTABLE = Path("/usr/bin/python3")
_TRUSTED_PYTHON_PARENTS = (Path("/usr"), Path("/usr/bin"))
_TRUSTED_GIT_EXECUTABLE = Path("/usr/bin/git")
_TRUSTED_GIT_PARENTS = (Path("/usr"), Path("/usr/bin"))
_INVOCATION_FLAGS = frozenset(
    {
        "--repository-root",
        "--git-dir",
        "--index-file",
        "--manifest-fd",
        "--expected-validator-blob-sha",
        "--expected-code-commit-sha",
        "--expected-code-tree-sha",
    }
)
_VALIDATOR_PATH = "scripts/sdlc/increment5_profile_validator.py"
_CONTRACT_PATH = "newsroom/increment5/data/increment5a_retrieval_contract_v1.json"
''',
    "validator constants",
)

repository_class = '''class _TrustedRepositoryView:
    __slots__ = ("root", "git", "git_dir", "index_path", "_environment")

    def __init__(self, root: Path, git_dir: Path, index_path: Path) -> None:
        try:
            self.root = root.resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProfileInputError("repository root is unavailable") from exc
        try:
            current_root = Path.cwd().resolve(strict=True)
        except (OSError, RuntimeError) as exc:
            raise ProfileInputError("current repository root is unavailable") from exc
        if current_root != self.root:
            raise ProfileInputError("repository root differs from current checkout")

        expected_git_dir = self.root / ".git"
        expected_index = expected_git_dir / "index"
        if git_dir != expected_git_dir or index_path != expected_index:
            raise ProfileInputError("outer launcher repository paths differ")
        self._require_repository_path(expected_git_dir, directory=True)
        self._require_repository_path(expected_index, directory=False)
        self.git_dir = expected_git_dir
        self.index_path = expected_index
        self.git = _TrustedGitBinary()

        environment = _base_git_environment()
        environment.update(
            {
                "GIT_DIR": str(self.git_dir),
                "GIT_INDEX_FILE": str(self.index_path),
                "GIT_WORK_TREE": str(self.root),
            }
        )
        self._environment = environment

    @staticmethod
    def _require_repository_path(path: Path, *, directory: bool) -> None:
        try:
            info = path.lstat()
        except OSError as exc:
            raise ProfileInputError("repository metadata path is unavailable") from exc
        if stat.S_ISLNK(info.st_mode):
            raise ProfileInputError("repository metadata path cannot be a symlink")
        expected_type = stat.S_ISDIR if directory else stat.S_ISREG
        if not expected_type(info.st_mode):
            raise ProfileInputError("repository metadata path has the wrong type")
        if info.st_uid not in {0, os.getuid()}:
            raise ProfileInputError("repository metadata path has an unexpected owner")
        if info.st_mode & stat.S_IWOTH:
            raise ProfileInputError("repository metadata path is world writable")

    def command(self, *arguments: str) -> list[str]:
        self.git.require_unchanged()
        return [
            str(self.git.path),
            f"--git-dir={self.git_dir}",
            f"--work-tree={self.root}",
            "--no-replace-objects",
            "-c",
            "core.fsmonitor=false",
            *arguments,
        ]

    def run(
        self,
        *arguments: str,
        max_stdout_bytes: int = _MAX_GIT_OUTPUT_BYTES,
        timeout_seconds: float = 10,
        failure_message: str = "cannot inspect the exact Git code tree",
    ) -> bytes:
        self.git.require_unchanged()
        try:
            return _capture_bounded_process(
                self.command(*arguments),
                env=dict(self._environment),
                timeout_seconds=timeout_seconds,
                max_stdout_bytes=max_stdout_bytes,
                max_stderr_bytes=_MAX_GIT_OUTPUT_BYTES,
                failure_message=failure_message,
            )
        finally:
            self.git.require_unchanged()

    def require_stable_clean_tree(self, commit: str, tree: str) -> None:
        actual_commit = _git_sha(self, "HEAD^{commit}", "code commit SHA")
        actual_tree = _git_sha(self, "HEAD^{tree}", "code tree SHA")
        if actual_commit != commit:
            raise ProfileInputError("code commit SHA differs from expected identity")
        if actual_tree != tree:
            raise ProfileInputError("code tree SHA differs from expected identity")
        self._reject_hidden_index_flags()
        status = self.run(
            "status",
            "--porcelain=v1",
            "--untracked-files=no",
            "--ignore-submodules=none",
        )
        if status:
            raise ProfileInputError("tracked repository checkout differs from HEAD")

    def require_validator_blob(self, commit: str, expected_blob: str) -> None:
        actual_blob = _git_sha(
            self,
            f"{commit}:{_VALIDATOR_PATH}",
            "validator blob SHA",
        )
        if actual_blob != expected_blob:
            raise ProfileInputError("validator blob SHA differs from expected identity")

    def _reject_hidden_index_flags(self) -> None:
        raw = self.run(
            "ls-files",
            "-v",
            "-z",
            "--",
            max_stdout_bytes=_MAX_INDEX_LIST_BYTES,
            failure_message="cannot inspect tracked index flags",
        )
        for record in raw.split(b"\\0"):
            if not record:
                continue
            if len(record) < 3 or record[1:2] != b" ":
                raise ProfileInputError("tracked index flag inventory is malformed")
            tag = record[0]
            if tag == ord("S") or ord("a") <= tag <= ord("z"):
                raise ProfileInputError(
                    "tracked index flags can hide checkout changes"
                )

    def read_reviewed_blob(self, commit: str, path: str) -> bytes:
        return self.run(
            "cat-file",
            "blob",
            f"{commit}:{path}",
            max_stdout_bytes=_MAX_REVIEWED_BLOB_BYTES,
            timeout_seconds=20,
            failure_message=f"cannot read reviewed profile data: {path}",
        )


'''
validator = replace_section(
    validator,
    "class _TrustedRepositoryView:\n",
    "def _git_sha(",
    repository_class,
    "repository view",
)

invocation = '''def _parse_invocation(
    arguments: list[str],
) -> tuple[Path, Path, Path, int, str, str, str]:
    if len(arguments) != 14:
        raise ProfileInputError("exact outer launch arguments are required")
    values: dict[str, str] = {}
    for index in range(0, len(arguments), 2):
        name = arguments[index]
        value = arguments[index + 1]
        if name not in _INVOCATION_FLAGS or name in values:
            raise ProfileInputError("exact outer launch arguments are malformed")
        values[name] = value
    if frozenset(values) != _INVOCATION_FLAGS:
        raise ProfileInputError("exact outer launch arguments are required")

    for field in (
        "--expected-validator-blob-sha",
        "--expected-code-commit-sha",
        "--expected-code-tree-sha",
    ):
        if not _GIT_SHA.fullmatch(values[field]):
            raise ProfileInputError("expected code identity is not a canonical Git SHA")

    paths: list[Path] = []
    for field in ("--repository-root", "--git-dir", "--index-file"):
        path = Path(values[field])
        if not path.is_absolute() or str(path) != values[field]:
            raise ProfileInputError("outer launcher paths must be canonical absolute paths")
        paths.append(path)

    fd_text = values["--manifest-fd"]
    try:
        manifest_fd = int(fd_text, 10)
    except ValueError as exc:
        raise ProfileInputError("manifest descriptor is malformed") from exc
    if str(manifest_fd) != fd_text or not 3 <= manifest_fd <= 1024:
        raise ProfileInputError("manifest descriptor is malformed")

    return (
        paths[0],
        paths[1],
        paths[2],
        manifest_fd,
        values["--expected-validator-blob-sha"],
        values["--expected-code-commit-sha"],
        values["--expected-code-tree-sha"],
    )


def _read_manifest_descriptor(descriptor: int) -> bytes:
    try:
        duplicate = os.dup(descriptor)
    except OSError as exc:
        raise ProfileInputError("manifest descriptor is unavailable") from exc
    try:
        info = os.fstat(duplicate)
        if not stat.S_ISREG(info.st_mode):
            raise ProfileInputError("manifest descriptor must reference a regular file")
        if info.st_size > _MAX_INPUT_BYTES:
            raise ProfileInputError("input exceeds 1048576 bytes")
        with os.fdopen(duplicate, "rb", closefd=True) as stream:
            duplicate = -1
            raw = stream.read(_MAX_INPUT_BYTES + 1)
    finally:
        if duplicate >= 0:
            os.close(duplicate)
    if len(raw) > _MAX_INPUT_BYTES:
        raise ProfileInputError("input exceeds 1048576 bytes")
    return raw


'''
validator = replace_section(
    validator,
    "def _parse_expected_identities(",
    "def _load_reviewed_profile_data(",
    invocation,
    "invocation parser",
)

emit_and_main = '''def _emit_receipt(
    runtime: _TrustedPythonRuntime,
    repository: _TrustedRepositoryView,
    commit: str,
    tree: str,
    validator_blob: str,
    receipt: dict[str, Any],
    output: BinaryIO,
) -> None:
    raw = _canonical_json_bytes(receipt) + b"\\n"
    runtime.require_unchanged()
    repository.require_stable_clean_tree(commit, tree)
    repository.require_validator_blob(commit, validator_blob)
    output.write(raw)


def main() -> int:
    try:
        (
            repository_root,
            git_dir,
            index_path,
            manifest_fd,
            expected_validator_blob,
            expected_commit,
            expected_tree,
        ) = _parse_invocation(sys.argv[1:])
        runtime = _TrustedPythonRuntime()
        repository = _TrustedRepositoryView(repository_root, git_dir, index_path)
        repository.require_stable_clean_tree(expected_commit, expected_tree)
        repository.require_validator_blob(expected_commit, expected_validator_blob)

        raw = _read_manifest_descriptor(manifest_fd)
        manifest = _parse_input_manifest(raw)
        reviewed = _load_reviewed_profile_data(repository, expected_commit)
        profile_kind = _validate_profile_manifest(manifest, reviewed)
        receipt = {
            "authority_effect": "NONE",
            "code_commit_sha": expected_commit,
            "code_tree_sha": expected_tree,
            "executed_source_identity_attested": False,
            "external_python_packages_used": False,
            "manifest_digest": _digest_bytes(raw),
            "outer_signed_workflow_binding_required": True,
            "production_activation_authorized": False,
            "profile_kind": profile_kind,
            "python_runtime_executable": "/usr/bin/python3",
            "python_runtime_origin": "ROOT_OWNED_SYSTEM_PYTHON_NO_SITE",
            "qualification_authority_granted": False,
            "schema_version": "newsroom.increment5.profile-validation-receipt.v6",
            "site_initialization_used": False,
            "tracked_checkout_clean": True,
            "validation_code_delivery": "EXACT_COMMIT_GIT_BLOB_STDIN",
            "validation_code_identity_claim_effect": "NONE",
            "validation_code_origin": "OUTER_SIGNED_GIT_BLOB_LAUNCHER_REQUIRED",
            "validation_data_origin": "EXACT_REVIEWED_GIT_BLOBS",
            "validation_scope": (
                "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_EXACT_CODE_TREE"
            ),
            "validator_blob_sha": expected_validator_blob,
            "worktree_imports_used": False,
        }
        _emit_receipt(
            runtime,
            repository,
            expected_commit,
            expected_tree,
            expected_validator_blob,
            receipt,
            sys.stdout.buffer,
        )
        return 0
    except ProfileInputError as exc:
        return _fail(str(exc))


if __name__ == "__main__":
    raise SystemExit(main())
'''
validator = replace_section(
    validator,
    "def _emit_receipt(\n",
    "if __name__ == \"__main__\":\n    raise SystemExit(main())\n",
    emit_and_main,
    "receipt and main",
)
VALIDATOR.write_text(validator, encoding="utf-8")

# Test helper and exact receipt.
tests = TESTS.read_text(encoding="utf-8")
tests = replace_once(tests, "import sys\nimport time\n", "import sys\nimport tempfile\nimport time\n", "test imports")
tests = replace_once(
    tests,
    '_TRUSTED_PYTHON = Path("/usr/bin/python3")\n',
    '_TRUSTED_PYTHON = Path("/usr/bin/python3")\n_TRUSTED_GIT = Path("/usr/bin/git")\n',
    "trusted git constant",
)
helper = '''def _validator_environment() -> dict[str, str]:
    return {
        "LC_ALL": "C",
        "PATH": os.environ.get("PATH", os.defpath),
        "PYTHONUTF8": "1",
    }


def _trusted_git_environment(root: Path) -> dict[str, str]:
    git_dir = root / ".git"
    return {
        "GIT_CONFIG_GLOBAL": os.devnull,
        "GIT_CONFIG_NOSYSTEM": "1",
        "GIT_DIR": str(git_dir),
        "GIT_INDEX_FILE": str(git_dir / "index"),
        "GIT_NO_REPLACE_OBJECTS": "1",
        "GIT_OPTIONAL_LOCKS": "0",
        "GIT_WORK_TREE": str(root),
        "HOME": "/nonexistent",
        "LANG": "C",
        "LC_ALL": "C",
        "PATH": "/usr/bin:/bin",
    }


def _trusted_git_command(root: Path, *arguments: str) -> list[str]:
    return [
        str(_TRUSTED_GIT),
        f"--git-dir={root / '.git'}",
        f"--work-tree={root}",
        "--no-replace-objects",
        "-c",
        "core.fsmonitor=false",
        *arguments,
    ]


def _exact_validator_source(root: Path, commit: str) -> tuple[str, bytes]:
    environment = _trusted_git_environment(root)
    resolved = subprocess.run(
        _trusted_git_command(
            root,
            "rev-parse",
            "--verify",
            f"{commit}:{_VALIDATOR_RELATIVE_PATH.as_posix()}",
        ),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=environment,
        timeout=20,
    )
    assert resolved.returncode == 0, resolved.stderr.decode("utf-8")
    blob = resolved.stdout.decode("ascii", errors="strict").strip()
    assert len(blob) == 40
    read = subprocess.run(
        _trusted_git_command(root, "cat-file", "blob", blob),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        env=environment,
        timeout=20,
    )
    assert read.returncode == 0, read.stderr.decode("utf-8")
    return blob, read.stdout


def _run_isolated_bytes(
    raw: bytes,
    *,
    root: Path = _REPOSITORY_ROOT,
    expected_commit: str | None = None,
    expected_tree: str | None = None,
    expected_validator_blob: str | None = None,
    source_commit: str | None = None,
    environment: dict[str, str] | None = None,
    python_executable: Path = _TRUSTED_PYTHON,
) -> subprocess.CompletedProcess[bytes]:
    root = root.resolve(strict=True)
    actual_commit, actual_tree = _code_identity(root)
    expected_commit = expected_commit or actual_commit
    expected_tree = expected_tree or actual_tree
    source_commit = source_commit or actual_commit
    validator_blob, validator_source = _exact_validator_source(root, source_commit)
    expected_validator_blob = expected_validator_blob or validator_blob

    with tempfile.NamedTemporaryFile(mode="w+b") as manifest:
        manifest.write(raw)
        manifest.flush()
        os.fsync(manifest.fileno())
        manifest.seek(0)
        return subprocess.run(
            [
                str(python_executable),
                "-I",
                "-S",
                "-",
                "--repository-root",
                str(root),
                "--git-dir",
                str(root / ".git"),
                "--index-file",
                str(root / ".git/index"),
                "--manifest-fd",
                str(manifest.fileno()),
                "--expected-validator-blob-sha",
                expected_validator_blob,
                "--expected-code-commit-sha",
                expected_commit,
                "--expected-code-tree-sha",
                expected_tree,
            ],
            input=validator_source,
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            cwd=root,
            env=environment or _validator_environment(),
            pass_fds=(manifest.fileno(),),
            timeout=30,
        )


'''
tests = replace_section(
    tests,
    "def _validator_environment() -> dict[str, str]:\n",
    "def _run_isolated(manifest: dict[str, Any])",
    helper,
    "test launcher helper",
)

tests = replace_once(
    tests,
    '''        "manifest_digest": digest_bytes(canonical_json_bytes(manifest)),
        "production_activation_authorized": False,
        "profile_kind": manifest["profile_kind"],
        "python_runtime_executable": "/usr/bin/python3",
        "python_runtime_origin": "ROOT_OWNED_SYSTEM_PYTHON_NO_SITE",
        "qualification_authority_granted": False,
        "external_python_packages_used": False,
        "schema_version": "newsroom.increment5.profile-validation-receipt.v5",
        "site_initialization_used": False,
        "tracked_checkout_clean": True,
        "validation_code_origin": "EXACT_TRACKED_EXECUTABLE_STDLIB_ONLY",
        "validation_data_origin": "EXACT_REVIEWED_GIT_BLOBS",
        "validation_scope": (
            "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_EXACT_CODE_TREE"
        ),
        "worktree_imports_used": False,
''',
    '''        "executed_source_identity_attested": False,
        "external_python_packages_used": False,
        "manifest_digest": digest_bytes(canonical_json_bytes(manifest)),
        "outer_signed_workflow_binding_required": True,
        "production_activation_authorized": False,
        "profile_kind": manifest["profile_kind"],
        "python_runtime_executable": "/usr/bin/python3",
        "python_runtime_origin": "ROOT_OWNED_SYSTEM_PYTHON_NO_SITE",
        "qualification_authority_granted": False,
        "schema_version": "newsroom.increment5.profile-validation-receipt.v6",
        "site_initialization_used": False,
        "tracked_checkout_clean": True,
        "validation_code_delivery": "EXACT_COMMIT_GIT_BLOB_STDIN",
        "validation_code_identity_claim_effect": "NONE",
        "validation_code_origin": "OUTER_SIGNED_GIT_BLOB_LAUNCHER_REQUIRED",
        "validation_data_origin": "EXACT_REVIEWED_GIT_BLOBS",
        "validation_scope": (
            "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_EXACT_CODE_TREE"
        ),
        "validator_blob_sha": _exact_validator_source(
            _REPOSITORY_ROOT, _CODE_COMMIT_SHA
        )[0],
        "worktree_imports_used": False,
''',
    "receipt expectation",
)

# Replace tests whose old shape executed the worktree validator directly.
new_startup_tests = '''def test_nonisolated_execution_rejects_before_dependency_import(
    tmp_path: Path,
) -> None:
    fake_root = tmp_path / "pythonpath"
    fake_root.mkdir()
    marker = tmp_path / "fake-dependency-imported"
    fake_root.joinpath("sitecustomize.py").write_text(
        "from pathlib import Path\\n"
        f"Path({str(marker)!r}).write_text('imported', encoding='utf-8')\\n",
        encoding="utf-8",
    )
    _, source = _exact_validator_source(_REPOSITORY_ROOT, _CODE_COMMIT_SHA)
    environment = _validator_environment()
    environment["PYTHONPATH"] = str(fake_root)
    completed = subprocess.run(
        [str(_TRUSTED_PYTHON), "-S", "-"],
        input=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env=environment,
        timeout=30,
    )
    assert completed.returncode == 2
    assert b"signed outer Git-blob launcher" in completed.stderr
    assert completed.stdout == b""
    assert not marker.exists()


def test_isolated_mode_without_no_site_is_rejected() -> None:
    _, source = _exact_validator_source(_REPOSITORY_ROOT, _CODE_COMMIT_SHA)
    completed = subprocess.run(
        [str(_TRUSTED_PYTHON), "-I", "-"],
        input=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env=_validator_environment(),
        timeout=30,
    )
    assert completed.returncode == 2
    assert b"signed outer Git-blob launcher" in completed.stderr
    assert completed.stdout == b""


def test_direct_worktree_path_is_not_an_admitted_launcher() -> None:
    completed = subprocess.run(
        [str(_TRUSTED_PYTHON), "-I", "-S", str(_VALIDATOR_SCRIPT)],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env=_validator_environment(),
        timeout=30,
    )
    assert completed.returncode == 2
    assert b"signed outer Git-blob launcher" in completed.stderr
    assert completed.stdout == b""


def test_virtualenv_pth_executes_under_i_but_not_the_admitted_runtime(
    tmp_path: Path,
) -> None:
    import venv

    environment_root = tmp_path / "venv"
    venv.EnvBuilder(with_pip=False).create(environment_root)
    python = environment_root / "bin/python"
    purelib_result = subprocess.run(
        [python, "-c", "import sysconfig; print(sysconfig.get_paths()['purelib'])"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert purelib_result.returncode == 0, purelib_result.stderr.decode("utf-8")
    purelib = Path(purelib_result.stdout.decode("utf-8").strip())
    marker = tmp_path / "pth-executed-before-validator"
    purelib.joinpath("increment5_attack.pth").write_text(
        "import pathlib; "
        f"pathlib.Path({str(marker)!r}).write_text('executed', encoding='utf-8')\\n",
        encoding="utf-8",
    )
    _, source = _exact_validator_source(_REPOSITORY_ROOT, _CODE_COMMIT_SHA)
    vulnerable_shape = subprocess.run(
        [python, "-I", "-"],
        input=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env=_validator_environment(),
        timeout=30,
    )
    assert vulnerable_shape.returncode == 2
    assert marker.read_text(encoding="utf-8") == "executed"
    marker.unlink()

    wrong_runtime = _run_isolated_bytes(
        canonical_json_bytes(_fixture_manifest()),
        python_executable=python,
    )
    assert wrong_runtime.returncode == 2
    assert b"trusted system Python executable is required" in wrong_runtime.stderr
    assert wrong_runtime.stdout == b""
    assert not marker.exists()

    admitted = _run_isolated(_fixture_manifest())
    assert admitted.returncode == 0, admitted.stderr.decode("utf-8")
    assert not marker.exists()
    receipt = json.loads(admitted.stdout.decode("utf-8"))
    assert receipt["python_runtime_executable"] == "/usr/bin/python3"
    assert receipt["site_initialization_used"] is False
    assert receipt["external_python_packages_used"] is False


'''
tests = replace_section(
    tests,
    "def test_nonisolated_execution_rejects_before_dependency_import(\n",
    "def test_validator_requires_matching_commit_and_tree_arguments()",
    new_startup_tests,
    "startup tests",
)

new_identity_test = '''def test_validator_requires_matching_commit_tree_and_blob_arguments() -> None:
    raw = canonical_json_bytes(_fixture_manifest())
    _, source = _exact_validator_source(_REPOSITORY_ROOT, _CODE_COMMIT_SHA)
    unbound = subprocess.run(
        [str(_TRUSTED_PYTHON), "-I", "-S", "-"],
        input=source,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env=_validator_environment(),
        timeout=30,
    )
    assert unbound.returncode == 2
    assert b"exact outer launch arguments are required" in unbound.stderr
    assert unbound.stdout == b""

    wrong_commit = _run_isolated_bytes(
        raw,
        expected_commit="0" * 40,
        expected_tree=_CODE_TREE_SHA,
    )
    assert wrong_commit.returncode == 2
    assert b"code commit SHA differs from expected identity" in wrong_commit.stderr

    wrong_tree = _run_isolated_bytes(
        raw,
        expected_commit=_CODE_COMMIT_SHA,
        expected_tree="0" * 40,
    )
    assert wrong_tree.returncode == 2
    assert b"code tree SHA differs from expected identity" in wrong_tree.stderr

    wrong_blob = _run_isolated_bytes(raw, expected_validator_blob="0" * 40)
    assert wrong_blob.returncode == 2
    assert b"validator blob SHA differs from expected identity" in wrong_blob.stderr


def test_dirty_worktree_validator_is_never_executed_by_admitted_launcher(
    tmp_path: Path,
) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)
    marker = tmp_path / "dirty-validator-executed"
    source = clone / _VALIDATOR_RELATIVE_PATH
    source.write_text(
        "from pathlib import Path\\n"
        f"Path({str(marker)!r}).write_text('executed', encoding='utf-8')\\n"
        "print('fabricated receipt')\\n",
        encoding="utf-8",
    )
    completed = _run_isolated_bytes(
        canonical_json_bytes(_fixture_manifest()),
        root=clone,
        expected_commit=clone_commit,
        expected_tree=clone_tree,
    )
    assert completed.returncode == 2
    assert completed.stderr == (
        b"increment5 profile validation failed: "
        b"tracked repository checkout differs from HEAD\\n"
    )
    assert completed.stdout == b""
    assert not marker.exists()


'''
tests = replace_section(
    tests,
    "def test_validator_requires_matching_commit_and_tree_arguments() -> None:\n",
    "def test_path_selected_fake_git_is_never_used",
    new_identity_test,
    "identity and dirty-validator tests",
)

# Adapt runpy probes to the new stdin-only bootstrap and repository constructor.
tests = replace_once(
    tests,
    'namespace = runpy.run_path(sys.argv[1], run_name="validator-probe")',
    'sys.argv[0] = "-"\nnamespace = runpy.run_path(sys.argv[1], run_name="validator-probe")',
    "bounded probe bootstrap",
)
tests = replace_once(
    tests,
    'namespace = runpy.run_path(sys.argv[1], run_name="validator-completion-probe")\nruntime = namespace["_TrustedPythonRuntime"]()\nview = namespace["_TrustedRepositoryView"](Path(sys.argv[2]))',
    'sys.argv[0] = "-"\nnamespace = runpy.run_path(sys.argv[1], run_name="validator-completion-probe")\nruntime = namespace["_TrustedPythonRuntime"]()\nroot = Path(sys.argv[2])\nview = namespace["_TrustedRepositoryView"](root, root / ".git", root / ".git/index")',
    "completion probe constructor",
)
tests = replace_once(
    tests,
    '''    namespace["_emit_receipt"](
        runtime, view, sys.argv[3], sys.argv[4],
        {"authority_effect":"NONE"}, buffer
    )''',
    '''    blob = namespace["_git_sha"](
        view,
        f"{sys.argv[3]}:scripts/sdlc/increment5_profile_validator.py",
        "validator blob SHA",
    )
    namespace["_emit_receipt"](
        runtime, view, sys.argv[3], sys.argv[4], blob,
        {"authority_effect":"NONE"}, buffer
    )''',
    "completion probe receipt",
)

new_source_test = '''def test_validator_source_has_closed_outer_launch_and_repository_boundaries() -> None:
    source = _VALIDATOR_SCRIPT.read_text(encoding="utf-8")
    bootstrap = source.index("or sys.argv[0] != \"-\"")
    assert source.index("import sys") < bootstrap < source.index("import hashlib")
    assert '_TRUSTED_PYTHON_EXECUTABLE = Path("/usr/bin/python3")' in source
    assert "ROOT_OWNED_SYSTEM_PYTHON_NO_SITE" in source
    assert '"site_initialization_used": False' in source
    assert "jsonschema" not in source
    assert "importlib" not in source
    assert "tarfile" not in source
    assert "tempfile" not in source
    assert 'f"--git-dir={self.git_dir}"' in source
    assert 'f"--work-tree={self.root}"' in source
    assert '"--no-replace-objects"' in source
    assert '"core.fsmonitor=false"' in source
    assert '"GIT_NO_REPLACE_OBJECTS": "1"' in source
    assert "_reject_hidden_index_flags" in source
    assert "require_validator_blob" in source
    assert '"executed_source_identity_attested": False' in source
    assert '"outer_signed_workflow_binding_required": True' in source
    assert '"validation_code_delivery": "EXACT_COMMIT_GIT_BLOB_STDIN"' in source
    main = source.split("def main() -> int:", 1)[1]
    assert main.index("repository.require_stable_clean_tree(") < main.index(
        "_load_reviewed_profile_data("
    )
    assert main.index("repository.require_validator_blob(") < main.index(
        "_read_manifest_descriptor("
    )
    emit = source.split("def _emit_receipt(", 1)[1].split("def main()", 1)[0]
    assert emit.index("runtime.require_unchanged()") < emit.index(
        "repository.require_stable_clean_tree("
    ) < emit.index("repository.require_validator_blob(") < emit.index(
        "output.write(raw)"
    )


'''
tests = replace_section(
    tests,
    "def test_validator_source_has_closed_dependency_and_repository_boundaries() -> None:\n",
    "def test_isolated_validator_rejects_noncanonical_and_duplicate_json()",
    new_source_test,
    "source boundary test",
)
TESTS.write_text(tests, encoding="utf-8")

launcher_block = '''```bash
set -euo pipefail
REPOSITORY_ROOT="$(pwd -P)"
GIT_DIR="$REPOSITORY_ROOT/.git"
GIT_INDEX_FILE="$GIT_DIR/index"
PROFILE_MANIFEST="${PROFILE_MANIFEST:?canonical profile path required}"
CODE_COMMIT_SHA="$(
  env -i PATH=/usr/bin:/bin LC_ALL=C GIT_CONFIG_GLOBAL=/dev/null \\
    GIT_CONFIG_NOSYSTEM=1 GIT_NO_REPLACE_OBJECTS=1 \\
    GIT_DIR="$GIT_DIR" GIT_WORK_TREE="$REPOSITORY_ROOT" \\
    GIT_INDEX_FILE="$GIT_INDEX_FILE" \\
    /usr/bin/git --git-dir="$GIT_DIR" --work-tree="$REPOSITORY_ROOT" \\
      --no-replace-objects -c core.fsmonitor=false \\
      rev-parse --verify 'HEAD^{commit}'
)"
CODE_TREE_SHA="$(
  env -i PATH=/usr/bin:/bin LC_ALL=C GIT_CONFIG_GLOBAL=/dev/null \\
    GIT_CONFIG_NOSYSTEM=1 GIT_NO_REPLACE_OBJECTS=1 \\
    GIT_DIR="$GIT_DIR" GIT_WORK_TREE="$REPOSITORY_ROOT" \\
    GIT_INDEX_FILE="$GIT_INDEX_FILE" \\
    /usr/bin/git --git-dir="$GIT_DIR" --work-tree="$REPOSITORY_ROOT" \\
      --no-replace-objects -c core.fsmonitor=false \\
      rev-parse --verify 'HEAD^{tree}'
)"
VALIDATOR_PATH='scripts/sdlc/increment5_profile_validator.py'
VALIDATOR_BLOB_SHA="$(
  env -i PATH=/usr/bin:/bin LC_ALL=C GIT_CONFIG_GLOBAL=/dev/null \\
    GIT_CONFIG_NOSYSTEM=1 GIT_NO_REPLACE_OBJECTS=1 \\
    GIT_DIR="$GIT_DIR" GIT_WORK_TREE="$REPOSITORY_ROOT" \\
    GIT_INDEX_FILE="$GIT_INDEX_FILE" \\
    /usr/bin/git --git-dir="$GIT_DIR" --work-tree="$REPOSITORY_ROOT" \\
      --no-replace-objects -c core.fsmonitor=false \\
      rev-parse --verify "$CODE_COMMIT_SHA:$VALIDATOR_PATH"
)"
env -i PATH=/usr/bin:/bin LC_ALL=C GIT_CONFIG_GLOBAL=/dev/null \\
  GIT_CONFIG_NOSYSTEM=1 GIT_NO_REPLACE_OBJECTS=1 \\
  GIT_DIR="$GIT_DIR" GIT_WORK_TREE="$REPOSITORY_ROOT" \\
  GIT_INDEX_FILE="$GIT_INDEX_FILE" \\
  /usr/bin/git --git-dir="$GIT_DIR" --work-tree="$REPOSITORY_ROOT" \\
    --no-replace-objects -c core.fsmonitor=false \\
    cat-file blob "$VALIDATOR_BLOB_SHA" | \\
  env -i PATH=/usr/bin:/bin LC_ALL=C PYTHONUTF8=1 \\
    /usr/bin/python3 -I -S - \\
      --repository-root "$REPOSITORY_ROOT" \\
      --git-dir "$GIT_DIR" \\
      --index-file "$GIT_INDEX_FILE" \\
      --manifest-fd 3 \\
      --expected-validator-blob-sha "$VALIDATOR_BLOB_SHA" \\
      --expected-code-commit-sha "$CODE_COMMIT_SHA" \\
      --expected-code-tree-sha "$CODE_TREE_SHA" \\
      3<"$PROFILE_MANIFEST"
```'''

for path in (DECISION, EVALUATION, OPERATIONS):
    text = path.read_text(encoding="utf-8")
    start = text.find("```bash\n")
    if start < 0:
        start = text.find("```text\n")
    if start < 0:
        raise RuntimeError(f"{path.name}: validator command block missing")
    # Choose the command block containing increment5_profile_validator.py.
    search = 0
    selected = None
    while True:
        candidate = text.find("```", search)
        if candidate < 0:
            break
        close = text.find("```", candidate + 3)
        if close < 0:
            break
        block = text[candidate:close + 3]
        if "increment5_profile_validator.py" in block:
            selected = (candidate, close + 3)
            break
        search = close + 3
    if selected is None:
        raise RuntimeError(f"{path.name}: exact validator block missing")
    text = text[:selected[0]] + launcher_block + text[selected[1]:]
    text = text.replace(
        "Receipt v5",
        "Receipt v6",
    ).replace(
        "profile-validation-receipt.v5",
        "profile-validation-receipt.v6",
    ).replace(
        "EXACT_TRACKED_EXECUTABLE_STDLIB_ONLY",
        "OUTER_SIGNED_GIT_BLOB_LAUNCHER_REQUIRED",
    )
    binding = (
        "\n\nThe inner receipt deliberately sets "
        "`executed_source_identity_attested=false` and "
        "`validation_code_identity_claim_effect=NONE`. The signed outer "
        "workflow must bind the exact validator blob SHA, complete launcher "
        "command, system-Python/runtime-image identity, canonical manifest "
        "bytes, inner-receipt digest, Epoch, and code tree. A direct worktree-"
        "path invocation or an unbound inner receipt is `NOT_EVALUATED`.\n"
    )
    anchor = "\nThe receipt"
    position = text.find(anchor)
    if position < 0:
        position = text.find("\nReceipt v6")
    if position < 0:
        raise RuntimeError(f"{path.name}: receipt prose anchor missing")
    text = text[:position] + binding + text[position:]
    path.write_text(text, encoding="utf-8")

manifest = {
    "schema_version": "newsroom.increment5a.outer-git-blob-launcher.v1",
    "source_head": "3ebfe064cf299d5588014057e8a1769f6b1589fa",
    "product_paths": [
        str(DECISION.relative_to(ROOT)),
        str(EVALUATION.relative_to(ROOT)),
        str(OPERATIONS.relative_to(ROOT)),
        str(TESTS.relative_to(ROOT)),
        str(VALIDATOR.relative_to(ROOT)),
    ],
    "launcher_boundary": {
        "validator_source": "EXPECTED_COMMIT_GIT_BLOB",
        "delivery": "STDIN_BEFORE_VALIDATOR_EXECUTION",
        "direct_worktree_execution_admitted": False,
        "inner_source_attestation": False,
        "outer_signed_binding_required": True,
    },
    "contract_digest_unchanged": "sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c",
    "evaluation_plan_digest_unchanged": "sha256:c9d169c46a939573ffc6563704adfae973655f6394293ce591ec689f76a30959",
}
MANIFEST.write_text(json.dumps(manifest, sort_keys=True, separators=(",", ":")), encoding="utf-8")
print(json.dumps(manifest, indent=2, sort_keys=True))
