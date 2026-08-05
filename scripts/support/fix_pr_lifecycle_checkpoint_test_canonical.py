from __future__ import annotations

from pathlib import Path


path = Path(__file__).resolve().parents[2] / "newsroom/tests/test_pr_lifecycle.py"
text = path.read_text(encoding="utf-8")
old = '''        def get_pull_request(self, number: int):
            assert number == 11
            return {
                "number": 11,
                "body": body(
                    lifecycle="support",
                    canonical="#10",
                    close_when="canonical-merged",
                    retention="delete-after-checkpoint",
                ),
                "draft": True,
                "head": {
                    "ref": "support/increment-5b2-correction",
                    "sha": "a" * 40,
                    "repo": {"full_name": "fol2/newsroom"},
                },
                "labels": [{"name": HOUSEKEEPING_LABEL}],
                "created_at": "2026-08-05T12:00:00Z",
            }

        def pull_request_is_merged(self, number: int) -> bool:
            return number == 10
'''
new = '''        def get_pull_request(self, number: int):
            if number == 11:
                return {
                    "number": 11,
                    "body": body(
                        lifecycle="support",
                        canonical="#10",
                        close_when="canonical-merged",
                        retention="delete-after-checkpoint",
                    ),
                    "draft": True,
                    "head": {
                        "ref": "support/increment-5b2-correction",
                        "sha": "a" * 40,
                        "repo": {"full_name": "fol2/newsroom"},
                    },
                    "labels": [{"name": HOUSEKEEPING_LABEL}],
                    "created_at": "2026-08-05T12:00:00Z",
                }
            assert number == 10
            return {
                "number": 10,
                "body": body(),
                "draft": False,
                "head": {
                    "ref": "agent/increment-5b2",
                    "sha": "c" * 40,
                    "repo": {"full_name": "fol2/newsroom"},
                },
                "labels": [],
                "created_at": "2026-08-01T12:00:00Z",
                "merged_at": "2026-08-02T12:00:00Z",
            }
'''
if text.count(old) != 1:
    raise SystemExit("checkpoint regression canonical fake anchor differs")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
