#!/usr/bin/env python3
"""Disposable wrapper correcting document-specific launcher placement."""
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

for path in (DECISION, OPERATIONS):
    text = path.read_text(encoding="utf-8")
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
    text = text.replace("Receipt v5", "Receipt v6")
    text = text.replace(
        "profile-validation-receipt.v5",
        "profile-validation-receipt.v6",
    )
    text = text.replace(
        "EXACT_TRACKED_EXECUTABLE_STDLIB_ONLY",
        "OUTER_SIGNED_GIT_BLOB_LAUNCHER_REQUIRED",
    )
    position = text.find("\\nThe receipt")
    if position < 0:
        position = text.find("\\nReceipt v6")
    if position < 0:
        raise RuntimeError(f"{path.name}: receipt prose anchor missing")
    text = text[:position] + binding + text[position:]
    path.write_text(text, encoding="utf-8")

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

'''
program = program[:start] + replacement + program[end:]
exec(compile(program, __file__, "exec"))
