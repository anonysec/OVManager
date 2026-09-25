# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

"""Daily Telegram alerts for users who are expiring or out of traffic.

The panel process sends these messages itself over the Telegram HTTPS API
(``sendMessage``). That is safe to do while the bot subprocess is polling:
Telegram treats an outbound send and an inbound ``getUpdates`` long poll as
independent requests, so neither blocks the other.

Design notes
------------
* ``send_telegram`` reads ``Settings`` on its own and no-ops when the bot is
  disabled, the token is missing or cannot be decrypted, or no owner id is
  set. It never raises.
* ``run_daily_alerts`` is the scheduler entry point. It sends at most one
  summary per calendar day (module-level ``_last_sent_day`` guard). The guard
  lives in memory only, so restarting the panel forgets it and the summary
  **may be sent a second time that day** — an accepted trade-off that avoids
  adding a bookkeeping table for a single daily message.
* Nothing here ever logs the bot token, the request URL, or response bodies:
  a ``requests`` exception string embeds the URL (which carries the token),
  so failures are logged by exception type only.
"""

from __future__ import annotations

from datetime import UTC, date, datetime, timedelta
from html import escape

import requests

from backend.db import crud
from backend.db.engine import SessionLocal
from backend.logger import logger

#: Telegram sendMessage endpoint; ``{token}`` is filled in locally and never logged.
TELEGRAM_API_TEMPLATE = "https://api.telegram.org/bot{token}/sendMessage"
#: How many days ahead an expiry starts being reported.
EXPIRY_WINDOW_DAYS = 3
#: Keep the scheduler quiet: a hung Telegram call must not pile up.
HTTP_TIMEOUT_SECONDS = 10

#: Last calendar day (UTC) a summary was sent. ``None`` means "not yet today".
_last_sent_day: date | None = None


def _decrypt_bot_token(stored: str | None) -> str | None:
    """Return the bot token as stored, or ``None`` when unusable.

    At-rest encryption was removed in 1.0.5. A legacy ``enc:`` row cannot be
    read back without the retired key, so it is refused: ciphertext is never
    sent to Telegram as a token. Same fail-closed rule as crud.decrypt_bot_token.
    """
    if not stored:
        return None
    if str(stored).startswith("enc:"):
        logger.warning("Bot token is still encrypted (re-save it in Settings → Bot) — skipping alert")
        return None
    return stored


def send_telegram(text: str, db=None) -> bool:
    """Send one HTML-escaped message to the configured owner. Never raises.

    Returns ``True`` only when Telegram accepted the message. Silently returns
    ``False`` when the bot is disabled, no token is stored/can be decrypted,
    or no owner id is set. ``db`` is optional so callers that already hold a
    session (the daily job) can avoid opening another one.
    """
    own_session = db is None
    session = None
    try:
        session = db or SessionLocal()
        settings = crud.get_settings(session)
        if not bool(getattr(settings, "bot_enabled", False)):
            return False
        owner_id = getattr(settings, "owner_telegram_id", None)
        if not owner_id:
            return False
        token = _decrypt_bot_token(getattr(settings, "bot_token", None))
        if not token:
            return False

        try:
            response = requests.post(
                TELEGRAM_API_TEMPLATE.format(token=token),
                json={
                    "chat_id": owner_id,
                    "text": escape(text),
                    "parse_mode": "HTML",
                },
                timeout=HTTP_TIMEOUT_SECONDS,
            )
        except Exception as exc:
            # Exception text can embed the URL (and therefore the token).
            logger.error("Telegram sendMessage request failed (%s)", type(exc).__name__)
            return False

        if not response.ok:
            logger.warning("Telegram sendMessage returned HTTP %s", response.status_code)
            return False
        return True
    except Exception as exc:
        logger.error("Telegram alert skipped (%s)", type(exc).__name__)
        return False
    finally:
        if own_session and session is not None:
            session.close()


def collect_alerts(db) -> dict[str, list[str]]:
    """Group user names by the alert they belong to.

    * ``expiring`` — active users whose ``expiry_date`` falls between today
      and today + :data:`EXPIRY_WINDOW_DAYS` (both inclusive).
    * ``out_of_traffic`` — active users with a real quota (``total`` is not
      NULL) and ``used >= total``. ``total = NULL`` means unlimited and is
      skipped.
    * ``disabled_expiry`` / ``disabled_traffic`` — already-disabled users
      whose ``is_active`` flag was flipped because they expired or ran out
      of traffic. Reported separately because they need no action today.

    Names are sorted so the daily message is stable. Missing/never-expiring
    expiry values (``None`` or a far-future placeholder) simply never match.
    """
    today = datetime.now(UTC).date()
    deadline = today + timedelta(days=EXPIRY_WINDOW_DAYS)

    expiring: list[str] = []
    out_of_traffic: list[str] = []
    disabled_expiry: list[str] = []
    disabled_traffic: list[str] = []

    for user in crud.get_all_users(db):
        expiry = getattr(user, "expiry_date", None)
        total = getattr(user, "total", None)
        used = getattr(user, "used", None) or 0

        expired = expiry is not None and expiry < today
        over_quota = total is not None and used >= total

        if not getattr(user, "is_active", False):
            if expired:
                disabled_expiry.append(user.name)
            elif over_quota:
                disabled_traffic.append(user.name)
            continue

        if expiry is not None and today <= expiry <= deadline:
            expiring.append(user.name)
        if over_quota:
            out_of_traffic.append(user.name)

    return {
        "expiring": sorted(expiring),
        "out_of_traffic": sorted(out_of_traffic),
        "disabled_expiry": sorted(disabled_expiry),
        "disabled_traffic": sorted(disabled_traffic),
    }


def _user_segment(names: list[str], singular_verb: str, plural_verb: str, suffix: str = "") -> str:
    """Build ``"3 users expire within 3 days: a, b, c"`` for one category."""
    count = len(names)
    noun = "user" if count == 1 else "users"
    verb = singular_verb if count == 1 else plural_verb
    head = f"{count} {noun} {verb}"
    if suffix:
        head = f"{head} {suffix}"
    return f"{head}: {', '.join(names)}"


def build_summary(alerts: dict[str, list[str]], *, notify_expiry: bool = True, notify_traffic: bool = True) -> str:
    """Combine the alert groups into one compact line, honoring the toggles.

    Expiry groups are gated by ``notify_expiry``, traffic groups by
    ``notify_traffic``. Returns an empty string when nothing is enabled or
    there is nothing to report.
    """
    segments: list[str] = []

    expiring = alerts.get("expiring") or []
    if notify_expiry and expiring:
        segments.append(_user_segment(expiring, "expires", "expire", "within 3 days"))

    out_of_traffic = alerts.get("out_of_traffic") or []
    if notify_traffic and out_of_traffic:
        segments.append(_user_segment(out_of_traffic, "is out of traffic", "are out of traffic"))

    disabled: list[str] = []
    if notify_expiry:
        disabled.extend(alerts.get("disabled_expiry") or [])
    if notify_traffic:
        disabled.extend(alerts.get("disabled_traffic") or [])
    if disabled:
        segments.append(_user_segment(sorted(set(disabled)), "is disabled due to limits", "are disabled due to limits"))

    return " · ".join(segments)


def run_daily_alerts() -> bool:
    """Send the daily summary once per calendar day. Never raises.

    Returns ``True`` when a message was sent. The in-memory guard remembers
    the UTC day of the last successful send, so a second scheduler run that
    day is a no-op. **A panel restart clears the guard and may resend the
    same day's summary.**
    """
    global _last_sent_day
    today = datetime.now(UTC).date()
    if _last_sent_day == today:
        return False

    session = None
    try:
        session = SessionLocal()
        settings = crud.get_settings(session)
        notify_expiry = bool(getattr(settings, "notify_expiry", True))
        notify_traffic = bool(getattr(settings, "notify_traffic", True))

        alerts = collect_alerts(session)
        text = build_summary(alerts, notify_expiry=notify_expiry, notify_traffic=notify_traffic)
        if not text:
            return False

        sent = send_telegram(text, db=session)
        if sent:
            _last_sent_day = today
            logger.info("Daily Telegram alert summary sent")
        return sent
    except Exception as exc:
        logger.error("Daily Telegram alerts failed (%s)", type(exc).__name__)
        return False
    finally:
        if session is not None:
            session.close()
