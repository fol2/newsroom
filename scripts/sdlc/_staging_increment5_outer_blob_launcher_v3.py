#!/usr/bin/env python3
"""Disposable wrapper with document-specific outer-launcher placement."""
from __future__ import annotations

from pathlib import Path

source_path = Path(__file__).with_name("_staging_increment5_outer_blob_launcher.py")
program = source_path.read_text(encoding="utf-8")
start = program.index("for path in (DECISION, EVALUATION, OPERATIONS):\n")
end = program.index("manifest = {\n", start)
replacement = '''binding = (
    "\\n\\nThe inner receipt deliberately sets "
    "`executed_source_identity_attested=false` and "
    "`validation_code_identity_claim_effect=NONE`. The signed outer "
    "workflow must bind the exact validator blob SHA, complete launcher "
    "command, system-Python/runtime-image identity, canonical manifest "
    "bytes, inner-receipt digest, Epoch, and code tree. A direct worktree-"
    "path invocation or an unbound inner receipt is `NOT_EVALUATED`.\\n"
)

# The decision already carries the normative command block. Replace that exact
# block, then keep the surrounding authority explanation intact.
decision = DECISION.read_text(encoding="utf-8")
search = 0
selected = None
while True:
    candidate = decision.find("```", search)
    if candidate < 0:
        break
    close = decision.find("```", candidate + 3)
    if close < 0:
        break
    block = decision[candidate:close + 3]
    if "increment5_profile_validator.py" in block:
        selected = (candidate, close + 3)
        break
    search = close + 3
if selected is None:
    raise RuntimeError("decision exact validator block missing")
decision = decision[:selected[0]] + launcher_block + binding + decision[selected[1]:]
decision = decision.replace("Receipt v5", "Receipt v6")
decision = decision.replace(
    "profile-validation-receipt.v5",
    "profile-validation-receipt.v6",
)
decision = decision.replace(
    "EXACT_TRACKED_EXECUTABLE_STDLIB_ONLY",
    "OUTER_SIGNED_GIT_BLOB_LAUNCHER_REQUIRED",
)
DECISION.write_text(decision, encoding="utf-8")

# The evaluation plan has no launcher block. Add one bounded normative section
# immediately before the safety/failure protocol.
evaluation = EVALUATION.read_text(encoding="utf-8")
section_anchor = "\\n## Safety and failure experiments\\n"
if evaluation.count(section_anchor) != 1:
    raise RuntimeError("evaluation launcher section anchor differs")
section = (
    "\\n## Signed outer profile-validation launcher\\n\\n"
    "Before any validator byte executes, the signed 5E workflow resolves the "
    "validator blob from the frozen Epoch commit with fixed `/usr/bin/git`, "
    "streams those exact bytes to trusted no-site system Python, and supplies "
    "the canonical manifest on a separate regular-file descriptor. The exact "
    "admitted command is:\\n\\n"
    + launcher_block
    + binding
    + "\\n"
)
evaluation = evaluation.replace(section_anchor, section + section_anchor, 1)
evaluation = evaluation.replace("Receipt v5", "Receipt v6")
evaluation = evaluation.replace(
    "profile-validation-receipt.v5",
    "profile-validation-receipt.v6",
)
evaluation = evaluation.replace(
    "EXACT_TRACKED_EXECUTABLE_STDLIB_ONLY",
    "OUTER_SIGNED_GIT_BLOB_LAUNCHER_REQUIRED",
)
EVALUATION.write_text(evaluation, encoding="utf-8")

# The operating contract expresses this boundary as prose, not a code fence.
# Rebuild the complete section so the command and receipt semantics cannot
# diverge from one another.
operations = OPERATIONS.read_text(encoding="utf-8")
section_start = "## Profiles and validation\\n"
section_end = "## Epoch admission\\n"
first = operations.find(section_start)
second = operations.find(section_end, first)
if first < 0 or second < 0 or operations.find(section_start, first + 1) >= 0:
    raise RuntimeError("operations profile-validation section differs")
operations_section = (
    "## Profiles and validation\\n\\n"
    "`FIXTURE_REPLAY` is hermetic, zero-call, and never qualification evidence.\\n"
    "`PRODUCTION_SHAPED_QUALIFICATION` may use actual Neo4j and a signed,\\n"
    "rights-cleared, repository-safe dataset, but still has zero provider spend, no\\n"
    "model load, no protected content, no write authority, no public effect, and no\\n"
    "production activation.\\n\\n"
    "Every 5E profile is launched only by the signed outer workflow below. Before\\n"
    "any validator byte executes, fixed `/usr/bin/git` resolves the exact validator\\n"
    "blob from the frozen commit and streams those bytes to root-owned system\\n"
    "Python in isolated no-site stdin mode. The canonical manifest enters on a\\n"
    "separate inherited regular-file descriptor.\\n\\n"
    + launcher_block
    + binding
    + "\\nThe inner executable is standard-library-only and imports no environment package\\n"
    "or repository Python module. It binds the explicit Git directory, exact index,\\n"
    "and actual work tree; disables replacement objects and fsmonitor; rejects\\n"
    "assume-unchanged and skip-worktree flags; verifies the expected validator blob;\\n"
    "and reads only bounded digest-pinned contract/schema blobs from the exact\\n"
    "commit.\\n\\n"
    "Receipt v6 records `executed_source_identity_attested=false`,\\n"
    "`validation_code_identity_claim_effect=NONE`,\\n"
    "`outer_signed_workflow_binding_required=true`,\\n"
    "`validation_code_delivery=EXACT_COMMIT_GIT_BLOB_STDIN`,\\n"
    "`python_runtime_executable=/usr/bin/python3`,\\n"
    "`python_runtime_origin=ROOT_OWNED_SYSTEM_PYTHON_NO_SITE`,\\n"
    "`site_initialization_used=false`, `external_python_packages_used=false`,\\n"
    "`validation_code_origin=OUTER_SIGNED_GIT_BLOB_LAUNCHER_REQUIRED`,\\n"
    "`validation_data_origin=EXACT_REVIEWED_GIT_BLOBS`, and\\n"
    "`worktree_imports_used=false`. Runtime, commit, tree, validator blob, index\\n"
    "flags, and tracked cleanliness are checked again immediately before output.\\n"
    "The receipt retains authority effect `NONE`; it is necessary evidence only and\\n"
    "cannot authorize qualification or activation without the separately signed\\n"
    "outer evidence envelope.\\n\\n"
)
operations = operations[:first] + operations_section + operations[second:]
OPERATIONS.write_text(operations, encoding="utf-8")

'''
program = program[:start] + replacement + program[end:]
exec(compile(program, __file__, "exec"))
