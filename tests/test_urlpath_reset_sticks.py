"""`ovm url reset` must survive a restart.

_seed_settings runs on EVERY migrate, not only a fresh install. Treating a
blank prefix as "unset" there meant each boot restored .env's URLPATH, so the
documented recovery from a forgotten prefix silently reverted on the
`ovm restart` the operator was told to run — locking them out again with
nothing in the output saying why.
"""

from backend.config import config
from backend.db.engine import SessionLocal
from backend.db.migrations.seeds import _seed_settings
from backend.db.models import Settings


def test_reset_to_root_is_not_re_seeded_on_the_next_boot(monkeypatch):
    # The bug is only visible when .env actually carries a prefix; with an empty
    # one the re-seed writes "" and looks identical to the fixed behaviour.
    monkeypatch.setattr(config, "URLPATH", "k3y")

    db = SessionLocal()
    try:
        before = db.query(Settings).first()
        saved = before.urlpath if before else None
        had_row = before is not None
        try:
            if before is None:
                _seed_settings(db)
                db.commit()
                before = db.query(Settings).first()

            before.urlpath = ""  # what `ovm url reset` and the UI write
            db.commit()

            _seed_settings(db)  # the next boot
            db.commit()
            assert db.query(Settings).first().urlpath == "", "boot re-seeded the prefix from .env, undoing the operator's reset"
        finally:
            row = db.query(Settings).first()
            if row is not None:
                row.urlpath = saved if had_row else ""
            db.commit()
    finally:
        db.close()
