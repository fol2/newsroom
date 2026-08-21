#!/usr/bin/env python3
"""Cursor SDK no-tool calibration CLI. Provider I/O only happens on `--execute`."""

from __future__ import annotations

from newsroom.graphiti_adapter.sdk_no_tool_calibration import main

if __name__ == "__main__":
    raise SystemExit(main())
