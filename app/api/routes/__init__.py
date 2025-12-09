from app.api.routes.auth import router as auth_router
from app.api.routes.payments import router as payments_router
from app.api.routes.properties import router as properties_router
from app.api.routes.tenants import router as tenants_router
from app.api.routes.caretaker import router as caretaker_router
from app.api.routes.owner import router as owner_router
from app.api.routes.agent import router as agent_router
from app.api.routes.staff import router as staff_router

__all__ = [
    "auth_router",
    "payments_router",
    "properties_router",
    "tenants_router",
    "caretaker_router",
    "owner_router",
    "agent_router",
    "staff_router"
]