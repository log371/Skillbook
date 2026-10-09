import json
import sqlite3
from contextlib import closing
from datetime import UTC, datetime
from pathlib import Path

from skillbook.domain import canonical, digest

ZERO = "0" * 64


class Audit:
    """Local hash chain. Export its head externally to detect complete rewrites/truncation."""

    def __init__(self, path: Path):
        path.parent.mkdir(parents=True, exist_ok=True)
        self.path = path
        with closing(sqlite3.connect(path)) as db, db:
            db.execute(
                "CREATE TABLE IF NOT EXISTS events "
                "(seq INTEGER PRIMARY KEY, payload TEXT NOT NULL, "
                "previous TEXT NOT NULL, hash TEXT NOT NULL)"
            )
        path.chmod(0o600)

    def append(self, event: str, request_id: str, **fields: str | int | bool) -> str:
        # Callers pass only enumerated metadata, never prompts, keys or model arguments.
        payload = canonical(
            {
                "time": datetime.now(UTC).isoformat(),
                "event": event,
                "request_id": request_id,
                **fields,
            }
        ).decode()
        with closing(sqlite3.connect(self.path, timeout=10)) as db, db:
            db.execute("BEGIN IMMEDIATE")
            row = db.execute("SELECT seq, hash FROM events ORDER BY seq DESC LIMIT 1").fetchone()
            seq, previous = (row[0] + 1, row[1]) if row else (1, ZERO)
            hashed = digest(canonical([seq, previous, payload]))
            db.execute("INSERT INTO events VALUES (?, ?, ?, ?)", (seq, payload, previous, hashed))
        return hashed

    def verify(self, expected_head: str | None = None) -> dict:
        previous, count = ZERO, 0
        with closing(sqlite3.connect(self.path)) as db:
            for seq, payload, parent, hashed in db.execute("SELECT * FROM events ORDER BY seq"):
                count += 1
                if seq != count or parent != previous:
                    raise ValueError("Audit sequence broken")
                if digest(canonical([seq, parent, payload])) != hashed:
                    raise ValueError("Audit event modified")
                json.loads(payload)
                previous = hashed
        if expected_head is not None and expected_head != previous:
            raise ValueError("Audit head differs from trusted checkpoint")
        return {"events": count, "head": previous, "valid": True}
