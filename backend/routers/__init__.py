from backend.auth.auth import router as login_router
from .users import router as user_router
from .admins import router as admin_router
from .node import router as node_router
from .setting import router as setting_router
from .mlogin import router as mlogin_router
from .activity import router as activity_router
from .security import router as security_router
from .notifications import router as notifications_router
from .metrics import router as metrics_router
from .maintenance import router as maintenance_router

all_routers = [
    login_router,
    user_router,
    setting_router,
    node_router,
    admin_router,
    mlogin_router,
    activity_router,
    security_router,
    notifications_router,
    metrics_router,
    maintenance_router,
]
