from __future__ import annotations

from pathlib import Path
import subprocess
import sys


ROOT = Path(__file__).resolve().parents[1]
GENERATOR = ROOT / "scripts" / "temp_increment5a_review_hardening.py"


def replace_exact(text: str, old: str, new: str, *, label: str) -> str:
    count = text.count(old)
    if count != 1:
        raise RuntimeError(f"{label}: expected one match, found {count}")
    return text.replace(old, new, 1)


def replace_section(
    text: str,
    *,
    start: str,
    end: str,
    replacement: str,
    label: str,
) -> str:
    start_index = text.find(start)
    if start_index < 0:
        raise RuntimeError(f"{label}: start marker missing")
    end_index = text.find(end, start_index)
    if end_index < 0:
        raise RuntimeError(f"{label}: end marker missing")
    if text.find(start, start_index + 1) >= 0:
        raise RuntimeError(f"{label}: start marker is ambiguous")
    return text[:start_index] + replacement + text[end_index:]


def main() -> None:
    text = GENERATOR.read_text(encoding="utf-8")

    text = replace_exact(
        text,
        """def replace_once(text: str, old: str, new: str, *, label: str) -> str:\n    count = text.count(old)\n    if count != 1:\n        raise RuntimeError(f\"{label}: expected one match, found {count}\")\n    return text.replace(old, new, 1)\n""",
        """def _indent_block(value: str, width: int) -> str:\n    prefix = \" \" * width\n    return \"\\n\".join(\n        prefix + line if line else line\n        for line in value.splitlines()\n    )\n\n\ndef replace_once(text: str, old: str, new: str, *, label: str) -> str:\n    candidates = [(old, new)] + [\n        (_indent_block(old, width), _indent_block(new, width))\n        for width in (4, 8, 12, 16, 20)\n    ]\n    observed: list[int] = []\n    for old_value, new_value in candidates:\n        count = text.count(old_value)\n        observed.append(count)\n        if count == 1:\n            return text.replace(old_value, new_value, 1)\n        if count > 1:\n            raise RuntimeError(f\"{label}: ambiguous match count {count}\")\n    raise RuntimeError(f\"{label}: expected one match, observed {observed}\")\n""",
        label="indent-aware replacement helper",
    )

    text = replace_section(
        text,
        start=(
            "postmerge_doc = replace_once(\n"
            "    postmerge_doc,\n"
            "    \"The post-merge record is a separate admission artifact. \""
        ),
        end="write_text(postmerge_doc_path, postmerge_doc)",
        replacement="""postmerge_doc = replace_once(\n    postmerge_doc,\n    (\n        \"That later record can be created only after PR #255 is merged and the exact\\n\"\n        \"merged `main` commit has passed all six permanent workflows. It binds:\"\n    ),\n    (\n        \"That later record can be created only after PR #255 is merged and the exact\\n\"\n        \"merged `main` commit has passed all six permanent workflows. Before it can\\n\"\n        \"return authority, its source-pinned loader authenticates every claimed run\\n\"\n        \"attempt and the qualified commit tree against GitHub REST. It binds:\"\n    ),\n    label=\"post-merge live authentication documentation\",\n)\n""",
        label="post-merge authentication documentation",
    )

    text = replace_section(
        text,
        start=(
            "trace_doc = replace_once(\n"
            "    trace_doc,\n"
            "    \"`DEVAL-073`, `DOPS-064` and `DOPS-072` are deliberately assigned to 5E,\""
        ),
        end="write_text(trace_doc_path, trace_doc)",
        replacement="""trace_doc = replace_once(\n    trace_doc,\n    \"| Delivered in 5A / #250 | 24 |\",\n    \"| Delivered in 5A / #250 | 23 |\",\n    label=\"DOPS-074 delivered count\",\n)\ntrace_doc = replace_once(\n    trace_doc,\n    \"`DOPS-070`, `DOPS-074`, `DOPS-076`\",\n    \"`DOPS-070`, `DOPS-076`\",\n    label=\"remove DOPS-074 from 5A table\",\n)\ntrace_doc = replace_once(\n    trace_doc,\n    \"| Deferred to 5E / #254 | 41 |\",\n    \"| Deferred to 5E / #254 | 42 |\",\n    label=\"DOPS-074 deferred count\",\n)\ntrace_doc = replace_once(\n    trace_doc,\n    \"`DOPS-064`, `DOPS-072`, `DOPS-075`\",\n    \"`DOPS-064`, `DOPS-072`, `DOPS-074`, `DOPS-075`\",\n    label=\"add DOPS-074 to 5E table\",\n)\ntrace_doc = replace_once(\n    trace_doc,\n    \"`DOPS-072` remains in 5E, where rollback is actually exercised.\",\n    (\n        \"`DOPS-072` remains in 5E, where rollback is actually exercised. \"\n        \"`DOPS-074` is deferred to 5E/#254, where material rights, terms, \"\n        \"pricing, access and credential changes receive accountable review \"\n        \"and blocking evidence.\"\n    ),\n    label=\"DOPS-074 documentation deferral\",\n)\n""",
        label="DOPS-074 traceability documentation",
    )

    text = replace_section(
        text,
        start=(
            "owner_doc = replace_once(\n"
            "    owner_doc,\n"
            "    \"- the fixture-replay profile schema digest;\\n\""
        ),
        end="write_text(owner_doc_path, owner_doc)",
        replacement="""owner_doc = replace_once(\n    owner_doc,\n    \"**Fixture-replay schema:**\",\n    \"**Historical proposal fixture-replay schema:**\",\n    label=\"historical fixture owner binding documentation\",\n)\n""",
        label="owner fixture documentation",
    )

    text = replace_exact(
        text,
        """# The approval test must pin the newly generated exact statement digest.\napproval_test = approval_test_path.read_text(encoding=\"utf-8\")\n""",
        """owner_value = owner_doc_path.read_text(encoding=\"utf-8\")\nowner_marker = (\n    f\"**Historical proposal fixture-replay schema:** \"\n    f\"`{proposal_fixture_digest}`\"\n)\nowner_value = replace_once(\n    owner_value,\n    owner_marker,\n    owner_marker + f\"\\n**Effective fixture-replay schema:** `{new_fixture_digest}`\",\n    label=\"effective fixture owner metadata\",\n)\nwrite_text(owner_doc_path, owner_value)\n\n# The approval test must pin the newly generated exact statement digest.\napproval_test = approval_test_path.read_text(encoding=\"utf-8\")\n""",
        label="owner fixture metadata insertion",
    )

    marker = """# ---------------------------------------------------------------------------\n# Source-pinned loader must authenticate claims against live GitHub\n# ---------------------------------------------------------------------------\n"""
    proposal_patch = """# ---------------------------------------------------------------------------\n# Immutable proposal continues to bind the historical fixture schema\n# ---------------------------------------------------------------------------\n\ndecision_path = ROOT / \"newsroom\" / \"increment5\" / \"decision.py\"\ndecision = decision_path.read_text(encoding=\"utf-8\")\ndecision = replace_once(\n    decision,\n    \"    FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,\\n\"\n    \"    PROPOSAL_PRODUCTION_PROFILE_SCHEMA_DIGEST,\\n\",\n    \"    PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST,\\n\"\n    \"    PROPOSAL_PRODUCTION_PROFILE_SCHEMA_DIGEST,\\n\",\n    label=\"proposal fixture schema import\",\n)\ndecision = replace_once(\n    decision,\n    'schemas.get(\"fixture_replay\") != FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST',\n    (\n        'schemas.get(\"fixture_replay\") '\n        '!= PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST'\n    ),\n    label=\"proposal fixture schema verification\",\n)\ndecision = replace_once(\n    decision,\n    \"        fixture_replay_profile_schema_digest=(\\n\"\n    \"            FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST\\n\"\n    \"        ),\\n\",\n    \"        fixture_replay_profile_schema_digest=(\\n\"\n    \"            PROPOSAL_FIXTURE_REPLAY_PROFILE_SCHEMA_DIGEST\\n\"\n    \"        ),\\n\",\n    label=\"proposal fixture bundle binding\",\n)\nwrite_text(decision_path, decision)\n\n\n"""
    text = replace_exact(
        text,
        marker,
        proposal_patch + marker,
        label="proposal fixture boundary insertion",
    )

    GENERATOR.write_text(text, encoding="utf-8", newline="\n")
    subprocess.run([sys.executable, str(GENERATOR)], cwd=ROOT, check=True)


if __name__ == "__main__":
    main()
