# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Bot flow tests: API contract branches, session recovery, create gate,
delete-undo, owner edit flow, unknown commands and node drill-down.

Telegram objects are faked with SimpleNamespace; Panel is faked per-module
(the handlers do `from bot.api import Panel`, so each module attribute is
patched where it is looked up).
"""

from types import SimpleNamespace

import pytest

from bot.i18n import t
from bot.identity import Actor, _identity_cache, _token_cache


class FakeMessage:
    def __init__(self, text=""):
        self.text = text
        self.sent = []

    async def reply_text(self, text, **kwargs):
        self.sent.append((text, kwargs))

    async def reply_document(self, **kwargs):
        self.sent.append(("__document__", kwargs))


class FakeQuery:
    def __init__(self, data=""):
        self.data = data
        self.edited = []
        self.answered = []

    async def answer(self, text=None):
        self.answered.append(text)

    async def edit_message_text(self, text, **kwargs):
        self.edited.append((text, kwargs))


def make_update(text="", callback_data=None):
    return SimpleNamespace(
        effective_message=FakeMessage(text),
        callback_query=FakeQuery(callback_data) if callback_data is not None else None,
        effective_user=SimpleNamespace(id=7),
    )


def make_context(**extra):
    return SimpleNamespace(user_data={"lang": "en", **extra})


def make_actor(role="owner"):
    return Actor(telegram_id=7, username="boss", role=role, token="tok-1")


def all_texts(update):
    out = [text for text, _ in update.effective_message.sent if isinstance(text, str)]
    if update.callback_query:
        out += [text for text, _ in update.callback_query.edited]
    return out


def all_markups(update):
    out = [kw.get("reply_markup") for _, kw in update.effective_message.sent]
    if update.callback_query:
        out += [kw.get("reply_markup") for _, kw in update.callback_query.edited]
    return [m for m in out if m is not None]


def callbacks(markup):
    return [b.callback_data for row in markup.inline_keyboard for b in row]


class FakePanel:
    """Canned Panel double; override async methods per test."""

    def __init__(self, *args, **kwargs):
        self.last_status = 200
        self.calls = []

    async def get_user(self, *, uuid=None, name=None):
        self.calls.append(("get_user", uuid, name))
        return None

    async def extend_user(self, uuid, *, days=0, bytes_=0):
        self.calls.append(("extend", uuid, days, bytes_))
        return {"success": True, "status": 200}

    async def reset_usage(self, uuid):
        return {"success": True, "status": 200}

    async def disconnect(self, uuid):
        return {"success": True, "status": 200}

    async def set_status(self, uuid, name, active):
        return {"success": True, "status": 200}

    async def delete_user(self, uuid):
        return {"success": True, "status": 200}

    async def restore_user(self, uuid):
        return {"success": True, "status": 200}

    async def update_user(self, uuid, name, **fields):
        self.calls.append(("update", uuid, name, fields))
        return {"success": True, "status": 200}

    async def get_nodes(self):
        return []

    async def node_status(self, node_id):
        return {"success": True, "status": 200, "data": {}}

    async def get_sub_url(self, uuid):
        return f"https://panel/sub/{uuid}"

    async def next_username(self):
        return None


@pytest.mark.asyncio
async def test_panel_request_branches(monkeypatch):
    import bot.api as api_mod

    seen = {}

    class Resp:
        def __init__(self, status, body=None, raw=None):
            self.status_code = status
            self._body = body
            self._raw = raw
            self.headers = {}
            self.text = raw.decode() if isinstance(raw, bytes) else str(raw or "")
            self.content = raw if isinstance(raw, bytes) else b""

        def json(self):
            if self._raw is not None or isinstance(self._body, Exception):
                raise ValueError("not json")
            return self._body

    class FakeClient:
        is_closed = False

        def __init__(self, resp):
            self.resp = resp

        async def request(self, method, url, headers=None, **kwargs):
            seen["url"] = url
            if isinstance(self.resp, Exception):
                raise self.resp
            return self.resp

    async def call_with(resp):
        monkeypatch.setattr(api_mod, "_client", FakeClient(resp))
        panel = api_mod.Panel("tok")
        result = await panel.request("GET", "/users/")
        return panel, result

    panel, result = await call_with(Resp(200, {"success": True, "data": []}))
    assert result["success"] is True and result["status"] == 200 and panel.last_status == 200
    assert seen["url"].endswith("/users/")

    _, result = await call_with(Resp(200, [{"a": 1}]))
    assert result["success"] is True and result["data"] == [{"a": 1}]

    _, result = await call_with(Resp(200, None, raw=b"client-data"))
    assert result["success"] is True and result["raw"] is True

    _, result = await call_with(Resp(404, {"detail": "User not found"}))
    assert result == {"success": False, "msg": "User not found", "status": 404}

    _, result = await call_with(Resp(422, {"detail": [{"msg": "bad"}, {"msg": "worse"}]}))
    assert result["msg"] == "bad; worse" and result["status"] == 422

    panel, result = await call_with(ConnectionError("down"))
    assert result == {"success": False, "msg": "Panel is unreachable.", "status": 0}
    assert panel.last_status == 0

    panel, result = await call_with(Resp(401, {"detail": "expired"}))
    assert result["status"] == 401 and panel.last_status == 401


@pytest.mark.asyncio
async def test_restore_user_path(monkeypatch):
    import bot.api as api_mod

    called = {}

    class FakeClient:
        is_closed = False

        async def request(self, method, url, headers=None, **kwargs):
            called["method"] = method
            called["url"] = url

            class Resp:
                status_code = 200

                def json(self):
                    return {"success": True, "msg": "User restored successfully"}

            return Resp()

    monkeypatch.setattr(api_mod, "_client", FakeClient())
    result = await api_mod.Panel("tok").restore_user("some-uuid")
    assert called["method"] == "POST"
    assert called["url"].endswith("/users/some-uuid/restore")
    assert result["success"] is True


@pytest.mark.asyncio
async def test_ensure_panel_ok_unauthorized_resets_session():
    from bot.handlers.access import ensure_panel_ok
    from bot.identity import _identity_cache as cache

    actor = make_actor()
    cache[7] = (0.0, actor)
    update = make_update(callback_data="u:x")
    context = make_context(actor=actor)
    assert await ensure_panel_ok(update, context, actor, {"success": False, "status": 401}) is False
    assert 7 not in cache
    assert "actor" not in context.user_data
    assert any(t("en", "session_expired") in text for text in all_texts(update))


@pytest.mark.asyncio
async def test_ensure_panel_ok_unreachable_and_ok():
    from bot.handlers.access import ensure_panel_ok

    actor = make_actor()
    update = make_update(callback_data="u:x")
    context = make_context()
    assert await ensure_panel_ok(update, context, actor, {"success": False, "status": 0}) is False
    assert any(t("en", "panel_unreachable") in text for text in all_texts(update))

    update2 = make_update(callback_data="u:x")
    assert await ensure_panel_ok(update2, make_context(), actor, {"success": True, "status": 200}) is True
    assert all_texts(update2) == []


@pytest.mark.asyncio
async def test_invalidate_token_sweeps_caches():
    from bot.identity import _identity_cache as cache
    from bot.identity import _token_cache as tcaches
    from bot.identity import invalidate_token

    actor = make_actor()
    cache[7] = (0.0, actor)
    tcaches[("boss", "owner")] = (0.0, "tok-1")
    tcaches[("other", "admin")] = (0.0, "tok-9")
    invalidate_token("tok-1")
    assert 7 not in cache
    assert ("boss", "owner") not in tcaches
    assert ("other", "admin") in tcaches
    _identity_cache.clear()
    _token_cache.clear()


@pytest.mark.asyncio
async def test_create_confirm_gated_on_valid_input(monkeypatch):
    from bot.handlers import create as create_mod

    monkeypatch.setattr(create_mod, "Panel", FakePanel)
    actor = make_actor()
    update = make_update(text="not-a-number")
    context = make_context(flow={"kind": "create", "step": "logins", "name": "amy"})
    await create_mod.handle_create_text(update, context, actor, "not-a-number")
    assert context.user_data["flow"]["step"] == "logins"
    assert any(t("en", "create_need_int") in text for text in all_texts(update))
    assert not any("Confirm" in text or "confirm" in text.lower() and "plan" in text.lower() for text in all_texts(update))


@pytest.mark.asyncio
async def test_delete_then_undo(monkeypatch):
    from bot.handlers import actions as actions_mod

    class DeletingPanel(FakePanel):
        async def get_user(self, *, uuid=None, name=None):
            return {"uuid": "u-1", "name": "amy", "is_active": True}

    monkeypatch.setattr(actions_mod, "Panel", DeletingPanel)
    actor = make_actor()
    update = make_update(callback_data="okd:u-1")
    context = make_context()
    await actions_mod._delete(update, context, actor, "u-1")
    markups = all_markups(update)
    assert markups, "delete success must offer the undo keyboard"
    assert any(cb.startswith("undo:") for m in markups for cb in callbacks(m))

    update2 = make_update(callback_data="undo:u-1")
    await actions_mod._undo_delete(update2, make_context(), actor, "u-1")
    assert any(t("en", "restored_ok") in text for text in all_texts(update2))


@pytest.mark.asyncio
async def test_edit_flow_owner_only_and_happy_path(monkeypatch):
    from bot.handlers import edit as edit_mod

    class EditingPanel(FakePanel):
        async def get_user(self, *, uuid=None, name=None):
            return {"uuid": "u-1", "name": "amy", "is_active": True}

    monkeypatch.setattr(edit_mod, "Panel", EditingPanel)
    monkeypatch.setattr("bot.handlers.users.Panel", EditingPanel)

    admin = make_actor(role="admin")
    update = make_update(callback_data="edt:u-1")
    await edit_mod.start_edit(update, make_context(), admin, "u-1")
    assert any(t("en", "edit_owner_only") in text for text in all_texts(update))

    owner = make_actor(role="owner")
    update2 = make_update(callback_data="edt:u-1")
    context2 = make_context()
    await edit_mod.start_edit(update2, context2, owner, "u-1")
    assert context2.user_data["flow"]["kind"] == "edit"
    assert any(cb.startswith("edf:") for m in all_markups(update2) for cb in callbacks(m))

    update3 = make_update(callback_data="edf:traffic")
    await edit_mod.handle_edit_callback(update3, context2, owner, "edf:traffic")
    assert context2.user_data["flow"]["step"] == "value"

    update4 = make_update(text="oops")
    await edit_mod.handle_edit_text(update4, context2, owner, "oops")
    assert context2.user_data["flow"]["step"] == "value"

    update5 = make_update(text="10")
    await edit_mod.handle_edit_callback(update5, context2, owner, "edf:traffic")
    await edit_mod.handle_edit_text(update5, context2, owner, "10")
    assert context2.user_data["flow"]["step"] == "confirm"

    update6 = make_update(callback_data="edo")
    await edit_mod.handle_edit_callback(update6, context2, owner, "edo")
    assert any(t("en", "edit_ok", name="amy") in text for text in all_texts(update6))
    assert "flow" not in context2.user_data


@pytest.mark.asyncio
async def test_unknown_command_returns_home(monkeypatch):
    from bot.handlers import router as router_mod

    actor = make_actor()
    update = make_update(text="/frobnicate")
    context = make_context(actor=actor, flow={"kind": "create", "step": "name"})
    await router_mod.on_unknown_command(update, context)
    assert "flow" not in context.user_data
    assert any(t("en", "home_prompt") in text for text in all_texts(update))


@pytest.mark.asyncio
async def test_node_drill_down(monkeypatch):
    from bot.handlers import status as status_mod

    class NodePanel(FakePanel):
        async def get_nodes(self):
            return [{"id": 3, "name": "n3", "status": True}]

        async def node_status(self, node_id):
            assert node_id == 3
            return {
                "success": True,
                "status": 200,
                "data": {
                    "node_info": {"cpu_usage": 11, "memory_usage": 22, "version": "1.6.0", "openvpn_running": True},
                    "session_diagnostics": {"live_count": 4},
                },
            }

    monkeypatch.setattr(status_mod, "Panel", NodePanel)
    update = make_update(callback_data="ns:3")
    await status_mod.show_node_detail(update, make_context(), make_actor(), 3)
    texts = all_texts(update)
    assert any("n3" in text for text in texts)
    assert any("11%" in text for text in texts)
