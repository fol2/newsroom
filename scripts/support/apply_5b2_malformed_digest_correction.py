from __future__ import annotations

from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]


def replace_once(relative_path: str, old: str, new: str) -> None:
    path = ROOT / relative_path
    text = path.read_text(encoding="utf-8")
    count = text.count(old)
    if count != 1:
        raise SystemExit(
            f"5B2 malformed-digest anchor differs for {relative_path}: count={count}"
        )
    path.write_text(text.replace(old, new, 1), encoding="utf-8")


def main() -> None:
    replace_once(
        "newsroom/increment5/fulltext_retriever.py",
        "from newsroom.authority.canonical import validate_sha256_digest\n",
        "from newsroom.authority.canonical import (\n"
        "    CanonicalizationError,\n"
        "    validate_sha256_digest,\n"
        ")\n",
    )

    replace_once(
        "newsroom/increment5/fulltext_retriever.py",
        """            validate_sha256_digest(
                document_digest,
                field="fulltext_result_document_digest",
            )
""",
        """            try:
                validate_sha256_digest(
                    document_digest,
                    field="fulltext_result_document_digest",
                )
            except CanonicalizationError:
                raise FullTextContractError(
                    "full-text result document digest is invalid"
                ) from None
""",
    )

    replace_once(
        "newsroom/tests/test_increment5b2_fulltext_retriever.py",
        """        (
            "document-digest",
            [result_row("p-en", 1.0, document_digest=digest("tampered"))],
        ),
        ("language", [result_row("p-en", 1.0, language="zh-HK")]),
""",
        """        (
            "document-digest",
            [result_row("p-en", 1.0, document_digest=digest("tampered"))],
        ),
        (
            "malformed-document-digest",
            [result_row("p-en", 1.0, document_digest="not-a-digest")],
        ),
        ("language", [result_row("p-en", 1.0, language="zh-HK")]),
""",
    )


if __name__ == "__main__":
    main()
