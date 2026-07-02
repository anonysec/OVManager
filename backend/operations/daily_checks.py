import asyncio
import json

from backend.logger import logger
from backend.db import crud
from backend.db.engine import get_db
from backend.node.task import change_user_status_on_all_nodes, get_users_used_traffic


async def enforce_user_limits():
    """Disable users who are expired or exceeded traffic"""
    db = next(get_db())

    try:
        expired_users = crud.get_expired_users(db)
        exceeded_users = crud.get_users_exceeded_traffic(db)

        users_to_disable = {u.id: u for u in expired_users + exceeded_users}.values()

        for user in users_to_disable:
            user.is_active = False
            await change_user_status_on_all_nodes(uuid=user.uuid, name=user.name, status=False, db=db)
            await asyncio.sleep(0.5)

        db.commit()

    except Exception as e:
        db.rollback()
        logger.error(f"Error in users expiration check -> {e}")

    finally:
        db.close()


async def check_user_used_traffic():
    db = next(get_db())

    try:
        nodes = crud.get_all_nodes(db)

        if not nodes:
            logger.warning("No nodes found")
            return

        all_users = {u.name: u for u in crud.get_all_users(db)}

        for node in nodes:
            try:
                usage = await get_users_used_traffic(node, db=db)

                if not usage:
                    continue

                per_user_total = usage.get("users", {}) or {}
                per_user_sessions = usage.get("sessions", {}) or {}

                if not per_user_total:
                    continue

                # The node names every client "<panel_username>-<node_name>".
                # Strip exactly that node suffix instead of splitting on the
                # first "-", so usernames that themselves contain dashes
                # (e.g. "my-vpn") are matched and counted correctly.
                suffix = f"-{node.name}"

                for client_name, total_bytes in per_user_total.items():
                    if client_name.endswith(suffix):
                        clean_username = client_name[: -len(suffix)]
                    else:
                        # Fallback for legacy/unexpected names.
                        clean_username = client_name.rsplit("-", 1)[0]

                    user = all_users.get(clean_username)

                    if not user:
                        logger.warning(f"User not found: {clean_username}")
                        continue

                    # node_usage maps node_name -> {session_key: last_seen_bytes}
                    # so each session is diffed independently. This avoids
                    # double-counting when one of several simultaneous sessions
                    # disconnects (which would otherwise look like a counter
                    # reset on a summed total).
                    try:
                        node_usage = json.loads(user.node_usage or "{}")
                        if not isinstance(node_usage, dict):
                            node_usage = {}
                    except (ValueError, TypeError):
                        node_usage = {}

                    prev = node_usage.get(node.name)
                    sessions = per_user_sessions.get(client_name)

                    delta = 0
                    if isinstance(sessions, dict) and isinstance(prev, dict):
                        # Per-session diff (accurate path).
                        for skey, cur in sessions.items():
                            last = int(prev.get(skey, 0) or 0)
                            delta += (cur - last) if cur >= last else cur
                        new_state = {k: int(v) for k, v in sessions.items()}
                    elif isinstance(sessions, dict):
                        # First time we see sessions for this node: count all
                        # current bytes once, then start tracking per session.
                        # `prev` here is either absent or a legacy int total.
                        prev_int = int(prev or 0) if not isinstance(prev, dict) else 0
                        cur_total = int(sum(sessions.values()))
                        delta = cur_total - prev_int if cur_total >= prev_int else cur_total
                        new_state = {k: int(v) for k, v in sessions.items()}
                    else:
                        # Legacy fallback: node didn't send per-session data.
                        prev_int = int(prev or 0) if not isinstance(prev, dict) else 0
                        cur_total = int(total_bytes)
                        delta = cur_total - prev_int if cur_total >= prev_int else cur_total
                        new_state = cur_total

                    if delta < 0:
                        delta = 0

                    user.used = (user.used or 0) + delta
                    node_usage[node.name] = new_state
                    user.node_usage = json.dumps(node_usage)

                    logger.info(
                        f"[{clean_username}] node={node.name} "
                        f"total={int(total_bytes)} delta={delta}"
                    )

                # commit per node
                db.commit()

                logger.info(f"Traffic data committed for node {node.address}")

            except Exception as e:
                db.rollback()

                logger.error(
                    f"Error while processing node " f"{node.address} -> {e}",
                    exc_info=True,
                )

    except Exception as e:
        db.rollback()

        logger.error(f"Error in check_user_used_traffic -> {e}", exc_info=True)

    finally:
        db.close()
