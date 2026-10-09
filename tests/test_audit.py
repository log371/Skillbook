import sqlite3
from concurrent.futures import ThreadPoolExecutor
from contextlib import closing

import pytest

from skillbook.audit import Audit


def test_concurrent_append_and_tampering(tmp_path):
    audit = Audit(tmp_path / "audit.sqlite")
    with ThreadPoolExecutor(max_workers=4) as pool:
        list(pool.map(lambda n: audit.append("decision", str(n), allowed=False), range(20)))
    checkpoint = audit.verify()
    assert checkpoint["events"] == 20
    assert audit.verify(checkpoint["head"])["valid"]
    with closing(sqlite3.connect(audit.path)) as db, db:
        db.execute("UPDATE events SET payload='{}' WHERE seq=5")
    with pytest.raises(ValueError, match="modified"):
        audit.verify()


def test_truncation_requires_external_checkpoint(tmp_path):
    audit = Audit(tmp_path / "audit.sqlite")
    audit.append("one", "1")
    head = audit.append("two", "2")
    with closing(sqlite3.connect(audit.path)) as db, db:
        db.execute("DELETE FROM events WHERE seq=2")
    assert audit.verify()["events"] == 1
    with pytest.raises(ValueError, match="checkpoint"):
        audit.verify(head)


def test_deleted_middle_event(tmp_path):
    audit = Audit(tmp_path / "audit.sqlite")
    for i in range(3):
        audit.append("event", str(i))
    with closing(sqlite3.connect(audit.path)) as db, db:
        db.execute("DELETE FROM events WHERE seq=2")
    with pytest.raises(ValueError, match="sequence"):
        audit.verify()
