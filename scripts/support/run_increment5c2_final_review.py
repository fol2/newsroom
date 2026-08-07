from __future__ import annotations

from scripts.support import publish_increment5c2_final_review as builder
from scripts.support import publish_increment5c2_final_review_v2 as chunked


def main() -> None:
    builder.EXPECTED_TREE = "4adf04d289a1bbb9f89709445302a938196ee065"
    chunked.main()


if __name__ == "__main__":
    main()
