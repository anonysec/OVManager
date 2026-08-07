import re
import time
import logging
from datetime import date, timedelta
from telegram import Update, InlineKeyboardButton, InlineKeyboardMarkup
from telegram.ext import ContextTypes
from bot.ovmanager import OVManager
from bot.config import config

logger = logging.getLogger(__name__)
api = OVManager()

# {user_id: (state_str, timestamp)} — waiting for plain-text input
USER_STATES = {}
STATE_TTL = 300  # 5 minutes
_REQUEST_COUNTER = 0
_CLEANUP_REQUEST_INTERVAL = 10  # Cleanup every 10 requests

# Admin cache: { "data": list[dict], "ts": float }
_ADMIN_CACHE: dict = {"data": None, "ts": 0.0}
_ADMIN_CACHE_TTL = 60  # seconds


def _cleanup_states():
    """Remove stale USER_STATES entries older than STATE_TTL seconds."""
    now = time.time()
    stale = [uid for uid, (_, ts) in USER_STATES.items() if now - ts > STATE_TTL]
    for uid in stale:
        del USER_STATES[uid]


def _set_state(uid, state):
    _cleanup_states()
    USER_STATES[uid] = (state, time.time())


def _pop_state(uid):
    _cleanup_states()
    entry = USER_STATES.pop(uid, None)
    return entry[0] if entry else None


def _get_plans():
    """Return the current plan definitions from bot config (env-overridable)."""
    return config.plans if config else _DEFAULT_PLANS


_DEFAULT_PLANS = {
    "bronze": (30, 200, 1),
    "silver": (30, 200, 2),
    "gold": (0, 0, 0),
}

# Rate limiting: {user_id: [timestamps]}
_CMD_RATES: dict[int, list[float]] = {}
_CMD_RATE_LIMIT = 5  # max commands
_CMD_RATE_WINDOW = 60  # seconds
_CMD_RATE_CLEANUP_INTERVAL = 300  # cleanup every 5 min
_last_rate_cleanup = 0.0


def _periodic_cleanup():
    """Run periodic cleanup for states and rate limit buckets."""
    global _REQUEST_COUNTER, _last_rate_cleanup
    _REQUEST_COUNTER += 1
    if _REQUEST_COUNTER >= _CLEANUP_REQUEST_INTERVAL:
        _REQUEST_COUNTER = 0
        _cleanup_states()
        now = time.time()
        for uid in list(_CMD_RATES.keys()):
            _CMD_RATES[uid] = [t for t in _CMD_RATES[uid] if now - t < _CMD_RATE_WINDOW]
            if not _CMD_RATES[uid]:
                del _CMD_RATES[uid]
        _last_rate_cleanup = now


def _check_rate_limit(user_id: int) -> bool:
    """Returns True if within rate limit, False if exceeded."""
    global _last_rate_cleanup
    now = time.time()
    if now - _last_rate_cleanup > _CMD_RATE_CLEANUP_INTERVAL:
        for uid in list(_CMD_RATES.keys()):
            _CMD_RATES[uid] = [t for t in _CMD_RATES[uid] if now - t < _CMD_RATE_WINDOW]
            if not _CMD_RATES[uid]:
                del _CMD_RATES[uid]
        _last_rate_cleanup = now
    _CMD_RATES.setdefault(user_id, [])
    _CMD_RATES[user_id] = [t for t in _CMD_RATES[user_id] if now - t < _CMD_RATE_WINDOW]
    if len(_CMD_RATES[user_id]) >= _CMD_RATE_LIMIT:
        return False
    _CMD_RATES[user_id].append(now)
    return True


def _safe_handler(func):
    """Decorator for error-handling in bot handlers."""
    async def wrapper(update: Update, context: ContextTypes.DEFAULT_TYPE):
        try:
            return await func(update, context)
        except Exception as e:
            logger.exception("Handler error: %s", e)
            if update.effective_chat:
                await update.message.reply_text("❌ An error occurred. Contact admin.")
    return wrapper


HELP_TEXT = """🤖 <b>OVManager Bot</b>

<b>Users</b>
<code>/n</code> or <code>/new</code> &lt;name&gt; [days] [traffic] [users]
<code>/u</code> or <code>/users</code> [name]
<code>/r</code> or <code>/renew</code> &lt;name&gt; [days] [traffic] [users]
<code>/e</code> or <code>/edit</code> &lt;name&gt; [days] [traffic] [users]

<b>System</b>
<code>/s</code> or <code>/status</code>
<code>/help</code>

0 = unlimited | [] = optional"""

USERS_PER_PAGE = 10


def _parse_args(text: str):
    parts = text.strip().split()
    cmd = parts[0].lstrip("/").lower() if parts else ""
    if cmd in ("n", "new"):
        mode = "new"
    elif cmd in ("s", "status"):
        mode = "status"
    elif cmd in ("u", "users"):
        mode = "users"
    elif cmd in ("r", "renew"):
        mode = "renew"
    elif cmd in ("e", "edit"):
        mode = "edit"
    elif cmd in ("help",):
        mode = "help"
    else:
        mode = None
    args = parts[1:] if len(parts) > 1 else []
    return mode, args


def _fmt_bytes(b):
    if b is None:
        return "♾️"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if b < 1024:
            return f"{b:.1f} {unit}"
        b /= 1024
    return f"{b:.1f} PB"


def _days_remaining(expiry):
    if not expiry:
        return None, "♾️ Unlimited"
    try:
        exp = date.fromisoformat(expiry) if isinstance(expiry, str) else expiry
    except (ValueError, TypeError):
        return None, "❓ Unknown"
    delta = (exp - date.today()).days
    if delta < 0:
        return delta, f"❌ Expired {abs(delta)}d ago"
    elif delta == 0:
        return delta, "🔥 Expires today"
    elif delta <= 3:
        return delta, f"⚠️ {delta}d left"
    elif delta <= 14:
        return delta, f"⚡ {delta}d left"
    else:
        return delta, f"🔋 {delta}d left"


async def _get_admins_cached() -> list:
    """Return cached admin list, refreshing from the API if the cache is stale.

    The admin list rarely changes, so a 60s TTL avoids a panel API
    round-trip on every single message without meaningfully delaying
    permission changes.
    """
    global _ADMIN_CACHE
    now = time.time()
    if _ADMIN_CACHE["data"] is not None and now - _ADMIN_CACHE["ts"] < _ADMIN_CACHE_TTL:
        return _ADMIN_CACHE["data"]
    admins = await api.get_admins()
    _ADMIN_CACHE = {"data": admins, "ts": now}
    return admins


def _clear_admin_cache():
    """Invalidate the cached admin list (e.g. after an admin change)."""
    global _ADMIN_CACHE
    _ADMIN_CACHE = {"data": None, "ts": 0.0}


async def _auth(update: Update) -> bool:
    uid = update.effective_user.id
    admins = await _get_admins_cached()
    for a in admins:
        if a.get("telegram_id") == uid:
            return True
    settings = await api.get_settings()
    if settings.get("owner_telegram_id") == uid:
        return True
    return False


def _is_owner(uid: int) -> bool:
    s = api._get_settings_from_db()
    return s.get("owner_telegram_id") == uid


def _hub_kb():
    return [
        [InlineKeyboardButton("➕ New", callback_data="hub_new"),
         InlineKeyboardButton("🖥️ Status", callback_data="hub_status")],
        [InlineKeyboardButton("👥 Users", callback_data="users_page_0"),
         InlineKeyboardButton("❓ Help", callback_data="hub_help")],
    ]


async def _hub(update: Update):
    await update.message.reply_text("🏠 OVManager Bot", reply_markup=InlineKeyboardMarkup(_hub_kb()))
