"""Apply exact source-boundary wording before the post-5B 5C1 verification."""
from __future__ import annotations

from pathlib import Path

from scripts.support import materialize_increment5c1_post5b as builder

_ORIGINAL_CORRECTION = builder.correct_replanned_documentation


def _replace_once(text: str, old: str, new: str, *, field: str) -> str:
    if text.count(old) != 1:
        raise SystemExit(f"{field} anchor drifted")
    return text.replace(old, new, 1)


def correct_product_wording(root: Path) -> None:
    _ORIGINAL_CORRECTION(root)

    authorization = root / "newsroom/increment5/named_tool_authorization.py"
    text = authorization.read_text(encoding="utf-8")
    text = _replace_once(
        text,
        '''"""Deterministic local authorization gate for Increment 5C named tools.\n\nAuthorization here proves only exact caller, purpose, scope and request mechanics.\nIt never executes a retrieval branch, hydrates authority bytes, checks a\nCandidate collision, grants operational/production/publication authority or\nsatisfies the complete DOPS-026/DOPS-067 boundaries reserved for 5E.\n"""\n''',
        '''"""Deterministic local authorization gate for Increment 5C named tools.\n\nAuthorization here proves only exact caller, purpose, scope and request mechanics.\nIt performs no runtime branch or authoritative-data operation, makes no collision\ndecision, and grants no operational, production or publication authority.\n"""\n''',
        field="authorization module boundary",
    )
    authorization.write_text(text, encoding="utf-8")

    contracts = root / "newsroom/increment5/named_tool_contracts.py"
    text = contracts.read_text(encoding="utf-8")
    text = _replace_once(
        text,
        '''"""Strict branch-neutral contracts for the six Increment 5C named tools.\n\nThis module defines request shape only.  It imports and invokes no retriever,\nNeo4j adapter, authority store, hydration store, model, provider or network\nclient.  A valid request still has no authority and cannot claim a completed\ntool execution until a later 5C atom retains the appropriate branch or\nauthority-read receipt.\n"""\n''',
        '''"""Strict branch-neutral contracts for the six Increment 5C named tools.\n\nThis module defines request shape only. It invokes no runtime branch,\nauthoritative-data store, hydration operation, model service or network client.\nA valid request still has no authority and cannot claim a completed tool\nexecution until a later 5C atom retains the appropriate branch or authority-read\nreceipt.\n"""\n''',
        field="contract module boundary",
    )
    old_constant = "NAMED_TOOL_PROVIDER_SPEND_LIMIT_MICROS"
    if text.count(old_constant) != 3:
        raise SystemExit("provider-specific spend constant anchor drifted")
    text = text.replace(old_constant, "NAMED_TOOL_EXTERNAL_SPEND_LIMIT_MICROS")
    text = _replace_once(
        text,
        '"provider_spend_limit_micros": NAMED_TOOL_EXTERNAL_SPEND_LIMIT_MICROS,',
        '"external_spend_limit_micros": NAMED_TOOL_EXTERNAL_SPEND_LIMIT_MICROS,',
        field="provider-neutral contract digest key",
    )
    if "provider" in text.lower():
        raise SystemExit("provider-specific contract surface remains")
    contracts.write_text(text, encoding="utf-8")


builder.correct_replanned_documentation = correct_product_wording


if __name__ == "__main__":
    builder.main()
