"""Bot identity must honour the admin `disabled` flag on every resolve path.

Password login gates on `admin.disabled` (backend/auth/auth.py) and
`role_is_current()` re-checks it per request, but the bot resolves identity
from a Telegram ID and mints its own session. Before this guard a disabled
admin kept working straight through Telegram: disabling revoked the panel
sessions, the bot saw 401, dropped its cached actor, and re-minted a fresh
one for the same disabled row on the next tap.
"""

import pytest

from bot.identity import Actor, _identity_cache, _token_cache, resolve


@pytest.fixture(autouse=True)
def _clear_caches():
    _identity_cache.clear()
    _token_cache.clear()
    yield
    _identity_cache.clear()
    _token_cache.clear()


def _make_admin(username: str, telegram_id: int, disabled: bool) -> int:
    from backend.auth.hash import hash_password
    from backend.db.engine import SessionLocal
    from backend.db.models import Admin

    db = SessionLocal()
    try:
        admin = Admin(
            username=username,
            password=hash_password("pw-not-used-here-123"),
            telegram_id=telegram_id,
            disabled=disabled,
        )
        db.add(admin)
        db.commit()
        db.refresh(admin)
        return admin.id
    finally:
        db.close()


def _drop_admin(admin_id: int) -> None:
    from backend.db.engine import SessionLocal
    from backend.db.models import Admin

    db = SessionLocal()
    try:
        row = db.get(Admin, admin_id)
        if row is not None:
            db.delete(row)
            db.commit()
    finally:
        db.close()


@pytest.mark.anyio
async def test_disabled_admin_cannot_resolve():
    admin_id = _make_admin("disabled-bot-admin", 900001, disabled=True)
    try:
        assert await resolve(900001) is None
    finally:
        _drop_admin(admin_id)


@pytest.mark.anyio
async def test_enabled_admin_still_resolves():
    admin_id = _make_admin("enabled-bot-admin", 900002, disabled=False)
    try:
        actor = await resolve(900002)
        assert isinstance(actor, Actor)
        assert actor.role == "admin"
        assert actor.username == "enabled-bot-admin"
        assert actor.token
    finally:
        _drop_admin(admin_id)


@pytest.mark.anyio
async def test_disabling_mid_session_drops_cached_actor():
    admin_id = _make_admin("flip-bot-admin", 900003, disabled=False)
    try:
        assert await resolve(900003) is not None

        from backend.db.engine import SessionLocal
        from backend.db.models import Admin

        db = SessionLocal()
        try:
            row = db.get(Admin, admin_id)
            row.disabled = True
            db.commit()
        finally:
            db.close()

        _identity_cache.clear()
        assert await resolve(900003) is None
    finally:
        _drop_admin(admin_id)


@pytest.mark.anyio
async def test_remote_resolve_skips_disabled_admin(monkeypatch):
    import bot.identity as identity

    class FakePanel:
        def __init__(self, token):
            self.token = token

        async def get_settings(self):
            return {"owner_telegram_id": 0}

        async def get_admins(self):
            return [
                {"username": "off", "telegram_id": 900004, "disabled": True},
                {"username": "on", "telegram_id": 900005, "disabled": False},
            ]

    async def fake_service_token():
        return "svc-token"

    monkeypatch.setattr(identity, "service_token", fake_service_token)
    monkeypatch.setattr("bot.api.Panel", FakePanel)

    assert await resolve(900004) is None

    _identity_cache.clear()
    actor = await resolve(900005)
    assert actor is not None
    assert actor.username == "on"
