from app.api.routes.auth import router as auth_router
from app.api.routes.payments import router as payments_router, v1_router as v1_payments_router
from app.api.routes.properties import router as properties_router
from app.api.routes.tenants import router as tenants_router
from app.api.routes.caretaker import router as caretaker_router
from app.api.routes.owner import router as owner_router
from app.api.routes.agent import router as agent_router
from app.api.routes.staff import router as staff_router
from app.api.routes.tenant_portal import router as tenant_portal_router
from app.api.routes.settings import router as settings_router
from app.api.routes.staff_security import router as staff_security_router
from app.api.routes.staff_gardener import router as staff_gardener_router
from app.api.routes.admin import router as admin_router

__all__ = [
    "auth_router",
    "payments_router",
    "v1_payments_router",
    "properties_router",
    "tenants_router",
    "caretaker_router",
    "owner_router",
    "agent_router",
    "staff_router",
    "tenant_portal_router",
    "settings_router",
    "staff_security_router",
    "staff_gardener_router",
    "admin_router"
]