# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Bot translations — same four languages as the panel (en/fa/ru/cn).

Language is never taken from the Telegram app. The operator picks it from
the bot menu / reply keyboard / inline buttons.
"""

from __future__ import annotations

import json
import os
from functools import lru_cache
from pathlib import Path
from typing import Any

LOCALES = ("en", "fa", "ru", "cn")
DEFAULT_LANG = "en"
_DIR = Path(__file__).resolve().parent / "locales"

LANG_NAMES = {
    "en": "English",
    "fa": "فارسی",
    "ru": "Русский",
    "cn": "中文",
}

# First-run prompt is not locale-specific — no language has been chosen yet.
LANG_PROMPT = "<b>Language</b> · زبان · Язык · 语言"

_MENU_KEYS = {
    "btn_users": "users",
    "btn_new": "new",
    "btn_status": "status",
    "btn_nodes": "nodes",
    "btn_cancel": "cancel",
    "btn_language": "language",
}

_prefs: dict[str, str] = {}
_prefs_loaded = False


def normalize(code: str | None) -> str:
    if not code:
        return DEFAULT_LANG
    raw = str(code).strip().lower()
    return raw if raw in LOCALES else DEFAULT_LANG


@lru_cache
def _catalog(lang: str) -> dict:
    path = _DIR / f"{lang}.json"
    if not path.is_file():
        return {}
    data = json.loads(path.read_text(encoding="utf-8"))
    return data if isinstance(data, dict) else {}


def t(lang: str | None, key: str, **kwargs) -> str:
    lang = normalize(lang)
    text = _catalog(lang).get(key)
    if not isinstance(text, str) and lang != DEFAULT_LANG:
        text = _catalog(DEFAULT_LANG).get(key)
    if not isinstance(text, str):
        text = key
    if not kwargs:
        return text
    try:
        return text.format(**kwargs)
    except (KeyError, ValueError, IndexError):
        return text


def _uid(update: Any = None) -> int | None:
    user = getattr(update, "effective_user", None) if update else None
    ident = getattr(user, "id", None)
    return ident if isinstance(ident, int) else None


def _store_path() -> Path:
    return Path(os.getenv("OVM_BOT_LANG_FILE", "data/bot-lang.json"))


def _load_prefs() -> dict[str, str]:
    global _prefs, _prefs_loaded
    if _prefs_loaded:
        return _prefs
    try:
        data = json.loads(_store_path().read_text(encoding="utf-8"))
        if isinstance(data, dict):
            _prefs = {str(k): v for k, v in data.items() if v in LOCALES}
    except Exception:
        _prefs = {}
    _prefs_loaded = True
    return _prefs


def _save_pref(uid: int, lang: str) -> None:
    prefs = _load_prefs()
    prefs[str(uid)] = lang
    path = _store_path()
    try:
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_text(json.dumps(prefs, ensure_ascii=False, indent=0) + "\n", encoding="utf-8")
    except OSError:
        pass


def has_lang(update: Any = None, context: Any = None) -> bool:
    if context is not None:
        stored = context.user_data.get("lang") if getattr(context, "user_data", None) else None
        if stored in LOCALES:
            return True
    uid = _uid(update)
    if uid is None:
        return False
    return _load_prefs().get(str(uid)) in LOCALES


def lang_of(update: Any = None, context: Any = None) -> str:
    if context is not None:
        stored = context.user_data.get("lang") if getattr(context, "user_data", None) else None
        if stored in LOCALES:
            return stored
    uid = _uid(update)
    if uid is not None:
        saved = _load_prefs().get(str(uid))
        if saved in LOCALES:
            if context is not None and getattr(context, "user_data", None) is not None:
                context.user_data["lang"] = saved
            return saved
    return DEFAULT_LANG


def set_lang(context: Any, lang: str, update: Any = None) -> str:
    lang = normalize(lang)
    if context is not None and getattr(context, "user_data", None) is not None:
        context.user_data["lang"] = lang
    uid = _uid(update)
    if uid is not None:
        _save_pref(uid, lang)
    return lang


def menu_action(text: str | None) -> str | None:
    """Map a reply-keyboard label in any language to a stable action id."""
    if not text:
        return None
    for code, name in LANG_NAMES.items():
        if text == name:
            return f"lang:{code}"
    for lang in LOCALES:
        cat = _catalog(lang)
        for key, action in _MENU_KEYS.items():
            if cat.get(key) == text:
                return action
    return None
