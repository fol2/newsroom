from __future__ import annotations

from . import _main_qualification_v2 as _core
from .admission_anchors import MAIN_QUALIFICATION_RECORD_DIGEST


for _name in dir(_core):
    if not _name.startswith("__"):
        globals()[_name] = getattr(_core, _name)

# The parser and schema remain immutable in _main_qualification_v2.  Only this
# canonical data anchor changes when the later exact-main record is admitted.
_core.MAIN_QUALIFICATION_RECORD_DIGEST = MAIN_QUALIFICATION_RECORD_DIGEST

del _name
