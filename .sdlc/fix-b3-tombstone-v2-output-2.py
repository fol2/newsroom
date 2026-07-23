from __future__ import annotations

from pathlib import Path


path = Path("newsroom/tests/projection_b3_tombstone_helpers.py")
value = path.read_text(encoding="utf-8")
old_import = "from dataclasses import dataclass\nfrom pathlib import Path\n"
new_import = "from dataclasses import dataclass\nfrom pathlib import Path\nimport sqlite3\n"
if value.count(old_import) != 1:
    raise SystemExit("tombstone fixture sqlite import replacement mismatch")
value = value.replace(old_import, new_import)
old = '''        events = system.events.after(0, limit=1000, proof=proof())
        source_event = next(
            item for item in events if item.event_id == str(committed.event_id)
        )
        tombstone_event = next(
            item for item in events if item.event_id == str(tombstone.event_id)
        )
'''
new = '''        connection = sqlite3.connect(database)
        connection.row_factory = sqlite3.Row
        try:
            source_row = connection.execute(
                "SELECT * FROM ledger_events WHERE event_id=?",
                (str(committed.event_id),),
            ).fetchone()
            tombstone_row = connection.execute(
                "SELECT * FROM ledger_events WHERE event_id=?",
                (str(tombstone.event_id),),
            ).fetchone()
        finally:
            connection.close()
        if source_row is None or tombstone_row is None:
            raise AssertionError("retained tombstone fixture event is absent")
        source_event = LedgerEventRecord(**dict(source_row))
        tombstone_event = LedgerEventRecord(**dict(tombstone_row))
'''
if value.count(old) != 1:
    raise SystemExit("tombstone fixture event replacement mismatch")
path.write_text(value.replace(old, new), encoding="utf-8")
