from __future__ import annotations

from pathlib import Path


TARGET = Path(__file__).with_name("apply_pr_lifecycle_retain_branches.py")


OLD = '''    replace_once(
        path,
        """    if lifecycle.kind is LifecycleKind.CANONICAL:
""",
        """    if lifecycle.branch_retention is not BranchRetention.KEEP:
        raise PrLifecycleError(
            "automatic branch deletion is unsupported; "
            "Branch-Retention must be keep"
        )
    if lifecycle.kind is LifecycleKind.CANONICAL:
""",
    )
'''

NEW = '''    text = read(path)
    marker = "def _validate_lifecycle_shape(lifecycle: PrLifecycle) -> None:"
    start = text.find(marker)
    if start < 0:
        raise SystemExit("missing lifecycle-shape function")
    prefix = text[:start]
    shape = text[start:]
    old_shape = "    if lifecycle.kind is LifecycleKind.CANONICAL:\\n"
    if shape.count(old_shape) != 1:
        raise SystemExit(
            "lifecycle-shape canonical anchor differs: "
            f"count={shape.count(old_shape)}"
        )
    new_shape = """    if lifecycle.branch_retention is not BranchRetention.KEEP:
        raise PrLifecycleError(
            "automatic branch deletion is unsupported; "
            "Branch-Retention must be keep"
        )
    if lifecycle.kind is LifecycleKind.CANONICAL:
"""
    write(path, prefix + shape.replace(old_shape, new_shape, 1))
'''


def main() -> None:
    source = TARGET.read_text(encoding="utf-8")
    if source.count(OLD) != 1:
        raise SystemExit(
            f"retain-branches runner anchor differs: count={source.count(OLD)}"
        )
    patched = source.replace(OLD, NEW, 1)
    namespace = {
        "__name__": "__main__",
        "__file__": str(TARGET),
    }
    exec(compile(patched, str(TARGET), "exec"), namespace)


if __name__ == "__main__":
    main()
