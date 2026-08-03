#!/usr/bin/env python3
"""Materialize the final isolated-bootstrap Increment 5A boundary.

Disposable staging helper. It must never be merged into PR #255 or main.
"""

from __future__ import annotations

import json
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
SOURCE_HEAD = "a6a6de77ffc2f37117c270d7f96d69b4ca1e6708"
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
MANIFEST = ROOT / "increment5a-isolated-bootstrap-manifest.json"


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
    old = """from __future__ import annotations

from contextlib import contextmanager
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
"""
    new = """from __future__ import annotations

import sys

# This executable is an evidence boundary, not an importable convenience. The
# isolated-interpreter requirement is checked before any dependency import, so
# PYTHONPATH, user site packages, and caller-selected import roots cannot supply
# jsonschema or another transitive validator dependency.
if not sys.flags.isolated:
    sys.stderr.write(
        "increment5 profile validation failed: isolated Python mode is required\\n"
    )
    raise SystemExit(2)

from contextlib import contextmanager
import hashlib
import importlib
import json
import os
from pathlib import Path, PurePosixPath
import re
import selectors
import stat
import subprocess
import tarfile
import tempfile
import time
from typing import Any, Iterator
"""
    text = replace_once(text, old, new, label="isolated bootstrap imports")
    VALIDATOR.write_text(text, encoding="utf-8")


def update_tests() -> None:
    text = TESTS.read_text(encoding="utf-8")
    text = replace_once(
        text,
        "import importlib.util\n",
        "",
        label="remove ordinary-process validator import",
    )

    isolated_test = r'''


def test_nonisolated_execution_rejects_before_pythonpath_dependency_import(
    tmp_path: Path,
) -> None:
    fake_root = tmp_path / "pythonpath"
    fake_package = fake_root / "jsonschema"
    fake_package.mkdir(parents=True)
    marker = tmp_path / "fake-jsonschema-imported"
    fake_package.joinpath("__init__.py").write_text(
        "from pathlib import Path\n"
        f"Path({str(marker)!r}).write_text('imported', encoding='utf-8')\n"
        "class Draft202012Validator:\n"
        "    def __init__(self, schema): pass\n"
        "    def iter_errors(self, instance): return iter(())\n",
        encoding="utf-8",
    )
    invalid = _fixture_manifest()
    invalid["qualification_eligible"] = True
    environment = _validator_environment()
    environment["PYTHONPATH"] = str(fake_root)

    completed = subprocess.run(
        [
            sys.executable,
            str(_VALIDATOR_SCRIPT),
            "--expected-code-commit-sha",
            _CODE_COMMIT_SHA,
            "--expected-code-tree-sha",
            _CODE_TREE_SHA,
        ],
        input=canonical_json_bytes(invalid),
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env=environment,
        timeout=30,
    )

    assert completed.returncode == 2
    assert completed.stderr == (
        b"increment5 profile validation failed: "
        b"isolated Python mode is required\n"
    )
    assert completed.stdout == b""
    assert not marker.exists()
'''
    anchor = "\ndef test_validator_requires_matching_commit_and_tree_arguments() -> None:\n"
    text = replace_once(
        text,
        anchor,
        isolated_test + anchor,
        label="nonisolated dependency attack regression",
    )

    overflow_test = r'''def test_archive_limit_kills_the_producer_before_overflow_reaches_disk(
    tmp_path: Path,
) -> None:
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
    probe = """
import runpy
import sys
from pathlib import Path

namespace = runpy.run_path(
    sys.argv[1],
    run_name="increment5_profile_validator_streaming_probe",
)
error_type = namespace["ProfileInputError"]
try:
    namespace["_stream_bounded_process_to_file"](
        [sys.executable, sys.argv[2]],
        Path(sys.argv[3]),
        env={"LC_ALL": "C", "PYTHONUTF8": "1"},
        timeout_seconds=20,
        max_stdout_bytes=1024,
        max_stderr_bytes=1024,
        failure_message="cannot materialize the exact Git code tree",
    )
except error_type as exc:
    if str(exc) != "Git archive exceeds the generation limit":
        raise
else:
    raise SystemExit("overflowing producer unexpectedly succeeded")
if Path(sys.argv[3]).exists():
    raise SystemExit("partial archive remains after overflow")
"""

    completed = subprocess.run(
        [
            sys.executable,
            "-I",
            "-c",
            probe,
            str(_VALIDATOR_SCRIPT),
            str(emitter),
            str(archive),
        ],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        check=False,
        cwd=_REPOSITORY_ROOT,
        env={"LC_ALL": "C", "PYTHONUTF8": "1"},
        timeout=30,
    )

    assert completed.returncode == 0, completed.stderr.decode("utf-8")
    assert completed.stdout == b""
    assert not archive.exists()
    assert not marker.exists()


'''
    text = replace_section(
        text,
        "def _load_validator_module() -> Any:\n",
        "def test_validator_materializes_exact_tree_before_repository_import() -> None:\n",
        overflow_test,
        label="isolated overflow probe",
    )

    text = replace_once(
        text,
        """    assert '"--untracked-files=no"' in source
    assert '"--untracked-files=all"' not in source
""",
        """    bootstrap = source.index("if not sys.flags.isolated:")
    assert source.index("import sys") < bootstrap
    assert bootstrap < source.index("from contextlib import contextmanager")
    assert "isolated Python mode is required" in source
    assert '"--untracked-files=no"' in source
    assert '"--untracked-files=all"' not in source
""",
        label="bootstrap order assertions",
    )
    TESTS.write_text(text, encoding="utf-8")


def update_docs() -> None:
    decision = DECISION.read_text(encoding="utf-8")
    decision = replace_once(
        decision,
        """Before importing any Newsroom module, the validator resolves the actual Git
commit and tree, requires them to equal the caller-supplied identities, and
rejects staged or tracked differences. Git is never selected from caller
""",
        """The validator is executable only under Python isolated mode. Immediately after
importing the built-in `sys` module—and before importing any third-party or
repository dependency—it requires `sys.flags.isolated`; direct or otherwise
non-`-I` execution exits with status 2. Caller `PYTHONPATH`, user site packages,
and caller-selected import roots therefore cannot supply `jsonschema` or another
transitive validation dependency.

Before importing any Newsroom module, the validator resolves the actual Git
commit and tree, requires them to equal the caller-supplied identities, and
rejects staged or tracked differences. Git is never selected from caller
""",
        label="decision isolated bootstrap boundary",
    )
    DECISION.write_text(decision, encoding="utf-8")

    evaluation = EVALUATION.read_text(encoding="utf-8")
    evaluation = replace_once(
        evaluation,
        """`NOT_EVALUATED`. Every profile-validation receipt is v3, binds the actual Git
commit and tree, and records that staged/tracked checkout state was clean and
""",
        """`NOT_EVALUATED`. Every profile-validation receipt is v3 and is produced only by
an interpreter already running in isolated mode; failure to establish isolated
mode before dependency imports is `NOT_EVALUATED`. The receipt binds the actual
Git commit and tree and records that staged/tracked checkout state was clean and
""",
        label="evaluation isolated bootstrap boundary",
    )
    EVALUATION.write_text(evaluation, encoding="utf-8")

    operations = OPERATIONS.read_text(encoding="utf-8")
    operations = replace_once(
        operations,
        """The validator verifies the supplied Git commit and tree and rejects staged or
tracked differences before importing any Newsroom module. It ignores caller
""",
        """The validator first requires Python isolated mode, immediately after the
built-in `sys` import and before any dependency import. Non-`-I` execution exits
with status 2, so caller `PYTHONPATH`, user site packages, and caller-selected
import roots cannot supply validator dependencies.

It then verifies the supplied Git commit and tree and rejects staged or tracked
differences before importing any Newsroom module. It ignores caller
""",
        label="operations isolated bootstrap boundary",
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
        "bootstrap_boundary": {
            "allowed_mode": "PYTHON_ISOLATED_FLAG_TRUE",
            "dependency_imports_before_check": [],
            "nonisolated_exit_status": 2,
            "pythonpath_authority": False,
        },
        "changed_paths": sorted(changed_paths),
        "contract_digest_unchanged": CONTRACT_DIGEST,
        "evaluation_plan_digest_unchanged": PLAN_DIGEST,
        "schema_version": "newsroom.increment5a.isolated-bootstrap.v1",
        "source_head": SOURCE_HEAD,
        "streaming_and_git_boundaries_unchanged": True,
    }
    MANIFEST.write_text(
        json.dumps(manifest, sort_keys=True, separators=(",", ":")) + "\n",
        encoding="utf-8",
    )
    print(json.dumps(manifest, indent=2, sort_keys=True))


if __name__ == "__main__":
    main()
