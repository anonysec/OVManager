# Copyright (c) 2026 anonysec
# SPDX-License-Identifier: MIT

from backend.auth.auth import router as login_router

from .admins import router as admin_router
from .health import router as health_router
from .maintenance import router as maintenance_router
from .node import router as node_router
from .security import router as security_router
from .setting import router as setting_router
from .telemetry import activity_router, live_router, metrics_router, notifications_router
from .tls import https_router
from .tls import router as tls_router
from .updater import router as updater_router
from .users import mlogin_router
from .users import router as user_router

all_routers = [
    login_router,
    user_router,
    setting_router,
    node_router,
    admin_router,
    health_router,
    mlogin_router,
    activity_router,
    security_router,
    notifications_router,
    metrics_router,
    maintenance_router,
    tls_router,
    https_router,
    updater_router,
    live_router,
]
