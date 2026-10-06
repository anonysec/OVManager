# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Sweep expired users that are already disabled.

Runs daily from ``ovmanager-cleanup.timer`` as the panel user. The default is a
dry run: it reports what it would remove and writes an audit event for each
candidate, so an operator can watch a full cycle before arming deletion.
Pass ``--apply`` to actually delete the rows.
"""

from __future__ import annotations

import argparse
import json
import sys
from datetime import date
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))

from backend.db.engine import SessionLocal  # noqa: E402
from backend.db.models import User  # noqa: E402
from backend.logger import logger  # noqa: E402
from backend.operations.observability.audit import log_event  # noqa: E402


def cleanup(apply: bool = False) -> dict:
    db = SessionLocal()
    try:
        today = date.today()
        scanned = db.query(User).count()
        candidates = (
            db.query(User)
            .filter(User.expiry_date < today, User.is_active.is_(False))
            .order_by(User.id)
            .all()
        )
        usernames = [u.name for u in candidates]
        for user in candidates:
            logger.info("cleanup: expired disabled user %s (id=%s, expiry=%s)", user.name, user.id, user.expiry_date)
            log_event(
                db,
                "cleanup.stale_user",
                actor="ovmanager-cleanup",
                target=user.name,
                detail=f"expired={user.expiry_date} apply={apply}",
            )
        if apply:
            for user in candidates:
                db.delete(user)
            db.commit()
            logger.info("cleanup: removed %s expired disabled user(s)", len(candidates))
        return {"scanned": scanned, "expired": len(candidates), "would_remove": usernames}
    finally:
        db.close()


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument(
        "--apply",
        action="store_true",
        help="delete the swept users instead of only reporting them (off by default)",
    )
    args = parser.parse_args()
    result = cleanup(apply=args.apply)
    print(json.dumps(result))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())
