"""Owner welcome wizard: first ``/start`` walks through panel setup.

Four steps: welcome, panel URL, ACME opt-in (domain + email when yes), done.
State lives in ``context.user_data["flow"]`` like every other flow. Settings
persist to the panel database; the running instance needs ``ovm restart`` to
pick them up.
"""

from __future__ import annotations

from telegram import Update
from telegram.ext import ContextTypes

from backend.bot.i18n import lang_of, t
from backend.bot.identity import Actor
from backend.bot.states import clear_flow, get_flow, set_flow
from backend.bot.ui import edit_or_reply

_YES = {"yes", "y", "true", "1"}
_NO = {"no", "n", "false", "0"}


def _load_settings():
    try:
        from backend.db.engine import SessionLocal
        from backend.db.models import Settings

        db = SessionLocal()
        try:
            return db, db.query(Settings).first()
        except Exception:
            db.close()
            raise
    except Exception:
        return None, None


def _wizard_pending(actor: Actor) -> bool:
    """True when the owner has a Telegram id but has not finished setup."""
    if actor.role != "owner":
        return False
    db, settings = _load_settings()
    if settings is None:
        return False
    try:
        return bool(settings.owner_telegram_id) and not bool(settings.bot_owner_setup_complete)
    finally:
        db.close()


def _persist(values: dict) -> None:
    try:
        from backend.db.crud.settings import update_bot_config
        from backend.db.engine import SessionLocal

        db = SessionLocal()
        try:
            update_bot_config(db, **values)
        finally:
            db.close()
    except Exception:
        pass


def _is_yes(text: str, lang: str) -> bool:
    low = text.strip().lower()
    return low in _YES or low == t(lang, "setup_yes").strip().lower()


def _is_no(text: str, lang: str) -> bool:
    low = text.strip().lower()
    return low in _NO or low == t(lang, "setup_no").strip().lower()


async def maybe_start_setup(update: Update, context: ContextTypes.DEFAULT_TYPE) -> bool:
    """Begin the wizard for a pending owner. False for everyone else."""
    from backend.bot.handlers.access import actor_of

    actor = await actor_of(update, context)
    if actor is None or not _wizard_pending(actor):
        return False
    lang = lang_of(update, context)
    set_flow(context, "setup", step="panel_url")
    await edit_or_reply(update, t(lang, "setup_welcome"))
    await edit_or_reply(update, t(lang, "setup_ask_panel_url"))
    return True


async def handle_setup_text(update: Update, context: ContextTypes.DEFAULT_TYPE, actor: Actor, text: str) -> None:
    lang = lang_of(update, context)
    flow = get_flow(context) or {}
    flow.pop("kind", None)
    step = flow.get("step")

    if step == "panel_url":
        url = text.strip()
        if not (url.startswith("http://") or url.startswith("https://")):
            await edit_or_reply(update, t(lang, "setup_invalid_url"))
            return
        flow["panel_url"] = url.rstrip("/")
        flow["step"] = "acme_yn"
        set_flow(context, "setup", **flow)
        await edit_or_reply(update, t(lang, "setup_ask_acme"))
        return

    if step == "acme_yn":
        if _is_no(text, lang):
            _finish(flow, acme=False)
            clear_flow(context)
            await edit_or_reply(update, t(lang, "setup_done"))
            return
        if not _is_yes(text, lang):
            await edit_or_reply(update, t(lang, "setup_ask_acme"))
            return
        flow["step"] = "acme_domain"
        set_flow(context, "setup", **flow)
        await edit_or_reply(update, t(lang, "setup_ask_domain"))
        return

    if step == "acme_domain":
        domain = text.strip()
        if not domain or " " in domain or "." not in domain:
            await edit_or_reply(update, t(lang, "setup_ask_domain"))
            return
        flow["acme_domain"] = domain
        flow["step"] = "acme_email"
        set_flow(context, "setup", **flow)
        await edit_or_reply(update, t(lang, "setup_ask_email"))
        return

    if step == "acme_email":
        email = text.strip()
        if "@" not in email or " " in email:
            await edit_or_reply(update, t(lang, "setup_invalid_email"))
            return
        flow["acme_email"] = email
        _finish(flow, acme=True)
        clear_flow(context)
        await edit_or_reply(update, t(lang, "setup_done"))
        return

    clear_flow(context)
    await edit_or_reply(update, t(lang, "setup_done"))


def _finish(flow: dict, *, acme: bool) -> None:
    values: dict = {
        "panel_url": flow.get("panel_url"),
        "bot_owner_setup_complete": True,
    }
    if acme:
        values["acme_domain"] = flow.get("acme_domain")
        values["acme_email"] = flow.get("acme_email")
        values["cert_method"] = "letsencrypt"
    _persist(values)


__all__ = ["handle_setup_text", "maybe_start_setup"]
