#!/usr/bin/env python3
"""Disposable repair wrapper for the support-only generator."""
from base64 import b85decode
from pathlib import Path
from zlib import decompress

_SOURCE = Path(__file__).with_name(
    "_staging_increment5_no_site_composer.py"
).read_text(encoding="utf-8")
_PREFIX = '_PAYLOAD = """'
_SUFFIX = '"""\nexec(compile(decompress(b85decode(_PAYLOAD)), __file__, "exec"))'
if _SOURCE.count(_PREFIX) != 1 or _SOURCE.count(_SUFFIX) != 1:
    raise RuntimeError("support generator envelope differs")
_PAYLOAD = _SOURCE.split(_PREFIX, 1)[1].split(_SUFFIX, 1)[0]
_PROGRAM = decompress(b85decode(_PAYLOAD)).decode("utf-8")
_OLD = '''        ''' + "'''" + '''The exact delivery split is `9 / 0 / 4 / 11 / 123 / 7 / 1` for 5A, 5B, 5C,
5D, 5E, prior Increment 4, and outside activation respectively.
''' + "'''" + ''',
        ''' + "'''" + '''The exact delivery split is `9 / 0 / 2 / 13 / 123 / 7 / 1` for 5A, 5B, 5C,
5D, 5E, prior Increment 4, and outside activation respectively.
''' + "'''" + ''','''
_NEW = '''        ''' + "'''" + '''`9 / 0 / 4 / 11 / 123 / 7 / 1`''' + "'''" + ''',
        ''' + "'''" + '''`9 / 0 / 2 / 13 / 123 / 7 / 1`''' + "'''" + ''','''
if _PROGRAM.count(_OLD) != 1:
    raise RuntimeError("operations count patch source differs")
_PROGRAM = _PROGRAM.replace(_OLD, _NEW, 1)
exec(compile(_PROGRAM, __file__, "exec"))
