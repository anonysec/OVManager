"""`python -m backend.db.migrations [--check | --migrate]`."""

from backend.db.migrations.runner import _apply, _self_check

if __name__ == "__main__":
    import sys

    args = sys.argv[1:]
    if "--check" in args:
        raise SystemExit(_self_check())
    if "--migrate" in args:
        raise SystemExit(_apply())
    print("usage: python -m backend.db.migrations [--check | --migrate]")
    raise SystemExit(2)
