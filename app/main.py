"""
Propertech Software API - Main Application
FastAPI application with CORS, error handling, middleware, and logging
Production-ready configuration
"""
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZIPMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import logging
from datetime import datetime
import traceback

from app.api.routes import (
    auth_router,
    payments_router,
    properties_router,
    tenants_router,
    caretaker_router,
    owner_router,
    agent_router,
    staff_router
)
from app.core.config import settings

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger(__name__)

# Initialize FastAPI app
app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    description="Propertech Software - Complete Property Management System with Role-Based Portals",
    docs_url="/docs",
    redoc_url="/redoc",
    openapi_url="/openapi.json"
)

# ==================== MIDDLEWARE ====================

# Security: Trusted Host (only allow specified hosts)
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=[
        settings.FRONTEND_URL.replace("https://", "").replace("http://", ""),
        "localhost",
        "127.0.0.1",
        "*.propertechsoftware.com"
    ]
)

# Compression: GZip responses
app.add_middleware(GZIPMiddleware, minimum_size=1000)

# CORS: Cross-Origin Resource Sharing
allowed_origins = [
    settings.FRONTEND_URL,
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]

if settings.DEBUG:
    allowed_origins.extend([
        "http://localhost:8000",
        "http://localhost:8080",
    ])

app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS"],
    allow_headers=[
        "Content-Type",
        "Authorization",
        "X-CSRF-Token",
        "X-Requested-With",
        "Accept",
        "Origin",
    ],
    expose_headers=["Content-Length", "X-Total-Count"],
    max_age=3600,  # Cache preflight requests for 1 hour
)

# ==================== ROUTERS ====================

# Include all API routers with prefixes
app.include_router(auth_router, prefix="/auth", tags=["Authentication"])
app.include_router(payments_router, prefix="/payments", tags=["Payments"])
app.include_router(properties_router, prefix="/properties", tags=["Properties"])
app.include_router(tenants_router, prefix="/tenants", tags=["Tenants"])
app.include_router(caretaker_router, prefix="/caretaker", tags=["Caretaker"])
app.include_router(owner_router, prefix="/owner", tags=["Owner"])
app.include_router(agent_router, prefix="/agent", tags=["Agent"])
app.include_router(staff_router, prefix="/staff", tags=["Staff"])

# ==================== ERROR HANDLERS ====================

@app.exception_handler(RequestValidationError)
async def validation_exception_handler(request: Request, exc: RequestValidationError):
    """Handle validation errors with detailed response"""
    logger.warning(f"Validation error on {request.url}: {exc}")
    return JSONResponse(
        status_code=status.HTTP_422_UNPROCESSABLE_ENTITY,
        content={
            "success": False,
            "detail": "Validation error",
            "errors": exc.errors()
        }
    )


@app.exception_handler(Exception)
async def general_exception_handler(request: Request, exc: Exception):
    """Handle all unhandled exceptions"""
    logger.error(f"Unhandled exception: {exc}\n{traceback.format_exc()}")
    
    # Don't expose internal errors in production
    error_message = str(exc) if settings.DEBUG else "Internal server error"
    
    return JSONResponse(
        status_code=status.HTTP_500_INTERNAL_SERVER_ERROR,
        content={
            "success": False,
            "detail": error_message,
            "timestamp": datetime.utcnow().isoformat()
        }
    )

# ==================== HEALTH & STATUS ENDPOINTS ====================

@app.get("/", tags=["System"])
async def root():
    """Root endpoint - API information"""
    return {
        "success": True,
        "message": "Welcome to Propertech Software API",
        "app_name": settings.PROJECT_NAME,
        "version": settings.VERSION,
        "docs": "/docs",
        "redoc": "/redoc",
        "openapi": "/openapi.json",
        "status": "operational",
        "environment": "production" if not settings.DEBUG else "development"
    }


@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint"""
    return {
        "success": True,
        "status": "healthy",
        "timestamp": datetime.utcnow().isoformat(),
        "environment": settings.PROJECT_NAME,
        "version": settings.VERSION
    }


@app.get("/status", tags=["System"])
async def status_check():
    """Detailed status check"""
    return {
        "success": True,
        "status": "operational",
        "timestamp": datetime.utcnow().isoformat(),
        "service": {
            "name": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "environment": "production" if not settings.DEBUG else "development",
            "debug": settings.DEBUG
        },
        "features": {
            "authentication": "enabled",
            "payments": "enabled (Paystack)",
            "role_based_access": "enabled",
            "audit_logging": "enabled"
        },
        "api_endpoints": {
            "auth": "/auth",
            "payments": "/payments",
            "properties": "/properties",
            "tenants": "/tenants",
            "caretaker": "/caretaker",
            "owner": "/owner",
            "agent": "/agent",
            "staff": "/staff"
        }
    }

# ==================== STARTUP & SHUTDOWN ====================

@app.on_event("startup")
async def startup_event():
    """Run on application startup"""
    logger.info(f"Starting {settings.PROJECT_NAME} v{settings.VERSION}")
    logger.info(f"Environment: {'Production' if not settings.DEBUG else 'Development'}")
    logger.info(f"Database: {settings.DATABASE_URL}")
    logger.info(f"CORS Origins: {allowed_origins}")
    logger.info("✅ Application startup complete")


@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown"""
    logger.info("🛑 Application shutdown")

# ==================== LIFESPAN EVENTS (Alternative to events) ====================

# Uncomment to use lifespan context manager instead of events
# from contextlib import asynccontextmanager

# @asynccontextmanager
# async def lifespan(app: FastAPI):
#     # Startup
#     logger.info(f"Starting {settings.PROJECT_NAME}")
#     yield
#     # Shutdown
#     logger.info("Shutting down")

# app = FastAPI(lifespan=lifespan)

# ==================== REQUEST LOGGING ====================

@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests"""
    # Skip logging for health checks
    if request.url.path in ["/health", "/status"]:
        return await call_next(request)
    
    logger.info(f"📨 {request.method} {request.url.path} - {request.client.host}")
    
    try:
        response = await call_next(request)
        logger.info(f"✅ {request.method} {request.url.path} - {response.status_code}")
        return response
    except Exception as e:
        logger.error(f"❌ {request.method} {request.url.path} - Error: {str(e)}")
        raise

# ==================== API DOCUMENTATION ====================

# Custom OpenAPI schema
def custom_openapi():
    """Custom OpenAPI schema with additional metadata"""
    if app.openapi_schema:
        return app.openapi_schema
    
    openapi_schema = {
        "openapi": "3.0.2",
        "info": {
            "title": settings.PROJECT_NAME,
            "version": settings.VERSION,
            "description": "Complete Property Management System with Role-Based Portals",
            "contact": {
                "name": "PropertyTech Support",
                "email": "support@propertechsoftware.com",
                "url": "https://propertechsoftware.com"
            },
            "license": {
                "name": "All Rights Reserved",
                "url": "https://propertechsoftware.com"
            }
        },
        "servers": [
            {
                "url": "https://api.propertechsoftware.com",
                "description": "Production Server"
            },
            {
                "url": "http://localhost:8000",
                "description": "Development Server"
            }
        ],
        "paths": app.openapi_schema.get("paths", {}),
        "components": app.openapi_schema.get("components", {}),
        "tags": [
            {
                "name": "Authentication",
                "description": "User registration, login, and token management"
            },
            {
                "name": "Payments",
                "description": "Payment processing via Paystack"
            },
            {
                "name": "Properties",
                "description": "Property and unit management"
            },
            {
                "name": "Tenants",
                "description": "Tenant portal and management"
            },
            {
                "name": "Caretaker",
                "description": "Caretaker portal operations"
            },
            {
                "name": "Owner",
                "description": "Owner portal and analytics"
            },
            {
                "name": "Agent",
                "description": "Agent portal and commission tracking"
            },
            {
                "name": "Staff",
                "description": "Staff management and operations"
            },
            {
                "name": "System",
                "description": "System health and status endpoints"
            }
        ]
    }
    
    app.openapi_schema = openapi_schema
    return app.openapi_schema


app.openapi = custom_openapi

# ==================== VERSION INFO ====================

@app.get("/api/version", tags=["System"])
async def get_version():
    """Get API version information"""
    return {
        "success": True,
        "api_version": settings.VERSION,
        "app_name": settings.PROJECT_NAME,
        "build_date": "2025-01-01",
        "python_version": "3.11+",
        "fastapi_version": "0.115.12"
    }

# ==================== Application Export ====================
# For use with uvicorn: uvicorn app.main:app --reload
if __name__ == "__main__":
    import uvicorn
    
    uvicorn.run(
        "app.main:app",
        host=settings.HOST,
        port=settings.PORT,
        reload=settings.RELOAD,
        log_level=settings.LOG_LEVEL.lower()
    )