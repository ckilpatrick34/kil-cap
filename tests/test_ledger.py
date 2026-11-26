import sqlite3

import pytest

from kil_capital.core.ledger import Ledger


def test_hash_chain_and_append_only(tmp_path):
    L = Ledger(tmp_path / "x.sqlite")
    for i in range(5):
        L.audit("a", "carson", {"i": i}, "ok")
    assert L.verify_chain() == (True, None)
    with pytest.raises(sqlite3.DatabaseError):
        L.db.execute("UPDATE audit SET result='x' WHERE id=2")
    with pytest.raises(sqlite3.DatabaseError):
        L.db.execute("DELETE FROM audit WHERE id=2")


def test_tamper_detected(tmp_path):
    L = Ledger(tmp_path / "x.sqlite")
    for i in range(3):
        L.audit("a", "carson", {"i": i}, "ok")
    L.db.execute("DROP TRIGGER audit_no_update")
    L.db.execute("UPDATE audit SET payload='{\"i\":99}' WHERE id=2")
    ok, bad = L.verify_chain()
    assert not ok and bad == 2


def test_nav_marks(tmp_path):
    from decimal import Decimal as D
    L = Ledger(tmp_path / "x.sqlite")
    assert L.nav_mark("2026-11-24", D("1000")) == (D("1000"), D("1000"))
    assert L.nav_mark("2026-11-24", D("1100")) == (D("1000"), D("1100"))
    assert L.nav_mark("2026-11-25", D("1050")) == (D("1050"), D("1100"))
