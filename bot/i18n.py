# Copyright (c) 2025 anonysec. All rights reserved.
# Proprietary and confidential. Unauthorized copying, distribution, or use is prohibited.

"""Bot translations — same four languages as the panel (en/fa/ru/cn)."""

from __future__ import annotations

import json
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

_TELEGRAM_MAP = {
    "en": "en",
    "fa": "fa",
    "ru": "ru",
    "zh": "cn",
    "zh-cn": "cn",
    "zh-hans": "cn",
    "zh-hant": "cn",
    "cn": "cn",
}

_MENU_KEYS = {
    "btn_users": "users",
    "btn_new": "new",
    "btn_status": "status",
    "btn_nodes": "nodes",
    "btn_cancel": "cancel",
    "btn_language": "language",
}


def normalize(code: str | None) -> str:
    if not code:
        return DEFAULT_LANG
    raw = str(code).replace("_", "-").strip().lower()
    if raw in LOCALES:
        return raw
    primary = raw.split("-", 1)[0]
    return _TELEGRAM_MAP.get(raw) or _TELEGRAM_MAP.get(primary) or DEFAULT_LANG


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


def lang_of(update: Any = None, context: Any = None) -> str:
    if context is not None:
        stored = context.user_data.get("lang") if getattr(context, "user_data", None) else None
        if stored in LOCALES:
            return stored
    user = getattr(update, "effective_user", None) if update else None
    code = getattr(user, "language_code", None) if user else None
    if code:
        return normalize(code)
    return DEFAULT_LANG


def set_lang(context: Any, lang: str) -> str:
    lang = normalize(lang)
    context.user_data["lang"] = lang
    return lang


def menu_action(text: str | None) -> str | None:
    """Map a reply-keyboard label in any language to a stable action id."""
    if not text:
        return None
    for lang in LOCALES:
        cat = _catalog(lang)
        for key, action in _MENU_KEYS.items():
            if cat.get(key) == text:
                return action
    return None
