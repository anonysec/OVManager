import asyncio
from datetime import date

from fastapi import APIRouter, Depends, Request
from fastapi.concurrency import run_in_threadpool
from fastapi.responses import HTMLResponse
from fastapi.templating import Jinja2Templates
from sqlalchemy.orm import Session

from backend.config import config
from backend.db.engine import get_db
from backend.db import crud
from backend.node.task import download_ovpn_client_from_node
from backend.node.requests import NodeRequests


templates = Jinja2Templates(directory="frontend/templates")
router = APIRouter(prefix=f"/{config.SUBSCRIPTION_PATH}", tags=["Subscription"])


def _days_left(expiry_date) -> object:
    """Days remaining until expiry. Returns int (>=0 means still valid),
    or None when no expiry is set (unlimited)."""
    if not expiry_date:
        return None
    try:
        delta = expiry_date - date.today()
        return delta.days
    except TypeError:
        try:
            d = date.fromisoformat(str(expiry_date)[:10])
            return (d - date.today()).days
        except Exception:
            return None


def _used_pct(used, total) -> object:
    """Percentage of traffic used (0-100). None when unlimited (total is None)."""
    if total is None:
        return None
    used = used or 0
    if total <= 0:
        return 100 if used > 0 else 0
    return max(0, min(100, round((used / total) * 100)))


def _fmt_date(value) -> str:
    """Render a date/datetime as YYYY-MM-DD (or empty if unset)."""
    if not value:
        return "—"
    try:
        return value.strftime("%Y-%m-%d")
    except AttributeError:
        return str(value)[:10]


# Render a clean, on-brand HTML error page instead of a raw JSON
# {"detail": "..."} body (which is what clients/users see otherwise).
def sub_error_page(status_code: int, title: str, message: str) -> HTMLResponse:
    html = f"""<!DOCTYPE html>
<html lang="en" dir="ltr">
<head>
<meta charset="UTF-8">
<meta name="viewport" content="width=device-width, initial-scale=1.0">
<title>{title}</title>
<style>
  :root {{ --bg:#0f172a; --surface:#1e293b; --text:#f8fafc; --muted:#94a3b8; --border:#334155; --orange:#ea7e20; }}
  * {{ box-sizing:border-box; margin:0; padding:0; }}
  body {{ font-family:'Plus Jakarta Sans',system-ui,sans-serif; background:var(--bg); color:var(--text);
         min-height:100vh; display:flex; align-items:center; justify-content:center; padding:20px; }}
  .card {{ width:100%; max-width:420px; background:var(--surface); border:1px solid var(--border);
          border-radius:24px; padding:32px 28px; text-align:center; box-shadow:0 20px 25px -5px rgba(0,0,0,.3); }}
  .badge {{ display:inline-flex; align-items:center; gap:8px; padding:6px 16px; border-radius:50px;
           background:rgba(239,68,68,.12); color:#ef4444; border:1px solid rgba(239,68,68,.25);
           font-weight:600; font-size:.85rem; margin-bottom:16px; }}
  h2 {{ font-size:1.3rem; margin-bottom:10px; }}
  p {{ color:var(--muted); font-size:.92rem; line-height:1.5; }}
  .ovpn {{ color:var(--orange); font-weight:700; }}
</style>
</head>
<body>
  <div class="card">
    <div class="badge">● {title}</div>
    <h2>{message}</h2>
    <p>This is an <span class="ovpn">OpenVPN</span> panel. To connect, download the <b>.ovpn</b> config
       from your provider's dashboard (per-node <b>Get Config</b>) and import it into an OpenVPN client.
       OpenVPN does not use HTTP subscription links.</p>
  </div>
</body>
</html>"""
    return HTMLResponse(content=html, status_code=status_code)


@router.get("/{uuid}")
async def get_subscription(
    request: Request,
    uuid: str,
    db: Session = Depends(get_db),
):
    user = crud.get_user_by_uuid(db, uuid)
    if not user:
        return sub_error_page(404, "Not Found", "This subscription link is invalid or the user no longer exists.")
    used = user.used or 0
    # Evaluate expiry BEFORE active state: when a user's subscription expires
    # the daily cron flips is_active to False, so we must surface "Expired"
    # distinctly from a manually disabled account ("Account Disabled").
    if user.expiry_date and user.expiry_date < date.today():
        return sub_error_page(403, "Expired", "This subscription has expired. Contact your administrator to extend it.")
    if not bool(user.is_active):
        return sub_error_page(403, "Account Disabled", "This user account is currently disabled. Contact your administrator to reactivate it.")
    if user.total is not None and used >= user.total:
        return sub_error_page(403, "Traffic Limit Reached", "This user has used all allocated traffic. Contact your administrator to increase the limit.")
    nodes = [n for n in crud.get_all_nodes(db) if n.status]
    ovpn_download_links = {}

    # check_node() is blocking (requests); run all nodes concurrently in a
    # threadpool so one slow/unreachable node can't block the event loop or
    # stall the whole subscription page.
    async def is_up(node):
        try:
            return await run_in_threadpool(
                NodeRequests(
                    address=node.address, port=node.port, api_key=node.key
                ).check_node
            )
        except Exception:
            return False

    results = await asyncio.gather(*[is_up(n) for n in nodes]) if nodes else []
    for node, up in zip(nodes, results):
        if not up:
            continue
        ovpn_download_links[node.name] = str(
            request.url_for("download_ovpn", uuid=uuid, node_name=node.name)
        )

    return templates.TemplateResponse(
        "subscription.html",
        {
            "request": request,
            "name": user.name,
            "expiry_date": _fmt_date(user.expiry_date),
            "days_left": _days_left(user.expiry_date),
            "used_pct": _used_pct(user.used, user.total),
            "total": user.total,
            "used": user.used,
            "is_active": user.is_active,
            "ovpn_download_links": ovpn_download_links,
        },
    )


@router.get("/download/{uuid}/{node_name}")
async def download_ovpn(
    uuid: str,
    node_name: str,
    db: Session = Depends(get_db),
):
    user = crud.get_user_by_uuid(db, uuid)
    if not user:
        return sub_error_page(404, "Not Found", "This subscription link is invalid or the user no longer exists.")
    used = user.used or 0
    # Evaluate expiry BEFORE active state: when a user's subscription expires
    # the daily cron flips is_active to False, so we must surface "Expired"
    # distinctly from a manually disabled account ("Account Disabled").
    if user.expiry_date and user.expiry_date < date.today():
        return sub_error_page(403, "Expired", "This subscription has expired. Contact your administrator to extend it.")
    if not bool(user.is_active):
        return sub_error_page(403, "Account Disabled", "This user account is currently disabled. Contact your administrator to reactivate it.")
    if user.total is not None and used >= user.total:
        return sub_error_page(403, "Traffic Limit Reached", "This user has used all allocated traffic. Contact your administrator to increase the limit.")
    node_obj = crud.get_node_by_name(db, node_name)
    if not node_obj:
        return sub_error_page(404, "Not Found", "The requested node was not found.")
    response = await download_ovpn_client_from_node(user.uuid, node_obj.id, db)
    if not response:
        return sub_error_page(404, "Not Found", "The configuration file could not be generated.")
    return response
