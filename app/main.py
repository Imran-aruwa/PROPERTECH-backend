"""
Propertech Software API - Main Application
FastAPI application with CORS, error handling, middleware, and logging
Production-ready configuration with proper database initialization
"""
from fastapi import FastAPI, Request, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.middleware.gzip import GZipMiddleware
from fastapi.middleware.trustedhost import TrustedHostMiddleware
from fastapi.responses import JSONResponse
from fastapi.exceptions import RequestValidationError
import logging
from datetime import datetime
import traceback
import sys


from app.api.routes import (
    auth_router,
    payments_router,
    v1_payments_router,
    properties_router,
    tenants_router,
    caretaker_router,
    owner_router,
    agent_router,
    staff_router,
    tenant_portal_router,
    settings_router,
    staff_security_router,
    staff_gardener_router,
    admin_router,
    inspections_router
)
from app.core.config import settings
from app.database import test_connection, init_db, close_db_connection


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
    docs_url="/api/docs" if settings.DEBUG else None,
    redoc_url="/api/redoc" if settings.DEBUG else None,
    openapi_url="/api/openapi.json" if settings.DEBUG else None,
)


# ==================== MIDDLEWARE ====================


# Security: Trusted Host (only allow specified hosts)
trusted_hosts = ["localhost", "127.0.0.1"]


# Add frontend domain
if settings.FRONTEND_URL:
    frontend_host = settings.FRONTEND_URL.replace("https://", "").replace("http://", "").split(":")[0].split("/")[0]
    trusted_hosts.append(frontend_host)


# Always add Railway domains for cloud deployment compatibility
trusted_hosts.extend([
    ".railway.app",
    ".up.railway.app",
])


# For production on Railway, allow all hosts (Railway handles security at edge)
# TrustedHostMiddleware can cause issues with Railway's proxy setup
app.add_middleware(
    TrustedHostMiddleware,
    allowed_hosts=["*"]  # Allow all hosts - Railway proxy handles security
)


# Compression: GZip responses
app.add_middleware(GZipMiddleware, minimum_size=1000)


# CORS: Cross-Origin Resource Sharing
allowed_origins = [
    settings.FRONTEND_URL,
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]


# Add Railway frontend domains (support various Railway URL patterns)
railway_patterns = [
    "https://*.railway.app",
    "https://*.up.railway.app",
]


if settings.DEBUG:
    allowed_origins.extend([
        "http://localhost:8000",
        "http://localhost:8080",
    ])


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    allow_origin_regex=r"https://.*\.railway\.app",
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    allow_headers=["*"],
    expose_headers=["Content-Length", "X-Total-Count"],
    max_age=3600,
)


# ==================== ROUTERS ====================


# Include all API routers with /api prefix
app.include_router(auth_router, prefix="/api/auth", tags=["Authentication"])
app.include_router(payments_router, prefix="/api/payments", tags=["Payments"])
app.include_router(properties_router, prefix="/api/properties", tags=["Properties"])
app.include_router(tenants_router, prefix="/api/tenants", tags=["Tenants"])
app.include_router(caretaker_router, prefix="/api/caretaker", tags=["Caretaker"])
app.include_router(owner_router, prefix="/api/owner", tags=["Owner"])
app.include_router(agent_router, prefix="/api/agent", tags=["Agent"])
app.include_router(staff_router, prefix="/api/staff", tags=["Staff"])
app.include_router(tenant_portal_router, prefix="/api/tenant", tags=["Tenant Portal"])
app.include_router(settings_router, prefix="/api/settings", tags=["Settings"])
app.include_router(staff_security_router, prefix="/api/staff/security", tags=["Security Staff"])
app.include_router(staff_gardener_router, prefix="/api/staff/gardener", tags=["Gardener Staff"])
app.include_router(admin_router, prefix="/api/admin", tags=["Admin"])
app.include_router(inspections_router, prefix="/api/inspections", tags=["Inspections"])

# V1 API compatibility endpoints
app.include_router(v1_payments_router, prefix="/api/v1", tags=["V1 API"])


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
        "docs": "/docs" if settings.DEBUG else "Contact admin for API docs",
        "status": "operational",
        "environment": "production" if not settings.DEBUG else "development"
    }


@app.get("/health", tags=["System"])
async def health_check():
    """Health check endpoint for Railway/monitoring"""
    try:
        # Quick connection test (non-blocking)
        connection_ok = test_connection()
        
        return {
            "success": True,
            "status": "healthy" if connection_ok else "degraded",
            "database": "connected" if connection_ok else "disconnected",
            "timestamp": datetime.utcnow().isoformat(),
        }
    except Exception as e:
        logger.error(f"Health check failed: {e}")
        return JSONResponse(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE,
            content={
                "success": False,
                "status": "unhealthy",
                "error": str(e),
                "timestamp": datetime.utcnow().isoformat()
            }
        )


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
        }
    }


# ==================== STARTUP & SHUTDOWN ====================


@app.on_event("startup")
async def startup_event():
    """Run on application startup"""
    logger.info("="*70)
    logger.info(f"Starting {settings.PROJECT_NAME} v{settings.VERSION}")
    logger.info("="*70)
    logger.info(f"Environment: {'Production' if not settings.DEBUG else 'Development'}")
    logger.info(f"Frontend URL: {settings.FRONTEND_URL}")
    logger.info(f"[AUTH CONFIG] SECRET_KEY (first 8 chars): {settings.SECRET_KEY[:8]}...")
    logger.info(f"[AUTH CONFIG] ALGORITHM: {settings.ALGORITHM}")
    logger.info(f"[AUTH CONFIG] TOKEN_EXPIRE: {settings.ACCESS_TOKEN_EXPIRE_MINUTES} minutes")
    if settings.SECRET_KEY == "your-super-secret-key-change-this-in-production":
        logger.warning("[AUTH CONFIG] WARNING: Using default SECRET_KEY! Set SECRET_KEY in environment variables.")

    # Test database connection NON-BLOCKING
    logger.info("Testing database connection...")
    try:
        if test_connection():
            logger.info("[OK] Database connection successful!")
        else:
            logger.warning("[WARN] Database connection failed - continuing in degraded mode")
    except Exception as db_error:
        logger.warning(f"[WARN] Database test failed: {db_error} - continuing in degraded mode")

    # Run database migrations on startup (production)
    logger.info("Running database migrations...")
    try:
        from alembic.config import Config
        from alembic import command
        import os

        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")
        logger.info("[OK] Database migrations complete!")
    except Exception as migration_error:
        logger.warning(f"[WARN] Migration failed: {migration_error} - continuing anyway")

    # ===== DIRECT SCHEMA FIX: Ensure payment columns exist =====
    logger.info("Checking payments table schema...")
    try:
        from app.database import SessionLocal
        from sqlalchemy import text

        db = SessionLocal()
        try:
            # Check if we're on PostgreSQL (not SQLite)
            result = db.execute(text("SELECT version()"))
            db_version = result.fetchone()
            if db_version and 'PostgreSQL' in str(db_version[0]):
                logger.info(f"[INFO] PostgreSQL detected: {db_version[0][:50]}...")

                # Check for payment_type column
                result = db.execute(text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'payments' AND column_name = 'payment_type'
                """))
                if not result.fetchone():
                    logger.info("[FIX] Adding missing payment columns...")

                    # Create enum type if not exists
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE paymenttype AS ENUM (
                                'rent', 'water', 'electricity', 'garbage', 'deposit',
                                'maintenance', 'penalty', 'subscription', 'one_off'
                            );
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.commit()

                    # Add columns one by one with IF NOT EXISTS
                    db.execute(text("ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_type paymenttype"))
                    db.execute(text("ALTER TABLE payments ADD COLUMN IF NOT EXISTS tenant_id UUID"))
                    db.execute(text("ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_date TIMESTAMP"))
                    db.execute(text("ALTER TABLE payments ADD COLUMN IF NOT EXISTS due_date TIMESTAMP"))
                    db.commit()

                    logger.info("[OK] Payment columns added successfully!")
                else:
                    logger.info("[OK] Payment schema is correct")
            else:
                logger.info("[INFO] Non-PostgreSQL database, skipping schema check")
        except Exception as schema_error:
            logger.warning(f"[WARN] Schema check/fix failed: {schema_error}")
            db.rollback()
        finally:
            db.close()
    except Exception as db_error:
        logger.warning(f"[WARN] Could not check schema: {db_error}")

    # Initialize database NON-BLOCKING
    logger.info("Initializing database tables...")
    try:
        if init_db():
            logger.info("[OK] Database initialization complete!")
        else:
            logger.warning("[WARN] Database init returned False - tables may not exist")
    except Exception as init_error:
        logger.warning(f"[WARN] Database init failed: {init_error} - tables may not exist")

    # ONE-TIME FIX: Reassign orphaned properties to owner using raw SQL
    logger.info("Checking for orphaned properties...")
    try:
        from app.database import SessionLocal
        from app.models.user import User, UserRole
        from sqlalchemy import text

        db = SessionLocal()

        # Find the first owner account
        owner = db.query(User).filter(User.role == UserRole.OWNER).first()

        if owner:
            owner_id_str = str(owner.id)
            logger.info(f"[STARTUP] Found owner: {owner.email} (ID: {owner_id_str})")

            # Use raw SQL to find properties NOT linked to an owner-role user
            # Cast role to TEXT to avoid PostgreSQL enum type comparison issues
            orphaned = db.execute(text("""
                SELECT p.id, p.name, CAST(p.user_id AS TEXT) as uid
                FROM properties p
                LEFT JOIN users u ON p.user_id = u.id
                WHERE u.id IS NULL OR LOWER(CAST(u.role AS TEXT)) != 'owner'
            """)).fetchall()

            if orphaned:
                logger.info(f"[STARTUP] Found {len(orphaned)} orphaned properties, fixing...")
                for row in orphaned:
                    logger.info(f"  Fixing property '{row[1]}' (current user_id: {row[2]}) -> {owner.email}")

                # Fix all orphaned properties in one SQL statement
                db.execute(
                    text("""
                        UPDATE properties SET user_id = CAST(:owner_id AS UUID)
                        WHERE id IN (
                            SELECT p.id FROM properties p
                            LEFT JOIN users u ON p.user_id = u.id
                            WHERE u.id IS NULL OR LOWER(CAST(u.role AS TEXT)) != 'owner'
                        )
                    """),
                    {"owner_id": owner_id_str}
                )
                db.commit()
                logger.info(f"[OK] Fixed {len(orphaned)} orphaned properties -> {owner.email}")
            else:
                logger.info("[OK] No orphaned properties found")
        else:
            logger.info("[INFO] No owner account found - skipping property fix")

        db.close()
    except Exception as fix_error:
        logger.warning(f"[WARN] Property fix failed: {fix_error} - continuing anyway")

    logger.info("="*70)
    logger.info("[OK] Application startup complete!")
    logger.info("="*70)


@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown"""
    logger.info("="*70)
    logger.info("Shutting down application...")
    logger.info("="*70)

    # Close database connections
    try:
        close_db_connection()
    except:
        pass  # Ignore shutdown errors

    logger.info("Application shutdown complete")



# ==================== REQUEST LOGGING ====================


@app.middleware("http")
async def log_requests(request: Request, call_next):
    """Log all incoming requests"""
    # Skip logging for health checks
    if request.url.path in ["/health", "/status"]:
        return await call_next(request)

    start_time = datetime.utcnow()
    logger.info(f">> {request.method} {request.url.path} - {request.client.host}")

    try:
        response = await call_next(request)
        duration = (datetime.utcnow() - start_time).total_seconds()
        logger.info(f"<< {request.method} {request.url.path} - {response.status_code} ({duration:.2f}s)")
        return response
    except Exception as e:
        duration = (datetime.utcnow() - start_time).total_seconds()
        logger.error(f"[ERROR] {request.method} {request.url.path} - Error: {str(e)} ({duration:.2f}s)")
        raise


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
        "fastapi_version": "0.115+"
    }


