"""One tenancy rule, one place: backend/auth/authz.py.

The rule the whole panel relies on — an admin may touch only their own users,
the owner may touch everything — used to be written out by hand in the users,
node and health routers. Divergence between those copies is a silent privilege
bug, so the shared helper is pinned here.
"""

from types import SimpleNamespace

import pytest
from fastapi import HTTPException

from backend.auth.authz import owned_by, require_user_access


def _user(owner: str):
    return SimpleNamespace(owner=owner)


def test_owner_may_access_any_user():
    require_user_access(_user("someone-else"), {"type": "owner", "username": "boss"})


def test_admin_may_access_their_own_user():
    require_user_access(_user("alice"), {"type": "admin", "username": "alice"})


def test_admin_is_refused_another_admins_user():
    with pytest.raises(HTTPException) as exc:
        require_user_access(_user("bob"), {"type": "admin", "username": "alice"})
    assert exc.value.status_code == 403


def test_a_blank_owner_never_matches():
    """A NULL/empty owner must not become accessible to a blank username."""
    with pytest.raises(HTTPException):
        require_user_access(_user(""), {"type": "admin", "username": "alice"})
    with pytest.raises(HTTPException):
        require_user_access(_user("alice"), {"type": "admin", "username": ""})


def test_owned_by_adds_no_filter_for_the_owner():
    state = {"filtered": False}

    class FakeQuery:
        def filter(self, *args):
            state["filtered"] = True
            return self

    owned_by(FakeQuery(), {"type": "owner", "username": "boss"})
    assert state["filtered"] is False, "the owner must see every user"


def test_owned_by_scopes_the_query_for_an_admin():
    seen = {}

    class FakeQuery:
        def filter(self, expr):
            seen["expr"] = str(expr)
            return self

    owned_by(FakeQuery(), {"type": "admin", "username": "alice"})
    assert "owner" in seen["expr"]
