#!/usr/bin/env python3
"""Disposable wrapper correcting POSIX symlink-mode interpretation."""
from __future__ import annotations

from pathlib import Path
import runpy

ROOT = Path(__file__).resolve().parents[2]
runpy.run_path(
    str(Path(__file__).with_name("_staging_increment5_no_site_composer_v3.py")),
    run_name="__main__",
)

path = ROOT / "scripts/sdlc/increment5_profile_validator.py"
text = path.read_text(encoding="utf-8")
old = '''        if stat.S_ISLNK(info.st_mode):
            if not symlink_allowed:
                raise ProfileInputError(
                    "trusted system Python path cannot be a symlink"
                )
        else:
            expected_type = stat.S_ISDIR if directory else stat.S_ISREG
            if not expected_type(info.st_mode):
                raise ProfileInputError(
                    "trusted system Python path has the wrong type"
                )
        if info.st_uid != 0 or info.st_gid != 0:
            raise ProfileInputError(
                "trusted system Python path is not root owned"
            )
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ProfileInputError(
                "trusted system Python path is writable"
            )
        return info
'''
new = '''        if stat.S_ISLNK(info.st_mode):
            if not symlink_allowed:
                raise ProfileInputError(
                    "trusted system Python path cannot be a symlink"
                )
            if info.st_uid != 0 or info.st_gid != 0:
                raise ProfileInputError(
                    "trusted system Python path is not root owned"
                )
            # POSIX symlink permission bits are not access controls and are
            # commonly reported as 0777. The resolved target is checked below.
            return info
        expected_type = stat.S_ISDIR if directory else stat.S_ISREG
        if not expected_type(info.st_mode):
            raise ProfileInputError(
                "trusted system Python path has the wrong type"
            )
        if info.st_uid != 0 or info.st_gid != 0:
            raise ProfileInputError(
                "trusted system Python path is not root owned"
            )
        if info.st_mode & (stat.S_IWGRP | stat.S_IWOTH):
            raise ProfileInputError(
                "trusted system Python path is writable"
            )
        return info
'''
if text.count(old) != 1:
    raise RuntimeError("trusted Python symlink check source differs")
path.write_text(text.replace(old, new, 1), encoding="utf-8")
