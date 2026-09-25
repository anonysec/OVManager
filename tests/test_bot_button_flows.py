# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Button-first bot flows: persistent section menu, inline user actions,
plan-first creation, stats/settings routing and text fallbacks.

Same fakes as test_bot_flows.py — Telegram objects are SimpleNamespace and
Panel is patched per module where the handlers look it up.
"""

from types import SimpleNamespace

import pytest
from telegram import ReplyKeyboardMarkup

from bot.i18n import LOCALES, menu_action, t
from bot.identity import Actor
from bot.keyboards import home_actions, main_menu, user_actions


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


def reply_labels(markup):
    return [b.text for row in markup.keyboard for b in row]


class FakePanel:
    def __init__(self, *args, **kwargs):
        self.last_status = 200

    async def get_user(self, *, uuid=None, name=None):
        return None

    async def get_users(self, search=None):
        return []

    async def search_users(self, query):
        return []

    async def get_nodes(self):
        return []

    async def get_sub_url(self, uuid):
        return f"https://panel/sub/{uuid}"

    async def next_username(self):
        return None

    async def create_user(self, name, days, traffic_gb, max_logins):
        return {"success": True, "status": 200, "data": {"uuid": "u-9", "name": name}}


def test_menu_labels_map_to_actions_in_every_language():
    for lang in LOCALES:
        assert menu_action(t(lang, "btn_users")) == "users"
        assert menu_action(t(lang, "btn_new")) == "new"
        assert menu_action(t(lang, "btn_status")) == "status"
        assert menu_action(t(lang, "btn_settings")) == "settings"
    assert menu_action("Create") == "new"
    assert menu_action("Stats") == "status"
    assert menu_action("Settings") == "settings"


def test_main_menu_sections_owner_and_admin():
    owner_menu = main_menu(lang="en", is_owner=True)
    assert isinstance(owner_menu, ReplyKeyboardMarkup)
    assert owner_menu.is_persistent is True
    labels = reply_labels(owner_menu)
    assert labels[:4] == ["Users", "Create", "Stats", "Nodes"]
    assert "Settings" in labels

    admin_labels = reply_labels(main_menu(lang="en", is_owner=False))
    assert "Settings" not in admin_labels
    assert "Users" in admin_labels and "Stats" in admin_labels


def test_home_inline_actions_settings_owner_only():
    owner_cbs = callbacks(home_actions(lang="en", is_owner=True))
    assert "settings" in owner_cbs
    assert "users:0" in owner_cbs and "new" in owner_cbs

    admin_cbs = callbacks(home_actions(lang="en", is_owner=False))
    assert "settings" not in admin_cbs


def test_user_actions_cover_every_operation():
    user = {"uuid": "u-1", "name": "amy", "is_active": True}
    data = callbacks(user_actions(user, lang="en"))
    expected_cbs = (
        "e30:u-1",
        "e90:u-1",
        "eb10:u-1",
        "eb100:u-1",
        "rst:u-1",
        "tog:u-1",
        "dis:u-1",
        "del:u-1",
        "cfg:u-1",
        "sub:u-1",
    )
    for expected in expected_cbs:
        assert expected in data
    assert "edt:u-1" not in data
    assert "okd:u-1" not in data

    disabled_labels = [b.text for row in user_actions({**user, "is_active": False}, lang="en").inline_keyboard for b in row]
    assert t("en", "act_enable") in disabled_labels

    owner_data = callbacks(user_actions(user, is_owner=True, lang="en"))
    assert "edt:u-1" in owner_data


@pytest.mark.asyncio
async def test_start_shows_persistent_sections_and_home_actions():
    from bot.handlers.home import handle_start

    update = make_update(text="/start")
    context = make_context(actor=make_actor())
    await handle_start(update, context)
    markups = all_markups(update)
    keyboard = next(m for m in markups if isinstance(m, ReplyKeyboardMarkup))
    labels = reply_labels(keyboard)
    assert labels[:4] == ["Users", "Create", "Stats", "Nodes"]
    assert "Settings" in labels
    assert "settings" in callbacks(next(m for m in markups if not isinstance(m, ReplyKeyboardMarkup)))

    admin_update = make_update(text="/start")
    await handle_start(admin_update, make_context(actor=make_actor(role="admin")))
    admin_keyboard = next(m for m in all_markups(admin_update) if isinstance(m, ReplyKeyboardMarkup))
    assert "Settings" not in reply_labels(admin_keyboard)


@pytest.mark.asyncio
async def test_text_stats_reuses_status_summary(monkeypatch):
    from bot.handlers import router as router_mod
    from bot.handlers import status as status_mod

    class StatsPanel(FakePanel):
        async def get_info(self):
            return {"uptime": 3661, "cpu": 5, "memory_percent": 20, "disk_percent": 30}

        async def get_settings(self):
            return {"panel_version": "2.0.2"}

        async def get_users(self, search=None):
            return [{"uuid": "u1", "name": "amy", "is_active": True, "expiry_date": "2099-12-31"}]

    monkeypatch.setattr(status_mod, "Panel", StatsPanel)
    update = make_update(text="Stats")
    await router_mod.on_text(update, make_context(actor=make_actor()))
    texts = all_texts(update)
    assert any("Panel" in text and "2.0.2" in text for text in texts)
    assert any("1h 1m" in text for text in texts)


@pytest.mark.asyncio
async def test_text_settings_owner_view_and_admin_denied():
    from bot.handlers import router as router_mod

    owner_update = make_update(text="Settings")
    await router_mod.on_text(owner_update, make_context(actor=make_actor()))
    owner_texts = all_texts(owner_update)
    assert any(t("en", "settings_defaults") in text for text in owner_texts)
    assert any(t("en", "settings_bot", state=t("en", "settings_disabled")) in text for text in owner_texts)
    assert "settings" in callbacks(all_markups(owner_update)[-1])  # refresh

    admin_update = make_update(text="Settings")
    await router_mod.on_text(admin_update, make_context(actor=make_actor(role="admin")))
    assert any(t("en", "settings_owner_only") in text for text in all_texts(admin_update))


@pytest.mark.asyncio
async def test_callback_settings_opens_owner_view():
    from bot.handlers import router as router_mod

    update = make_update(callback_data="settings")
    await router_mod.on_callback(update, make_context(actor=make_actor()))
    texts = all_texts(update)
    assert any(t("en", "settings_title") in text for text in texts)
    assert "home" in callbacks(all_markups(update)[-1])


@pytest.mark.asyncio
async def test_text_create_opens_plan_picker_first():
    from bot.handlers import router as router_mod

    update = make_update(text="Create")
    context = make_context(actor=make_actor())
    await router_mod.on_text(update, context)
    assert context.user_data["flow"] == {"kind": "create", "step": "plan"}
    plan_cbs = callbacks(all_markups(update)[-1])
    assert "plan:standard" in plan_cbs and "plan:custom" in plan_cbs and "cancel" in plan_cbs


@pytest.mark.asyncio
async def test_create_plan_then_name_then_confirm(monkeypatch):
    from bot.handlers import create as create_mod
    from bot.handlers import users as users_mod

    created = []

    class CreatePanel(FakePanel):
        async def user_defaults(self):
            return {"days": 7, "traffic_gb": 5, "max_users": 2}

        async def get_user(self, *, uuid=None, name=None):
            if uuid == "u-9":
                return {"uuid": "u-9", "name": "bob", "is_active": True, "expiry_date": "2099-12-31"}
            return None

        async def create_user(self, name, days, traffic_gb, max_logins):
            created.append((name, days, traffic_gb, max_logins))
            return {"success": True, "status": 200, "data": {"uuid": "u-9", "name": name}}

    monkeypatch.setattr(create_mod, "Panel", CreatePanel)
    monkeypatch.setattr(users_mod, "Panel", CreatePanel)
    actor = make_actor()

    update = make_update(callback_data="new")
    context = make_context()
    await create_mod.start_create(update, context, actor)
    assert context.user_data["flow"]["step"] == "plan"

    update2 = make_update(callback_data="plan:standard")
    await create_mod.handle_create_callback(update2, context, actor, "plan:standard")
    assert context.user_data["flow"]["step"] == "name"
    # Standard = the acting admin's effective plan, not the fixed env default.
    assert (
        context.user_data["flow"]["days"],
        context.user_data["flow"]["traffic"],
        context.user_data["flow"]["logins"],
    ) == (7, 5, 2)
    assert "auto" in callbacks(all_markups(update2)[-1])

    update3 = make_update(text="bob")
    await create_mod.handle_create_text(update3, context, actor, "bob")
    assert context.user_data["flow"]["step"] == "confirm"
    assert "okc" in callbacks(all_markups(update3)[-1])

    update4 = make_update(callback_data="okc")
    await create_mod.handle_create_callback(update4, context, actor, "okc")
    assert created == [("bob", 7, 5, 2)]
    assert "flow" not in context.user_data
    assert any(t("en", "create_ok", name="bob") in text for text in all_texts(update4))


@pytest.mark.asyncio
async def test_standard_plan_falls_back_to_local_config_when_panel_has_no_defaults(monkeypatch):
    from bot.handlers import create as create_mod

    class NoDefaultsPanel(FakePanel):
        async def user_defaults(self):
            return None

    monkeypatch.setattr(create_mod, "Panel", NoDefaultsPanel)
    actor = make_actor()
    update = make_update(callback_data="plan:standard")
    context = make_context()
    context.user_data["flow"] = {"kind": "create", "step": "plan"}
    await create_mod.handle_create_callback(update, context, actor, "plan:standard")
    flow = context.user_data["flow"]
    assert (flow["days"], flow["traffic"]) == (
        create_mod.config.default_days,
        create_mod.config.default_traffic_gb,
    )


@pytest.mark.asyncio
async def test_create_custom_asks_values_after_name(monkeypatch):
    from bot.handlers import create as create_mod

    monkeypatch.setattr(create_mod, "Panel", FakePanel)
    actor = make_actor()
    update = make_update(callback_data="new")
    context = make_context()
    await create_mod.start_create(update, context, actor)

    update2 = make_update(callback_data="plan:custom")
    await create_mod.handle_create_callback(update2, context, actor, "plan:custom")
    assert context.user_data["flow"]["step"] == "name"

    update3 = make_update(text="carol")
    await create_mod.handle_create_text(update3, context, actor, "carol")
    assert context.user_data["flow"]["step"] == "days"
    assert any(t("en", "create_custom_days") in text for text in all_texts(update3))

    update4 = make_update(text="10")
    await create_mod.handle_create_text(update4, context, actor, "10")
    assert context.user_data["flow"]["step"] == "traffic"

    update5 = make_update(text="5")
    await create_mod.handle_create_text(update5, context, actor, "5")
    assert context.user_data["flow"]["step"] == "logins"

    update6 = make_update(text="2")
    await create_mod.handle_create_text(update6, context, actor, "2")
    assert context.user_data["flow"]["step"] == "confirm"
    assert "okc" in callbacks(all_markups(update6)[-1])


@pytest.mark.asyncio
async def test_free_text_during_plan_step_reshows_buttons(monkeypatch):
    from bot.handlers import create as create_mod

    monkeypatch.setattr(create_mod, "Panel", FakePanel)
    actor = make_actor()
    update = make_update(callback_data="new")
    context = make_context()
    await create_mod.start_create(update, context, actor)

    update2 = make_update(text="daft-name")
    await create_mod.handle_create_text(update2, context, actor, "daft-name")
    assert context.user_data["flow"]["step"] == "plan"
    assert any(t("en", "create_choose_plan") in text for text in all_texts(update2))
    assert "plan:custom" in callbacks(all_markups(update2)[-1])


@pytest.mark.asyncio
async def test_unknown_text_guides_back_to_menu(monkeypatch):
    from bot.handlers import router as router_mod
    from bot.handlers import users as users_mod

    monkeypatch.setattr(users_mod, "Panel", FakePanel)
    update = make_update(text="zzz-not-a-name")
    await router_mod.on_text(update, make_context(actor=make_actor()))
    assert any(t("en", "search_none", query="zzz-not-a-name") in text for text in all_texts(update))
    fallback_cbs = callbacks(all_markups(update)[-1])
    assert "search" in fallback_cbs and "new" in fallback_cbs


@pytest.mark.asyncio
async def test_delete_button_asks_confirmation(monkeypatch):
    from bot.handlers import actions as actions_mod

    class DeletingPanel(FakePanel):
        async def get_user(self, *, uuid=None, name=None):
            return {"uuid": "u-1", "name": "amy", "is_active": True}

    monkeypatch.setattr(actions_mod, "Panel", DeletingPanel)
    update = make_update(callback_data="del:u-1")
    await actions_mod.dispatch_action(update, make_context(), make_actor(), "del:u-1")
    texts = all_texts(update)
    assert any(t("en", "delete_ask", name="amy") in text for text in texts)
    confirm_cbs = callbacks(all_markups(update)[-1])
    assert "okd:u-1" in confirm_cbs and "u:u-1" in confirm_cbs
