"""Finish 5C2 when needed, then run the exact-main Increment 5C closeout."""
from __future__ import annotations

import json
import os
from urllib.request import Request, urlopen

from scripts.support.publish_increment5c2_final_review_v5 import main as publish
from scripts.support.finalize_increment5c2 import main as finalize
from scripts.support.close_increment5c import main as close_parent


def pr_merged() -> bool:
    request = Request(
        "https://api.github.com/repos/fol2/newsroom/pulls/347",
        headers={
            "Accept": "application/vnd.github+json",
            "Authorization": f"Bearer {os.environ['GH_TOKEN']}",
            "X-GitHub-Api-Version": "2022-11-28",
            "User-Agent": "newsroom-increment5c-finish",
        },
    )
    with urlopen(request, timeout=60) as response:
        return bool(json.loads(response.read())["merged"])


def main() -> None:
    publish()
    if not pr_merged():
        finalize()
    close_parent()


if __name__ == "__main__":
    main()
