#!/usr/bin/env python3
"""Generate direct tracked-content verification for Increment 5A.

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
MANIFEST = ROOT / "increment5a-content-addressed-cleanliness-manifest.json"


def replace_once(text: str, old: str, new: str, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


validator = VALIDATOR.read_text(encoding="utf-8")
validator = replace_once(
    validator,
    "from pathlib import Path\n",
    "from pathlib import Path, PurePosixPath\n",
    "pure path import",
)
validator = replace_once(
    validator,
    "_MAX_INDEX_LIST_BYTES = 16_777_216\n_MAX_REVIEWED_BLOB_BYTES = 16_777_216\n",
    "_MAX_INDEX_LIST_BYTES = 16_777_216\n"
    "_MAX_TRACKED_TREE_BYTES = 16_777_216\n"
    "_MAX_TRACKED_FILE_BYTES = 67_108_864\n"
    "_MAX_TRACKED_TOTAL_BYTES = 536_870_912\n"
    "_MAX_TRACKED_PATHS = 100_000\n"
    "_MAX_REVIEWED_BLOB_BYTES = 16_777_216\n",
    "tracked content bounds",
)
validator = replace_once(
    validator,
    '''            "-c",
            "core.fsmonitor=false",
            *arguments,
''',
    '''            "-c",
            "core.fsmonitor=false",
            "-c",
            "core.trustctime=true",
            "-c",
            "core.checkStat=default",
            "-c",
            "core.ignoreStat=false",
            "-c",
            "core.fileMode=true",
            *arguments,
''',
    "Git config closure",
)
old_clean = '''    def require_stable_clean_tree(self, commit: str, tree: str) -> None:
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

'''
new_clean = '''    def require_stable_clean_tree(self, commit: str, tree: str) -> None:
        actual_commit = _git_sha(self, "HEAD^{commit}", "code commit SHA")
        actual_tree = _git_sha(self, "HEAD^{tree}", "code tree SHA")
        if actual_commit != commit:
            raise ProfileInputError("code commit SHA differs from expected identity")
        if actual_tree != tree:
            raise ProfileInputError("code tree SHA differs from expected identity")
        self._reject_hidden_index_flags()
        expected = self._read_expected_tree(commit)
        self._require_index_matches_tree(expected)
        self._require_worktree_matches_tree(expected)

    @staticmethod
    def _parse_tree_record(
        record: bytes,
        *,
        index: bool,
    ) -> tuple[str, str, str]:
        try:
            metadata, raw_path = record.split(b"\\t", 1)
            fields = metadata.split(b" ")
            if index:
                if len(fields) != 3 or fields[2] != b"0":
                    raise ValueError
                mode_raw, oid_raw = fields[:2]
            else:
                if len(fields) != 3 or fields[1] != b"blob":
                    raise ValueError
                mode_raw, oid_raw = fields[0], fields[2]
            mode = mode_raw.decode("ascii", errors="strict")
            oid = oid_raw.decode("ascii", errors="strict")
            path = raw_path.decode("utf-8", errors="strict")
        except (ValueError, UnicodeError) as exc:
            raise ProfileInputError("tracked tree inventory is malformed") from exc
        if mode not in {"100644", "100755", "120000"}:
            raise ProfileInputError("tracked tree contains an unsupported entry")
        if not _GIT_SHA.fullmatch(oid):
            raise ProfileInputError("tracked tree contains a malformed blob identity")
        pure = PurePosixPath(path)
        if (
            not path
            or pure.is_absolute()
            or any(part in {"", ".", ".."} for part in pure.parts)
        ):
            raise ProfileInputError("tracked tree contains an unsafe path")
        return path, mode, oid

    def _read_expected_tree(self, commit: str) -> dict[str, tuple[str, str]]:
        raw = self.run(
            "ls-tree",
            "-r",
            "-z",
            "--full-tree",
            commit,
            max_stdout_bytes=_MAX_TRACKED_TREE_BYTES,
            timeout_seconds=30,
            failure_message="cannot inspect exact tracked tree",
        )
        result: dict[str, tuple[str, str]] = {}
        for record in raw.split(b"\\0"):
            if not record:
                continue
            path, mode, oid = self._parse_tree_record(record, index=False)
            if path in result:
                raise ProfileInputError("tracked tree contains a duplicate path")
            result[path] = (mode, oid)
            if len(result) > _MAX_TRACKED_PATHS:
                raise ProfileInputError("tracked tree exceeds the path limit")
        if not result:
            raise ProfileInputError("tracked tree is empty")
        return result

    def _require_index_matches_tree(
        self,
        expected: dict[str, tuple[str, str]],
    ) -> None:
        raw = self.run(
            "ls-files",
            "-s",
            "-z",
            "--",
            max_stdout_bytes=_MAX_TRACKED_TREE_BYTES,
            timeout_seconds=30,
            failure_message="cannot inspect exact tracked index",
        )
        actual: dict[str, tuple[str, str]] = {}
        for record in raw.split(b"\\0"):
            if not record:
                continue
            path, mode, oid = self._parse_tree_record(record, index=True)
            if path in actual:
                raise ProfileInputError("tracked index contains a duplicate path")
            actual[path] = (mode, oid)
        if actual != expected:
            raise ProfileInputError("tracked repository index differs from HEAD")

    def _tracked_path(
        self,
        relative: str,
        directories: set[Path],
    ) -> Path:
        pure = PurePosixPath(relative)
        current = self.root
        for part in pure.parts[:-1]:
            current = current / part
            if current in directories:
                continue
            try:
                info = current.lstat()
            except OSError as exc:
                raise ProfileInputError(
                    "tracked repository checkout differs from HEAD"
                ) from exc
            if stat.S_ISLNK(info.st_mode) or not stat.S_ISDIR(info.st_mode):
                raise ProfileInputError(
                    "tracked repository checkout differs from HEAD"
                )
            directories.add(current)
        return current / pure.parts[-1]

    @staticmethod
    def _blob_digest_for_bytes(data: bytes) -> str:
        digest = hashlib.sha1(usedforsecurity=False)
        digest.update(f"blob {len(data)}\\0".encode("ascii"))
        digest.update(data)
        return digest.hexdigest()

    @staticmethod
    def _stable_stat_identity(info: os.stat_result) -> tuple[int, ...]:
        return (
            info.st_dev,
            info.st_ino,
            info.st_mode,
            info.st_size,
            info.st_mtime_ns,
            info.st_ctime_ns,
        )

    def _regular_blob_digest(
        self,
        path: Path,
        before: os.stat_result,
    ) -> tuple[str, int]:
        if before.st_size > _MAX_TRACKED_FILE_BYTES:
            raise ProfileInputError("tracked file exceeds the verification limit")
        flags = os.O_RDONLY | getattr(os, "O_CLOEXEC", 0)
        flags |= getattr(os, "O_NOFOLLOW", 0)
        try:
            descriptor = os.open(path, flags)
        except OSError as exc:
            raise ProfileInputError(
                "tracked repository checkout differs from HEAD"
            ) from exc
        try:
            opened = os.fstat(descriptor)
            if self._stable_stat_identity(opened) != self._stable_stat_identity(before):
                raise ProfileInputError(
                    "tracked repository checkout changed during verification"
                )
            digest = hashlib.sha1(usedforsecurity=False)
            digest.update(f"blob {opened.st_size}\\0".encode("ascii"))
            consumed = 0
            while True:
                chunk = os.read(descriptor, 1_048_576)
                if not chunk:
                    break
                consumed += len(chunk)
                if consumed > opened.st_size:
                    raise ProfileInputError(
                        "tracked repository checkout changed during verification"
                    )
                digest.update(chunk)
            after = os.fstat(descriptor)
            if (
                consumed != opened.st_size
                or self._stable_stat_identity(after)
                != self._stable_stat_identity(opened)
            ):
                raise ProfileInputError(
                    "tracked repository checkout changed during verification"
                )
            return digest.hexdigest(), consumed
        finally:
            os.close(descriptor)

    def _require_worktree_matches_tree(
        self,
        expected: dict[str, tuple[str, str]],
    ) -> None:
        directories: set[Path] = {self.root}
        total = 0
        for relative in sorted(expected):
            mode, oid = expected[relative]
            path = self._tracked_path(relative, directories)
            try:
                before = path.lstat()
            except OSError as exc:
                raise ProfileInputError(
                    "tracked repository checkout differs from HEAD"
                ) from exc
            if mode == "120000":
                if not stat.S_ISLNK(before.st_mode):
                    raise ProfileInputError(
                        "tracked repository checkout differs from HEAD"
                    )
                try:
                    target = os.readlink(os.fsencode(path))
                    after = path.lstat()
                except OSError as exc:
                    raise ProfileInputError(
                        "tracked repository checkout differs from HEAD"
                    ) from exc
                if self._stable_stat_identity(after) != self._stable_stat_identity(before):
                    raise ProfileInputError(
                        "tracked repository checkout changed during verification"
                    )
                actual_oid = self._blob_digest_for_bytes(target)
                size = len(target)
            else:
                if stat.S_ISLNK(before.st_mode) or not stat.S_ISREG(before.st_mode):
                    raise ProfileInputError(
                        "tracked repository checkout differs from HEAD"
                    )
                executable = bool(stat.S_IMODE(before.st_mode) & 0o111)
                if executable != (mode == "100755"):
                    raise ProfileInputError(
                        "tracked repository checkout differs from HEAD"
                    )
                actual_oid, size = self._regular_blob_digest(path, before)
            total += size
            if total > _MAX_TRACKED_TOTAL_BYTES:
                raise ProfileInputError("tracked tree exceeds the verification limit")
            if actual_oid != oid:
                raise ProfileInputError(
                    "tracked repository checkout differs from HEAD"
                )

'''
validator = replace_once(
    validator,
    old_clean,
    new_clean,
    "content-addressed cleanliness boundary",
)
VALIDATOR.write_text(validator, encoding="utf-8")

# Add the exact local-stat-cache attack and source-level invariants.
tests = TESTS.read_text(encoding="utf-8")
stat_test = '''def test_local_stat_config_cannot_hide_same_size_restored_mtime_edit(
    tmp_path: Path,
) -> None:
    clone, clone_commit, clone_tree = _clone_exact_head(tmp_path)
    relative = "newsroom/increment5/profiles.py"
    source = clone / relative
    original = source.read_bytes()
    baseline = source.stat()
    for name, value in (
        ("core.trustctime", "false"),
        ("core.checkStat", "minimal"),
        ("core.ignoreStat", "true"),
        ("core.fileMode", "false"),
    ):
        configured = subprocess.run(
            ["git", "-C", str(clone), "config", name, value],
            stdout=subprocess.PIPE,
            stderr=subprocess.PIPE,
            check=False,
            timeout=20,
        )
        assert configured.returncode == 0, configured.stderr.decode("utf-8")
    refreshed = subprocess.run(
        ["git", "-C", str(clone), "update-index", "--refresh"],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        timeout=20,
    )
    assert refreshed.returncode == 0, refreshed.stderr.decode("utf-8")
    changed = bytearray(original)
    offset = next(index for index, value in enumerate(changed) if 65 <= value <= 90)
    changed[offset] = 90 if changed[offset] != 90 else 89
    source.write_bytes(changed)
    os.utime(source, ns=(baseline.st_atime_ns, baseline.st_mtime_ns))
    assert source.stat().st_size == baseline.st_size
    assert _git_text(clone, "status", "--porcelain=v1", "--untracked-files=no") == ""

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


'''
anchor = "def test_bounded_blob_reader_kills_an_overflowing_producer(tmp_path: Path) -> None:\n"
if tests.count(anchor) != 1:
    raise RuntimeError("stat attack insertion anchor differs")
tests = tests.replace(anchor, stat_test + anchor, 1)
tests = replace_once(
    tests,
    '''    assert '"core.fsmonitor=false"' in source
''',
    '''    assert '"core.fsmonitor=false"' in source
    assert '"core.trustctime=true"' in source
    assert '"core.checkStat=default"' in source
    assert '"core.ignoreStat=false"' in source
    assert '"core.fileMode=true"' in source
    assert '"ls-tree"' in source
    assert '"ls-files",\n            "-s"' in source
    assert "hashlib.sha1(usedforsecurity=False)" in source
    assert '"status",' not in source
''',
    "source-level stat-cache invariants",
)
TESTS.write_text(tests, encoding="utf-8")

prose = (
    "The clean-tree decision does not trust Git's index stat cache. The validator "
    "compares the stage-zero index inventory directly with the exact commit tree, "
    "then computes the Git blob identity and executable/symlink mode of every "
    "tracked worktree entry with the Python standard library. Local `trustctime`, "
    "`checkStat`, `ignoreStat`, `fileMode`, fsmonitor, restored mtimes, and same-size "
    "edits therefore cannot create a false `tracked_checkout_clean=true` claim."
)
for path in (DECISION, EVALUATION, OPERATIONS):
    text = path.read_text(encoding="utf-8")
    marker = "The inner receipt deliberately sets"
    position = text.find(marker)
    if position < 0:
        marker = "The inner executable is standard-library-only"
        position = text.find(marker)
    if position < 0:
        raise RuntimeError(f"{path.name}: cleanliness prose anchor missing")
    paragraph_end = text.find("\n\n", position)
    if paragraph_end < 0:
        raise RuntimeError(f"{path.name}: cleanliness paragraph boundary missing")
    text = text[:paragraph_end] + "\n\n" + prose + text[paragraph_end:]
    path.write_text(text, encoding="utf-8")

manifest = {
    "schema_version": "newsroom.increment5a.content-addressed-cleanliness.v1",
    "source_head": "17f619315819cfff99c0988664d04ec534cc5f93",
    "product_paths": [
        str(DECISION.relative_to(ROOT)),
        str(EVALUATION.relative_to(ROOT)),
        str(OPERATIONS.relative_to(ROOT)),
        str(TESTS.relative_to(ROOT)),
        str(VALIDATOR.relative_to(ROOT)),
    ],
    "cleanliness_boundary": {
        "git_status_used": False,
        "index_authority": "STAGE_ZERO_ENTRIES_EQUAL_EXACT_COMMIT_TREE",
        "worktree_authority": "DIRECT_STDLIB_GIT_BLOB_HASH_AND_MODE_COMPARISON",
        "stat_cache_trusted": False,
    },
    "contract_digest_unchanged": "sha256:51a3837ad9cdb70fe8aaa4242997b191c7e848bb1d391c6940cccc2bd45ba06c",
    "evaluation_plan_digest_unchanged": "sha256:c9d169c46a939573ffc6563704adfae973655f6394293ce591ec689f76a30959",
}
MANIFEST.write_text(
    json.dumps(manifest, sort_keys=True, separators=(",", ":")),
    encoding="utf-8",
)
print(json.dumps(manifest, indent=2, sort_keys=True))
