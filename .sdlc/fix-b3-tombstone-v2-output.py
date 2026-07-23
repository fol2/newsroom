from __future__ import annotations

from pathlib import Path


path = Path("newsroom/tests/projection_b3_tombstone_helpers.py")
value = path.read_text(encoding="utf-8")
old = '''        trust_scope=TrustScope.OBSERVED,
        security_scope="authority.internal",
        retention_scope="source.short",
        required_scope="authority.observed.write",
        required_object_class="source_capture",
        required_allowed_use="project.discovery",
'''
new = '''        trust_scope=TrustScope.OBSERVED,
        security_scope="authority.protected",
        retention_scope="source.short",
        required_scope="authority.observed.write",
        required_object_class="source_capture",
        required_allowed_use="project.discovery",
'''
if value.count(old) != 1:
    raise SystemExit("tombstone fixture security-scope replacement mismatch")
path.write_text(value.replace(old, new), encoding="utf-8")
