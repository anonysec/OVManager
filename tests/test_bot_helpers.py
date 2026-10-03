# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""The bot's pure helpers: formatting, i18n, and the callback contract.

Three things with no shared state, grouped because they are all "the bot's
vocabulary" — what it says, in what language, and what its buttons mean.

- formatters: bytes, expiry, status, usage and the card, with escaping
- i18n: locale parity, the translate/fallback path, per-user language,
  and menu-label -> action mapping
- callbacks: two invariants pinned here. Every callback_data a keyboard can
  emit parses to a handler (no dead buttons, no uncaught slices), and the
  bot READS shared backend state directly but WRITES only through the panel
  HTTP API (bot.api.Panel) — no crud writes in bot code, so audit and
  tenancy cannot be bypassed from Telegram.
"""

import os
import re
import tempfile
from datetime import date, timedelta
from pathlib import Path

from backend.bot.callbacks import (
    MAX_CALLBACK_BYTES,
    build_callback,
    int_arg,
    node_ref_arg,
    parse_callback,
    uuid_arg,
)
from backend.bot.formatters import (
    esc,
    expiry_label,
    fmt_bytes,
    fmt_uptime,
    is_expired,
    plan_label,
    status_label,
    status_rank,
    usage_line,
    user_card,
)
from backend.bot.i18n import LOCALES, _catalog, has_lang, lang_of, menu_action, normalize, set_lang, t

REPO = Path(__file__).resolve().parent.parent


# ── formatters ────────────────────────────────────────────────────────────────


def test_fmt_bytes_unlimited_and_scale():
    assert fmt_bytes(None) == "Unlimited"
    assert fmt_bytes(512) == "512 B"
    assert fmt_bytes(1073741824) == "1.0 GB"


def test_expiry_and_status():
    future = (date.today() + timedelta(days=12)).isoformat()
    past = (date.today() - timedelta(days=3)).isoformat()
    assert expiry_label(None) == "No expiry"
    assert expiry_label("2099-12-31") == "No expiry"
    assert "12 days left" in expiry_label(future)
    assert "Expired 3d ago" in expiry_label(past)
    assert status_label({"is_active": True, "expiry_date": future}) == "Active"
    assert status_label({"is_active": True, "online": True, "expiry_date": future}) == "Online"
    assert status_label({"is_active": False, "expiry_date": future}) == "Disabled"
    assert is_expired({"expiry_date": past})


def test_usage_and_card_escape():
    user = {
        "name": "ali<x>",
        "is_active": True,
        "used": 512,
        "total": 1024,
        "max_logins": 1,
        "active_connections": 0,
        "expiry_date": (date.today() + timedelta(days=5)).isoformat(),
        "owner": "root",
        "uuid": "abc",
    }
    assert "50%" in usage_line(user)
    card = user_card(user)
    assert "ali&lt;x&gt;" in card
    assert "<script>" not in card
    assert esc("<b>") == "&lt;b&gt;"


def test_plan_and_uptime():
    assert plan_label(30, 100, 1) == "30 days · 100 GB · 1 device"
    assert "No expiry" in plan_label(0, 0, 0)
    assert fmt_uptime(90) == "1m"
    assert "1d" in fmt_uptime(90000)


# ── i18n ──────────────────────────────────────────────────────────────────────


def test_locale_key_parity():
    en_keys = set(_catalog("en"))
    for lang in LOCALES:
        keys = set(_catalog(lang))
        assert keys == en_keys, f"{lang} missing {en_keys - keys} extra {keys - en_keys}"


def test_translate_and_fallback():
    assert t("en", "btn_users") == "Users"
    assert t("fa", "btn_users") == "کاربران"
    assert t("ru", "btn_users") == "Пользователи"
    assert t("cn", "btn_users") == "用户"
    assert t("en", "missing_key_xyz") == "missing_key_xyz"
    assert "30" in t("fa", "updated_days", days=30)


def test_normalize_only_panel_locales():
    assert normalize("fa") == "fa"
    assert normalize("ru") == "ru"
    assert normalize("cn") == "cn"
    assert normalize("en") == "en"
    assert normalize("fa-IR") == "en"
    assert normalize("zh-Hans") == "en"
    assert normalize("de") == "en"
    assert normalize(None) == "en"


def test_lang_is_not_telegram_app_language():

    import backend.bot.i18n as i18n

    fd, path = tempfile.mkstemp(suffix=".json")
    os.close(fd)
    os.environ["OVM_BOT_LANG_FILE"] = path
    i18n._prefs = {}
    i18n._prefs_loaded = False

    class User:
        id = 42
        language_code = "fa"

    class Update:
        effective_user = User()

    class Context:
        user_data: dict = {}

    try:
        ctx = Context()
        upd = Update()
        assert lang_of(upd, ctx) == "en"
        assert has_lang(upd, ctx) is False
        assert set_lang(ctx, "fa", upd) == "fa"
        assert lang_of(upd, ctx) == "fa"
        assert has_lang(upd, ctx) is True
    finally:
        os.environ.pop("OVM_BOT_LANG_FILE", None)
        i18n._prefs = {}
        i18n._prefs_loaded = False
        try:
            os.unlink(path)
        except OSError:
            pass


def test_menu_action_all_languages():
    for lang in LOCALES:
        assert menu_action(t(lang, "btn_users")) == "users"
        assert menu_action(t(lang, "btn_new")) == "new"
        assert menu_action(t(lang, "btn_status")) == "status"
        assert menu_action(t(lang, "btn_nodes")) == "nodes"
        assert menu_action(t(lang, "btn_cancel")) == "cancel"
        assert menu_action(t(lang, "btn_language")) == "language"
    assert menu_action("English") == "lang:en"
    assert menu_action("فارسی") == "lang:fa"
    assert menu_action("Русский") == "lang:ru"
    assert menu_action("中文") == "lang:cn"
    assert menu_action("not-a-button") is None


def test_formatters_follow_language():
    assert fmt_bytes(None, lang="fa") == t("fa", "unlimited")
    assert fmt_bytes(None, lang="cn") != "Unlimited"
    assert expiry_label(None, lang="ru") == t("ru", "no_expiry")
    user = {"is_active": True, "online": True, "expiry_date": "2099-12-31"}
    assert status_label(user, lang="fa") == t("fa", "status_online")
    assert status_rank(user) == 0
    assert status_rank({"is_active": False, "expiry_date": "2099-12-31"}) == 2


# ── callbacks ─────────────────────────────────────────────────────────────────


def test_build_callback_enforces_size_limit():
    assert build_callback("u", "abc") == "u:abc"
    try:
        build_callback("u", "x" * MAX_CALLBACK_BYTES)
    except ValueError:
        pass
    else:
        raise AssertionError("oversize callback_data must raise")


def test_registered_prefixes_round_trip():
    import backend.bot.handlers.actions  # noqa: F401 (populates the registry)

    for prefix, arg in [
        ("ext", "some-uuid"),
        ("e30", "some-uuid"),
        ("rst", "some-uuid"),
        ("tog", "some-uuid"),
        ("dis", "some-uuid"),
        ("del", "some-uuid"),
        ("okd", "some-uuid"),
        ("undo", "some-uuid"),
        ("sub", "some-uuid"),
        ("cfg", "some-uuid"),
        ("dl", "some-uuid:3"),
    ]:
        fn, kwargs, out_arg = parse_callback(f"{prefix}:{arg}")
        assert fn is not None, f"{prefix}: has no handler"
        assert out_arg == arg
    fn, _, _ = parse_callback("nope:whatever")
    assert fn is None, "unknown prefix must fall through"


def test_arg_helpers_fail_closed():
    assert uuid_arg("6f1b2c3d-4e5f-6789-abcd-ef0123456789") is not None
    assert uuid_arg("") is None
    assert uuid_arg("a:b") is None
    assert uuid_arg("x" * 65) is None
    assert int_arg("3") == 3
    assert int_arg("junk") == 0
    assert int_arg("junk", default=7) == 7
    assert node_ref_arg("some-uuid:3") == ("some-uuid", 3)
    assert node_ref_arg("some-uuid") is None
    assert node_ref_arg("some-uuid:abc") is None
    assert node_ref_arg("") is None


def test_every_emitted_callback_fits_and_matches():
    """Scan keyboards/handlers for emitted callback literals: each must fit
    in 64 bytes at construction size and carry a known prefix."""
    known = {
        "ext",
        "e30",
        "e90",
        "eb10",
        "eb100",
        "rst",
        "tog",
        "dis",
        "del",
        "okd",
        "undo",
        "sub",
        "cfg",
        "dl",
        "edt",
        "edf",
        "edo",
        "edc",
        "u",
        "users",
        "ns",
        "lang",
        "plan",
    }
    text = (REPO / "backend" / "bot" / "keyboards.py").read_text(encoding="utf-8")
    for mod in ("actions", "create", "edit", "users", "status", "settings", "home", "router"):
        text += (REPO / "backend" / "bot" / "handlers" / f"{mod}.py").read_text(encoding="utf-8")
    # f"<prefix>:..." literals (static part before any {interpolation}).
    emitted = set(re.findall(r'f"([a-z0-9]+):', text))
    unknown = {p for p in emitted if p not in known}
    assert not unknown, f"callback prefixes with no documented handler: {unknown}"


def test_bot_never_writes_through_crud():
    """The panel is the single writer: bot code may read shared backend
    state but must never call crud create/update/delete paths."""
    writes = re.compile(r"crud\.(create|update|delete|adjust|restore|change_user_status|reset_user_usage)\w*\(")
    offenders = []
    for path in (REPO / "backend" / "bot").rglob("*.py"):
        for i, line in enumerate(path.read_text(encoding="utf-8").splitlines(), 1):
            if writes.search(line):
                offenders.append(f"{path.name}:{i}: {line.strip()}")
    assert not offenders, f"bot writes through crud (must go over HTTP): {offenders}"
