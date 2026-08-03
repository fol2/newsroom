#!/usr/bin/env python3
"""Build the cache-free exact-tree Increment 5A validator on staging only.

The final PR candidate is assembled separately as one helper-free replacement
commit over the fixed base. This transformer, its manifest, and its workflow are
never part of PR #255 or main.
"""

from __future__ import annotations

import json
from pathlib import Path
import subprocess


ROOT = Path(__file__).resolve().parents[2]
SOURCE_HEAD = "2e705938f61ba687b0c4db9f6f9aadef178d1b50"
VALIDATOR = ROOT / "scripts/sdlc/increment5_profile_validator.py"
TEST = ROOT / "newsroom/tests/test_increment5a_profile_semantic_envelope.py"
DECISION = ROOT / (
    "docs/decisions/2026-08-02-increment-5a-production-retrieval-contract.md"
)
OPERATIONS = ROOT / "docs/operations/increment-5-production-retrieval-contract.md"
EVALUATION = ROOT / (
    "docs/evaluation/2026-08-02-increment-5-retrieval-evaluation-plan-v1.md"
)
OUTPUT = ROOT / "increment5a-cache-free-validator-manifest.json"


VALIDATOR_TEXT = '#!/usr/bin/env python3\n"""Validate one canonical Increment 5 profile from an exact Git tree.\n\nThe receipt proves only that exact manifest bytes passed the reviewed profile\nstructure and semantic checks loaded from a cache-free materialization of the\nstated Git commit/tree. It grants no qualification, production, component,\nsource, model, provider, spend, write, or public-effect authority.\n"""\n\nfrom __future__ import annotations\n\nfrom contextlib import contextmanager\nimport importlib\nimport json\nimport os\nfrom pathlib import Path, PurePosixPath\nimport re\nimport shutil\nimport subprocess\nimport sys\nimport tarfile\nimport tempfile\nfrom typing import Any, Iterator\n\n\n_MAX_INPUT_BYTES = 1_048_576\n_MAX_GIT_OUTPUT_BYTES = 65_536\n_MAX_ARCHIVE_BYTES = 67_108_864\n_MAX_ARCHIVE_MEMBER_BYTES = 16_777_216\n_GIT_SHA = re.compile(r"^[0-9a-f]{40}$")\n_REPOSITORY_ROOT = Path(__file__).resolve().parents[2]\n_SCRIPT_DIRECTORY = Path(__file__).resolve().parent\n_EXPECTED_FLAGS = frozenset(\n    {\n        "--expected-code-commit-sha",\n        "--expected-code-tree-sha",\n    }\n)\n_REQUIRED_MATERIALIZED_FILES = frozenset(\n    {\n        "newsroom/__init__.py",\n        "newsroom/authority/canonical.py",\n        "newsroom/increment5/__init__.py",\n        "newsroom/increment5/profiles.py",\n    }\n)\n\n\nclass ProfileInputError(ValueError):\n    """The isolated validator input or exact-code identity is invalid."""\n\n\ndef _without_duplicate_names(pairs: list[tuple[str, Any]]) -> dict[str, Any]:\n    result: dict[str, Any] = {}\n    for name, value in pairs:\n        if name in result:\n            raise ProfileInputError(f"duplicate JSON object name: {name}")\n        result[name] = value\n    return result\n\n\ndef _fail(message: str) -> int:\n    sys.stderr.write(f"increment5 profile validation failed: {message}\\n")\n    return 2\n\n\ndef _canonical_git_sha(value: object, field: str) -> str:\n    if not isinstance(value, str) or _GIT_SHA.fullmatch(value) is None:\n        raise ProfileInputError(f"{field} must be 40 lowercase hexadecimal characters")\n    return value\n\n\ndef _parse_code_identity_args(argv: list[str]) -> tuple[str, str]:\n    if len(argv) != 4:\n        raise ProfileInputError(\n            "exact code identity arguments are required: "\n            "--expected-code-commit-sha <sha> "\n            "--expected-code-tree-sha <sha>"\n        )\n    values: dict[str, str] = {}\n    for index in range(0, len(argv), 2):\n        flag = argv[index]\n        if flag not in _EXPECTED_FLAGS:\n            raise ProfileInputError(f"unsupported argument: {flag}")\n        if flag in values:\n            raise ProfileInputError(f"duplicate argument: {flag}")\n        values[flag] = argv[index + 1]\n    if frozenset(values) != _EXPECTED_FLAGS:\n        raise ProfileInputError("exact code identity arguments are incomplete")\n    return (\n        _canonical_git_sha(\n            values["--expected-code-commit-sha"],\n            "expected code commit SHA",\n        ),\n        _canonical_git_sha(\n            values["--expected-code-tree-sha"],\n            "expected code tree SHA",\n        ),\n    )\n\n\ndef _git_executable() -> Path:\n    raw = shutil.which("git")\n    if raw is None:\n        raise ProfileInputError("Git is unavailable for exact code-tree validation")\n    path = Path(raw).resolve()\n    if not path.is_file():\n        raise ProfileInputError("Git executable is not a regular file")\n    try:\n        path.relative_to(_REPOSITORY_ROOT)\n    except ValueError:\n        return path\n    raise ProfileInputError("Git executable cannot come from the repository checkout")\n\n\ndef _git_environment(git: Path) -> dict[str, str]:\n    return {\n        "GIT_CONFIG_GLOBAL": os.devnull,\n        "GIT_CONFIG_NOSYSTEM": "1",\n        "GIT_OPTIONAL_LOCKS": "0",\n        "LANG": "C",\n        "LC_ALL": "C",\n        "PATH": str(git.parent),\n    }\n\n\ndef _run_git(git: Path, *arguments: str) -> bytes:\n    try:\n        completed = subprocess.run(\n            [str(git), "-C", str(_REPOSITORY_ROOT), *arguments],\n            stdout=subprocess.PIPE,\n            stderr=subprocess.PIPE,\n            check=False,\n            timeout=10,\n            env=_git_environment(git),\n        )\n    except (OSError, subprocess.TimeoutExpired) as exc:\n        raise ProfileInputError("cannot inspect the exact Git code tree") from exc\n    if (\n        completed.returncode != 0\n        or len(completed.stdout) > _MAX_GIT_OUTPUT_BYTES\n        or len(completed.stderr) > _MAX_GIT_OUTPUT_BYTES\n    ):\n        raise ProfileInputError("cannot inspect the exact Git code tree")\n    return completed.stdout\n\n\ndef _git_sha(git: Path, revision: str, field: str) -> str:\n    raw = _run_git(git, "rev-parse", "--verify", revision)\n    try:\n        value = raw.decode("ascii", errors="strict").strip()\n    except UnicodeError as exc:\n        raise ProfileInputError(f"{field} is not canonical Git text") from exc\n    return _canonical_git_sha(value, field)\n\n\ndef _require_exact_code_tree(\n    expected_commit: str,\n    expected_tree: str,\n) -> tuple[Path, str, str]:\n    """Bind HEAD and reject tracked changes before repository imports exist."""\n\n    git = _git_executable()\n    actual_commit = _git_sha(git, "HEAD^{commit}", "code commit SHA")\n    actual_tree = _git_sha(git, "HEAD^{tree}", "code tree SHA")\n    if actual_commit != expected_commit:\n        raise ProfileInputError("code commit SHA differs from expected identity")\n    if actual_tree != expected_tree:\n        raise ProfileInputError("code tree SHA differs from expected identity")\n    tracked_status = _run_git(\n        git,\n        "status",\n        "--porcelain=v1",\n        "--untracked-files=no",\n    )\n    if tracked_status:\n        raise ProfileInputError("tracked repository checkout differs from HEAD")\n    return git, actual_commit, actual_tree\n\n\ndef _write_git_archive(git: Path, commit: str, archive_path: Path) -> None:\n    try:\n        with archive_path.open("xb") as output:\n            completed = subprocess.run(\n                [\n                    str(git),\n                    "-C",\n                    str(_REPOSITORY_ROOT),\n                    "archive",\n                    "--format=tar",\n                    commit,\n                    "--",\n                    "newsroom",\n                ],\n                stdout=output,\n                stderr=subprocess.PIPE,\n                check=False,\n                timeout=30,\n                env=_git_environment(git),\n            )\n    except (OSError, subprocess.TimeoutExpired) as exc:\n        raise ProfileInputError("cannot materialize the exact Git code tree") from exc\n    if (\n        completed.returncode != 0\n        or len(completed.stderr) > _MAX_GIT_OUTPUT_BYTES\n        or not archive_path.is_file()\n        or archive_path.stat().st_size > _MAX_ARCHIVE_BYTES\n    ):\n        raise ProfileInputError("cannot materialize the exact Git code tree")\n\n\ndef _canonical_archive_name(name: str) -> PurePosixPath:\n    if not name or "\\\\" in name:\n        raise ProfileInputError("Git archive contains an unsafe path")\n    path = PurePosixPath(name)\n    if path.is_absolute() or any(part in {"", ".", ".."} for part in path.parts):\n        raise ProfileInputError("Git archive contains an unsafe path")\n    if "__pycache__" in path.parts or path.suffix in {".pyc", ".pyo"}:\n        raise ProfileInputError("Git archive contains executable bytecode")\n    return path\n\n\ndef _extract_exact_archive(archive_path: Path, destination: Path) -> None:\n    seen: set[str] = set()\n    total_size = 0\n    try:\n        with tarfile.open(archive_path, mode="r:") as archive:\n            for member in archive:\n                relative = _canonical_archive_name(member.name)\n                canonical_name = relative.as_posix()\n                if canonical_name in seen:\n                    raise ProfileInputError("Git archive contains a duplicate path")\n                seen.add(canonical_name)\n                target = destination.joinpath(*relative.parts)\n                if member.isdir():\n                    target.mkdir(parents=True, exist_ok=True)\n                    continue\n                if not member.isfile() or member.size < 0:\n                    raise ProfileInputError("Git archive contains a non-regular entry")\n                if member.size > _MAX_ARCHIVE_MEMBER_BYTES:\n                    raise ProfileInputError("Git archive member exceeds the size limit")\n                total_size += member.size\n                if total_size > _MAX_ARCHIVE_BYTES:\n                    raise ProfileInputError("Git archive exceeds the extraction limit")\n                target.parent.mkdir(parents=True, exist_ok=True)\n                if target.exists():\n                    raise ProfileInputError("Git archive path already exists")\n                source = archive.extractfile(member)\n                if source is None:\n                    raise ProfileInputError("Git archive member cannot be read")\n                remaining = member.size\n                with target.open("xb") as output:\n                    while remaining:\n                        chunk = source.read(min(1_048_576, remaining))\n                        if not chunk:\n                            raise ProfileInputError("Git archive member is truncated")\n                        output.write(chunk)\n                        remaining -= len(chunk)\n                    if source.read(1):\n                        raise ProfileInputError("Git archive member exceeds its size")\n    except (OSError, tarfile.TarError) as exc:\n        raise ProfileInputError("cannot extract the exact Git code tree") from exc\n    if not _REQUIRED_MATERIALIZED_FILES.issubset(seen):\n        raise ProfileInputError("Git archive omits required validator source")\n\n\ndef _path_is_within(path: Path, root: Path) -> bool:\n    try:\n        path.resolve(strict=True).relative_to(root.resolve(strict=True))\n    except (OSError, ValueError):\n        return False\n    return True\n\n\ndef _verify_newsroom_import_origins(root: Path) -> None:\n    for name, module in tuple(sys.modules.items()):\n        if name != "newsroom" and not name.startswith("newsroom."):\n            continue\n        raw_path = getattr(module, "__file__", None)\n        if not isinstance(raw_path, str):\n            raise ProfileInputError(f"reviewed module has no source path: {name}")\n        path = Path(raw_path)\n        if path.suffix != ".py" or not _path_is_within(path, root):\n            raise ProfileInputError(f"reviewed module did not load from exact tree: {name}")\n\n\n@contextmanager\ndef _materialized_repository_api(\n    git: Path,\n    commit: str,\n) -> Iterator[tuple[Any, Any, Any, Any, Any]]:\n    """Load every Newsroom module from a cache-free exact Git materialization."""\n\n    if any(name == "newsroom" or name.startswith("newsroom.") for name in sys.modules):\n        raise ProfileInputError("Newsroom modules loaded before exact-tree materialization")\n    with tempfile.TemporaryDirectory(prefix="newsroom-increment5-profile-") as raw_temp:\n        temp_root = Path(raw_temp).resolve(strict=True)\n        if _path_is_within(temp_root, _REPOSITORY_ROOT):\n            raise ProfileInputError("exact Git materialization cannot use the checkout")\n        archive_path = temp_root / "tree.tar"\n        source_root = temp_root / "source"\n        source_root.mkdir(mode=0o700)\n        _write_git_archive(git, commit, archive_path)\n        _extract_exact_archive(archive_path, source_root)\n        archive_path.unlink()\n\n        original_path = list(sys.path)\n        original_dont_write = sys.dont_write_bytecode\n        filtered_path = [\n            entry\n            for entry in original_path\n            if entry\n            and Path(entry).resolve() not in {_REPOSITORY_ROOT, _SCRIPT_DIRECTORY}\n        ]\n        sys.path[:] = [str(source_root), *filtered_path]\n        sys.dont_write_bytecode = True\n        importlib.invalidate_caches()\n        try:\n            canonical_module = importlib.import_module("newsroom.authority.canonical")\n            profiles_module = importlib.import_module("newsroom.increment5.profiles")\n            _verify_newsroom_import_origins(source_root)\n            yield (\n                canonical_module.CanonicalizationError,\n                canonical_module.canonical_json_bytes,\n                canonical_module.digest_bytes,\n                profiles_module.Increment5ProfileError,\n                profiles_module._check_profile_manifest,\n            )\n        finally:\n            for name in tuple(sys.modules):\n                if name == "newsroom" or name.startswith("newsroom."):\n                    del sys.modules[name]\n            sys.path[:] = original_path\n            sys.dont_write_bytecode = original_dont_write\n            importlib.invalidate_caches()\n\n\ndef main() -> int:\n    try:\n        expected_commit, expected_tree = _parse_code_identity_args(sys.argv[1:])\n        git, actual_commit, actual_tree = _require_exact_code_tree(\n            expected_commit,\n            expected_tree,\n        )\n    except ProfileInputError as exc:\n        return _fail(str(exc))\n\n    raw = sys.stdin.buffer.read(_MAX_INPUT_BYTES + 1)\n    if len(raw) > _MAX_INPUT_BYTES:\n        return _fail("input exceeds 1048576 bytes")\n\n    try:\n        with _materialized_repository_api(git, actual_commit) as repository_api:\n            (\n                canonicalization_error_type,\n                canonical_json_bytes,\n                digest_bytes,\n                profile_error_type,\n                check_profile_manifest,\n            ) = repository_api\n            try:\n                value = json.loads(\n                    raw.decode("utf-8", errors="strict"),\n                    object_pairs_hook=_without_duplicate_names,\n                )\n                canonical = canonical_json_bytes(value)\n            except (\n                UnicodeError,\n                json.JSONDecodeError,\n                canonicalization_error_type,\n                ProfileInputError,\n            ) as exc:\n                return _fail(str(exc))\n\n            if raw != canonical:\n                return _fail("input is not canonical JSON")\n            if not isinstance(value, dict):\n                return _fail("profile manifest must be an object")\n\n            try:\n                check_profile_manifest(value)\n            except profile_error_type as exc:\n                return _fail(str(exc))\n\n            profile_kind = value.get("profile_kind")\n            if not isinstance(profile_kind, str):\n                return _fail("profile kind is not canonical text")\n\n            receipt = {\n                "authority_effect": "NONE",\n                "code_commit_sha": actual_commit,\n                "code_tree_sha": actual_tree,\n                "manifest_digest": digest_bytes(raw),\n                "production_activation_authorized": False,\n                "profile_kind": profile_kind,\n                "qualification_authority_granted": False,\n                "schema_version": "newsroom.increment5.profile-validation-receipt.v3",\n                "tracked_checkout_clean": True,\n                "validation_code_origin": "CACHE_FREE_EXACT_GIT_ARCHIVE",\n                "validation_scope": (\n                    "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_EXACT_CODE_TREE"\n                ),\n                "worktree_imports_used": False,\n            }\n            sys.stdout.buffer.write(canonical_json_bytes(receipt) + b"\\n")\n            return 0\n    except ProfileInputError as exc:\n        return _fail(str(exc))\n    except Exception as exc:  # pragma: no cover - fail-closed import boundary\n        return _fail(f"cannot load reviewed profile validator: {exc}")\n\n\nif __name__ == "__main__":\n    raise SystemExit(main())\n'


def _replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label} replacement count differs: {count}")
    return text.replace(old, new, 1)


def _replace_block(
    text: str,
    start: str,
    end: str,
    replacement: str,
    label: str,
) -> str:
    if text.count(start) != 1 or text.count(end) != 1:
        raise RuntimeError(f"{label} block markers differ")
    prefix, remainder = text.split(start, 1)
    _, suffix = remainder.split(end, 1)
    return prefix + replacement + end + suffix


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
        raise RuntimeError("staging product source differs from reviewed predecessor")


def _transform_test(text: str) -> str:
    text = _replace_once(
        text,
        "import os\nfrom pathlib import Path\nimport subprocess\n",
        "import os\nfrom pathlib import Path\nimport py_compile\nimport subprocess\n",
        "test imports",
    )
    text = _replace_once(
        text,
        '''def _run_isolated(manifest: dict[str, Any]) -> subprocess.CompletedProcess[bytes]:
    return _run_isolated_bytes(canonical_json_bytes(manifest))


def _closure_cell(
''',
        '''def _run_isolated(manifest: dict[str, Any]) -> subprocess.CompletedProcess[bytes]:
    return _run_isolated_bytes(canonical_json_bytes(manifest))


def _clone_exact_head(destination: Path) -> tuple[Path, str, str]:
    clone = destination / "repo"
    cloned = subprocess.run(
        [
            "git",
            "clone",
            "--shared",
            "--no-checkout",
            "--quiet",
            str(_REPOSITORY_ROOT),
            str(clone),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert cloned.returncode == 0, cloned.stderr.decode("utf-8")
    checked_out = subprocess.run(
        ["git", "-C", str(clone), "checkout", "--detach", _CODE_COMMIT_SHA],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=30,
    )
    assert checked_out.returncode == 0, checked_out.stderr.decode("utf-8")
    clone_commit, clone_tree = _code_identity(clone)
    assert (clone_commit, clone_tree) == (_CODE_COMMIT_SHA, _CODE_TREE_SHA)
    return clone, clone_commit, clone_tree


def _closure_cell(
''',
        "clone helper",
    )
    text = _replace_once(
        text,
        '''        "qualification_authority_granted": False,
        "repository_clean": True,
        "schema_version": "newsroom.increment5.profile-validation-receipt.v2",
        "validation_scope": (
            "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_CLEAN_CODE_TREE"
        ),
''',
        '''        "qualification_authority_granted": False,
        "schema_version": "newsroom.increment5.profile-validation-receipt.v3",
        "tracked_checkout_clean": True,
        "validation_code_origin": "CACHE_FREE_EXACT_GIT_ARCHIVE",
        "validation_scope": (
            "REVIEWED_PROFILE_STRUCTURE_SEMANTICS_AND_EXACT_CODE_TREE"
        ),
        "worktree_imports_used": False,
''',
        "receipt expectation",
    )
    text = _replace_once(
        text,
        "        # The fresh -I process reloads exact clean source and rejects the same\n",
        "        # The fresh -I process imports only the cache-free exact Git tree and\n",
        "closure comment first line",
    )
    text = _replace_once(
        text,
        "        # bytes; the caller's mutated cell cannot cross the process boundary.\n",
        "        # rejects the same bytes; the mutated cell cannot cross that boundary.\n",
        "closure comment second line",
    )

    new_repository_tests = r'''def test_tracked_repository_code_is_rejected_before_materialization(
    tmp_path: Path,
) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)

    profile_source = clone / "newsroom/increment5/profiles.py"
    profile_source.write_text(
        profile_source.read_text(encoding="utf-8")
        + "\nraise RuntimeError('dirty profile import executed')\n",
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
        b"tracked repository checkout differs from HEAD\n"
    )
    assert completed.stdout == b""


def test_ignored_bytecode_cannot_replace_materialized_validator_source(
    tmp_path: Path,
) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)
    cache_tag = sys.implementation.cache_tag
    assert isinstance(cache_tag, str) and cache_tag

    for relative in (
        "newsroom/authority/canonical.py",
        "newsroom/increment5/profiles.py",
    ):
        source = clone / relative
        cache = source.parent / "__pycache__" / (
            f"{source.stem}.{cache_tag}.pyc"
        )
        cache.parent.mkdir(parents=True, exist_ok=True)
        poison = tmp_path / f"poison-{source.stem}.py"
        poison.write_text(
            "raise RuntimeError('ignored checkout bytecode executed')\n",
            encoding="utf-8",
        )
        py_compile.compile(
            str(poison),
            cfile=str(cache),
            dfile=str(source),
            doraise=True,
            invalidation_mode=py_compile.PycInvalidationMode.UNCHECKED_HASH,
        )

    assert _git_text(
        clone,
        "status",
        "--porcelain=v1",
        "--untracked-files=no",
    ) == ""
    completed = _run_isolated_bytes(
        canonical_json_bytes(_fixture_manifest()),
        root=clone,
        expected_commit=clone_commit,
        expected_tree=clone_tree,
    )
    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    assert b"ignored checkout bytecode executed" not in completed.stderr
    receipt = json.loads(completed.stdout.decode("utf-8"))
    assert receipt["code_commit_sha"] == clone_commit
    assert receipt["code_tree_sha"] == clone_tree
    assert receipt["validation_code_origin"] == "CACHE_FREE_EXACT_GIT_ARCHIVE"
    assert receipt["worktree_imports_used"] is False


'''
    text = _replace_block(
        text,
        "def test_dirty_repository_code_is_rejected_before_import(\n",
        "def test_validator_checks_code_tree_before_repository_import() -> None:\n",
        new_repository_tests,
        "repository tests",
    )

    new_order_test = r'''def test_validator_materializes_exact_tree_before_repository_import() -> None:
    source = _VALIDATOR_SCRIPT.read_text(encoding="utf-8")
    main_source = source.split("def main() -> int:", 1)[1]
    assert main_source.index("_require_exact_code_tree(") < main_source.index(
        "_materialized_repository_api("
    )
    materialized_source = source.split(
        "def _materialized_repository_api(",
        1,
    )[1]
    assert materialized_source.index("_write_git_archive(") < (
        materialized_source.index(
            'importlib.import_module("newsroom.authority.canonical")'
        )
    )
    assert '"--untracked-files=no"' in source
    assert '"--untracked-files=all"' not in source


'''
    text = _replace_block(
        text,
        "def test_validator_checks_code_tree_before_repository_import() -> None:\n",
        "def test_isolated_validator_rejects_noncanonical_and_duplicate_json() -> None:\n",
        new_order_test,
        "validator order test",
    )
    return text


def _transform_decision(text: str) -> str:
    old = '''Before importing repository validation code, the validator resolves the actual
Git commit and tree, requires them to equal the caller-supplied identities, and
rejects any staged, tracked, or untracked checkout difference. It then rejects
non-canonical JSON, duplicate names, identity drift, wrong profile/eligibility
pairs, widened budgets or effects, fixture substitution, unsafe dataset state,
and missing actual-service requirements. Its canonical v2 receipt binds the
manifest digest, profile kind, `code_commit_sha`, `code_tree_sha`, and
`repository_clean=true` while stating:
'''
    new = '''Before importing any Newsroom module, the validator resolves the actual Git
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
    return _replace_once(text, old, new, "decision validator boundary")


def _transform_operations(text: str) -> str:
    old = '''The validator verifies the supplied Git commit and tree against a clean checkout
before importing repository code. Receipt v2 binds the manifest digest, profile
kind, `code_commit_sha`, `code_tree_sha`, and `repository_clean=true` while
stating `authority_effect=NONE`, `qualification_authority_granted=false`, and
`production_activation_authorized=false`. The receipt tree must equal the
frozen Epoch tree; mismatch is `NOT_EVALUATED`. It is necessary profile
evidence, never sufficient qualification evidence.
'''
    new = '''The validator verifies the supplied Git commit and tree and rejects staged or
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
    return _replace_once(text, old, new, "operations validator boundary")


def _transform_evaluation(text: str) -> str:
    old = '''Cross-Epoch pooling is prohibited. A missing or mismatched Epoch is
`NOT_EVALUATED`. Every profile-validation receipt is v2, records a clean actual
Git commit and tree verified before repository validation code is imported, and
must have `code_tree_sha` equal to the Epoch's frozen `code_tree_sha`. A missing,
dirty, or mismatched code tree is also `NOT_EVALUATED`. Superseded Epoch Runs
remain retained. The Epoch record binds the plan digest externally at Run
creation, so the machine plan does not contain a self-referential digest.
'''
    new = '''Cross-Epoch pooling is prohibited. A missing or mismatched Epoch is
`NOT_EVALUATED`. Every profile-validation receipt is v3, binds the actual Git
commit and tree, and records that staged/tracked checkout state was clean and
that all Newsroom imports came from a cache-free exact-commit materialization
rather than checkout or ignored bytecode. Its `code_tree_sha` must equal the
Epoch's frozen `code_tree_sha`; a missing, dirty, non-materialized, or mismatched
code tree is `NOT_EVALUATED`. Superseded Epoch Runs remain retained. The Epoch
record binds the plan digest externally at Run creation, so the machine plan
does not contain a self-referential digest.
'''
    return _replace_once(text, old, new, "evaluation receipt boundary")


def main() -> int:
    _require_source_boundary()

    current_validator = VALIDATOR.read_text(encoding="utf-8")
    if "profile-validation-receipt.v2" not in current_validator:
        raise RuntimeError("source validator is not the reviewed v2 predecessor")
    VALIDATOR.write_text(VALIDATOR_TEXT, encoding="utf-8")

    TEST.write_text(
        _transform_test(TEST.read_text(encoding="utf-8")),
        encoding="utf-8",
    )
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
        "ignored_bytecode_used": False,
        "receipt_schema_version": "newsroom.increment5.profile-validation-receipt.v3",
        "schema_version": "newsroom.increment5a.cache-free-validator.v1",
        "source_head": SOURCE_HEAD,
        "tracked_checkout_policy": "REJECT_STAGED_OR_TRACKED_DIFFERENCES",
        "validation_code_origin": "CACHE_FREE_EXACT_GIT_ARCHIVE",
        "worktree_imports_used": False,
    }
    raw = json.dumps(
        manifest,
        ensure_ascii=False,
        sort_keys=True,
        separators=(",", ":"),
    ).encode("utf-8")
    OUTPUT.write_bytes(raw + b"\n")
    print(json.dumps(manifest, indent=2, sort_keys=True))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
