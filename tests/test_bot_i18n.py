# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

from bot.formatters import expiry_label, fmt_bytes, status_label, status_rank
from bot.i18n import LOCALES, _catalog, menu_action, normalize, t


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


def test_normalize_telegram_codes():
    assert normalize("fa-IR") == "fa"
    assert normalize("zh-Hans") == "cn"
    assert normalize("zh_CN") == "cn"
    assert normalize("ru") == "ru"
    assert normalize("de") == "en"
    assert normalize(None) == "en"


def test_menu_action_all_languages():
    for lang in LOCALES:
        assert menu_action(t(lang, "btn_users")) == "users"
        assert menu_action(t(lang, "btn_new")) == "new"
        assert menu_action(t(lang, "btn_status")) == "status"
        assert menu_action(t(lang, "btn_nodes")) == "nodes"
        assert menu_action(t(lang, "btn_cancel")) == "cancel"
        assert menu_action(t(lang, "btn_language")) == "language"
    assert menu_action("not-a-button") is None


def test_formatters_follow_language():
    assert fmt_bytes(None, lang="fa") == t("fa", "unlimited")
    assert fmt_bytes(None, lang="cn") != "Unlimited"
    assert expiry_label(None, lang="ru") == t("ru", "no_expiry")
    user = {"is_active": True, "online": True, "expiry_date": "2099-12-31"}
    assert status_label(user, lang="fa") == t("fa", "status_online")
    assert status_rank(user) == 0
    assert status_rank({"is_active": False, "expiry_date": "2099-12-31"}) == 2
