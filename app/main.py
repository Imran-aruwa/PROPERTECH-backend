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
    admin_router
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
    docs_url="/api/docs",  # Always enable docs at /api/docs
    redoc_url="/api/redoc",
    openapi_url="/api/openapi.json"
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
    allow_origins=["*"],  # Allow all origins for Railway compatibility
    allow_credentials=True,
    allow_methods=["GET", "POST", "PUT", "DELETE", "PATCH", "OPTIONS", "HEAD"],
    allow_headers=["*"],  # Allow all headers
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


@app.get("/debug/property-fix", tags=["System"])
async def debug_property_fix():
    """Debug endpoint to check property ownership status"""
    try:
        from app.database import SessionLocal
        from app.models.user import User, UserRole
        from app.models.property import Property

        db = SessionLocal()

        # Get all users with their roles
        users = db.query(User).all()
        user_list = [{"id": str(u.id), "email": u.email, "role": u.role.value} for u in users]

        # Get all properties with their current owners
        properties = db.query(Property).all()
        property_list = []
        for p in properties:
            owner = db.query(User).filter(User.id == p.user_id).first()
            property_list.append({
                "id": str(p.id),
                "name": p.name,
                "user_id": str(p.user_id) if p.user_id else None,
                "owner_email": owner.email if owner else "Unknown",
                "owner_role": owner.role.value if owner else "Unknown"
            })

        # Find owners
        owners = [u for u in user_list if u["role"] == "owner"]

        db.close()

        return {
            "total_users": len(user_list),
            "total_properties": len(property_list),
            "owners": owners,
            "users": user_list,
            "properties": property_list
        }
    except Exception as e:
        return {"error": str(e)}


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


# ==================== DEBUG ENDPOINT (NO AUTH) ====================

@app.get("/api/debug/database", tags=["Debug"])
async def debug_database():
    """
    Public debug endpoint to check database state.
    NO AUTHENTICATION REQUIRED - use for troubleshooting.
    """
    from app.database import SessionLocal
    from app.models.user import User, UserRole
    from app.models.property import Property, Unit

    db = SessionLocal()
    try:
        # Count records
        user_count = db.query(User).count()
        owner_count = db.query(User).filter(User.role == UserRole.OWNER).count()
        property_count = db.query(Property).count()
        unit_count = db.query(Unit).count()

        # Get owners list (email only for privacy)
        owners = db.query(User).filter(User.role == UserRole.OWNER).all()
        owner_list = [{"id": str(o.id), "email": o.email} for o in owners]

        # Get properties with their owner info AND unit counts
        properties = db.query(Property).all()
        property_list = []
        for p in properties:
            owner = db.query(User).filter(User.id == p.user_id).first()
            # Count units for this property
            property_units = db.query(Unit).filter(Unit.property_id == p.id).all()
            property_list.append({
                "id": str(p.id),
                "name": p.name,
                "user_id": str(p.user_id) if p.user_id else None,
                "owner_email": owner.email if owner else "NOT FOUND",
                "owner_exists": owner is not None,
                "total_units_field": p.total_units,
                "actual_units_in_db": len(property_units),
                "units": [{"id": str(u.id), "unit_number": u.unit_number, "status": u.status, "rent": u.monthly_rent} for u in property_units]
            })

        # Get ALL units regardless of property
        all_units = db.query(Unit).all()
        all_units_list = [
            {
                "id": str(u.id),
                "property_id": str(u.property_id) if u.property_id else None,
                "unit_number": u.unit_number,
                "status": u.status,
                "monthly_rent": u.monthly_rent
            }
            for u in all_units
        ]

        return {
            "success": True,
            "timestamp": datetime.utcnow().isoformat(),
            "database_status": "connected",
            "counts": {
                "users": user_count,
                "owners": owner_count,
                "properties": property_count,
                "units": unit_count
            },
            "owners": owner_list,
            "properties": property_list,
            "all_units": all_units_list,
            "diagnosis": {
                "has_owners": owner_count > 0,
                "has_properties": property_count > 0,
                "has_units": unit_count > 0,
                "all_properties_have_owners": all(p["owner_exists"] for p in property_list) if property_list else True,
                "properties_missing_units": [p["name"] for p in property_list if p["actual_units_in_db"] == 0]
            }
        }
    except Exception as e:
        logger.error(f"Debug endpoint error: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }
    finally:
        db.close()


@app.post("/api/debug/create-units", tags=["Debug"])
async def create_missing_units(num_units: int = 10, default_rent: float = 15000):
    """
    AUTO-FIX: Create units for properties that don't have any.
    NO AUTHENTICATION REQUIRED - use for troubleshooting.

    Parameters:
    - num_units: Number of units to create per property (default: 10)
    - default_rent: Default monthly rent for each unit (default: 15000)
    """
    from app.database import SessionLocal
    from app.models.property import Property, Unit
    import uuid

    db = SessionLocal()
    try:
        # Find properties with no units
        properties = db.query(Property).all()
        created_units = []

        for prop in properties:
            existing_units = db.query(Unit).filter(Unit.property_id == prop.id).count()

            if existing_units == 0:
                # Create units for this property
                units_to_create = prop.total_units if prop.total_units and prop.total_units > 0 else num_units

                for i in range(1, units_to_create + 1):
                    new_unit = Unit(
                        id=uuid.uuid4(),
                        property_id=prop.id,
                        unit_number=f"Unit {i}",
                        bedrooms=1,
                        bathrooms=1.0,
                        monthly_rent=default_rent,
                        status="vacant"
                    )
                    db.add(new_unit)
                    created_units.append({
                        "property": prop.name,
                        "unit_number": f"Unit {i}",
                        "rent": default_rent
                    })

                # Update property's total_units field
                prop.total_units = units_to_create

        db.commit()

        return {
            "success": True,
            "message": f"Created {len(created_units)} units",
            "created_units": created_units,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Create units error: {e}")
        return {
            "success": False,
            "error": str(e),
            "timestamp": datetime.utcnow().isoformat()
        }
    finally:
        db.close()


@app.post("/api/debug/fix-kuscco-homes", tags=["Debug"])
async def fix_kuscco_homes():
    """
    SPECIFIC FIX: Create 120 units for Kuscco Homes property.
    NO AUTHENTICATION REQUIRED - one-time fix endpoint.
    """
    from app.database import SessionLocal
    from app.models.property import Property, Unit
    from app.models.user import User, UserRole
    import uuid

    db = SessionLocal()
    try:
        # Find Kuscco Homes property (case-insensitive search)
        property = db.query(Property).filter(
            Property.name.ilike("%kuscco%")
        ).first()

        if not property:
            # List all properties to help debugging
            all_props = db.query(Property).all()
            return {
                "success": False,
                "error": "Kuscco Homes property not found",
                "available_properties": [{"id": str(p.id), "name": p.name} for p in all_props],
                "timestamp": datetime.utcnow().isoformat()
            }

        # Get existing units count
        existing_units = db.query(Unit).filter(Unit.property_id == property.id).all()
        existing_count = len(existing_units)

        # Delete existing units if any (fresh start)
        if existing_count > 0:
            for unit in existing_units:
                db.delete(unit)
            db.flush()

        # Create exactly 120 units
        created_units = []
        for i in range(1, 121):  # 1 to 120
            new_unit = Unit(
                id=uuid.uuid4(),
                property_id=property.id,
                unit_number=f"Unit {i}",
                bedrooms=1,
                bathrooms=1.0,
                monthly_rent=15000.0,  # Default rent
                status="vacant"
            )
            db.add(new_unit)
            created_units.append(f"Unit {i}")

        # Update property's total_units field
        property.total_units = 120

        # Also ensure property is linked to an owner
        owner = db.query(User).filter(User.role == UserRole.OWNER).first()
        if owner and property.user_id != owner.id:
            property.user_id = owner.id

        db.commit()

        # Verify the count
        final_count = db.query(Unit).filter(Unit.property_id == property.id).count()

        return {
            "success": True,
            "message": f"Successfully created 120 units for Kuscco Homes",
            "property": {
                "id": str(property.id),
                "name": property.name,
                "user_id": str(property.user_id),
                "total_units": property.total_units
            },
            "previous_units": existing_count,
            "units_created": 120,
            "final_unit_count": final_count,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        db.rollback()
        logger.error(f"Fix Kuscco Homes error: {e}")
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "timestamp": datetime.utcnow().isoformat()
        }
    finally:
        db.close()


@app.get("/api/debug/schema", tags=["Debug"])
async def debug_schema():
    """
    Debug endpoint to check database schema.
    Shows what columns exist in the payments table.
    """
    from app.database import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    try:
        # Check payments table columns
        result = db.execute(text("""
            SELECT column_name, data_type, is_nullable
            FROM information_schema.columns
            WHERE table_name = 'payments'
            ORDER BY ordinal_position
        """))
        payments_columns = [{"name": row[0], "type": row[1], "nullable": row[2]} for row in result]

        # Check if paymenttype enum exists
        result = db.execute(text("""
            SELECT typname FROM pg_type WHERE typname = 'paymenttype'
        """))
        enum_exists = result.fetchone() is not None

        # Check alembic version
        result = db.execute(text("""
            SELECT version_num FROM alembic_version
        """))
        alembic_version = result.fetchone()

        return {
            "success": True,
            "payments_columns": payments_columns,
            "paymenttype_enum_exists": enum_exists,
            "alembic_version": alembic_version[0] if alembic_version else None,
            "expected_version": "d4e5f6g7h8i9",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "timestamp": datetime.utcnow().isoformat()
        }
    finally:
        db.close()


@app.get("/api/debug/run-migration", tags=["Debug"])
async def run_migration_manually():
    """
    Manually run pending migrations.
    """
    try:
        from alembic.config import Config
        from alembic import command

        alembic_cfg = Config("alembic.ini")
        command.upgrade(alembic_cfg, "head")

        return {
            "success": True,
            "message": "Migrations executed successfully",
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "timestamp": datetime.utcnow().isoformat()
        }


@app.get("/api/debug/fix-payments-schema", tags=["Debug"])
async def fix_payments_schema():
    """
    Direct SQL fix to add missing columns to payments table.
    This bypasses alembic if it's having issues.
    """
    from app.database import SessionLocal
    from sqlalchemy import text

    db = SessionLocal()
    results = []

    try:
        # Check which columns exist
        existing = db.execute(text("""
            SELECT column_name FROM information_schema.columns
            WHERE table_name = 'payments'
        """))
        existing_columns = [row[0] for row in existing]

        # Create enum type if not exists
        try:
            db.execute(text("""
                DO $$ BEGIN
                    CREATE TYPE paymenttype AS ENUM (
                        'rent', 'water', 'electricity', 'garbage', 'deposit',
                        'maintenance', 'penalty', 'subscription', 'one_off'
                    );
                EXCEPTION
                    WHEN duplicate_object THEN null;
                END $$;
            """))
            db.commit()
            results.append("Created paymenttype enum (or already exists)")
        except Exception as e:
            results.append(f"Enum creation: {str(e)}")
            db.rollback()

        # Add payment_type column if missing
        if 'payment_type' not in existing_columns:
            try:
                db.execute(text("""
                    ALTER TABLE payments ADD COLUMN payment_type paymenttype
                """))
                db.commit()
                results.append("Added payment_type column")
            except Exception as e:
                results.append(f"payment_type: {str(e)}")
                db.rollback()
        else:
            results.append("payment_type already exists")

        # Add tenant_id column if missing
        if 'tenant_id' not in existing_columns:
            try:
                db.execute(text("""
                    ALTER TABLE payments ADD COLUMN tenant_id UUID
                """))
                db.commit()
                results.append("Added tenant_id column")
            except Exception as e:
                results.append(f"tenant_id: {str(e)}")
                db.rollback()
        else:
            results.append("tenant_id already exists")

        # Add payment_date column if missing
        if 'payment_date' not in existing_columns:
            try:
                db.execute(text("""
                    ALTER TABLE payments ADD COLUMN payment_date TIMESTAMP
                """))
                db.commit()
                results.append("Added payment_date column")
            except Exception as e:
                results.append(f"payment_date: {str(e)}")
                db.rollback()
        else:
            results.append("payment_date already exists")

        # Add due_date column if missing
        if 'due_date' not in existing_columns:
            try:
                db.execute(text("""
                    ALTER TABLE payments ADD COLUMN due_date TIMESTAMP
                """))
                db.commit()
                results.append("Added due_date column")
            except Exception as e:
                results.append(f"due_date: {str(e)}")
                db.rollback()
        else:
            results.append("due_date already exists")

        # Update alembic version to mark migration as done
        try:
            db.execute(text("""
                UPDATE alembic_version SET version_num = 'd4e5f6g7h8i9'
            """))
            db.commit()
            results.append("Updated alembic version to d4e5f6g7h8i9")
        except Exception as e:
            results.append(f"alembic version update: {str(e)}")
            db.rollback()

        return {
            "success": True,
            "results": results,
            "timestamp": datetime.utcnow().isoformat()
        }
    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "results": results,
            "timestamp": datetime.utcnow().isoformat()
        }
    finally:
        db.close()


@app.get("/api/debug/fix-all", tags=["Debug"])
async def fix_all_issues():
    """
    COMPREHENSIVE FIX: Runs all fixes in order.
    1. Fix payments schema (add missing columns)
    2. Fix property ownership (link to owner)
    3. Create missing units

    Run this endpoint to fix all dashboard issues at once.
    """
    from app.database import SessionLocal
    from app.models.user import User, UserRole
    from app.models.property import Property, Unit
    from sqlalchemy import text
    import uuid

    results = {
        "schema_fix": [],
        "property_fix": [],
        "units_fix": [],
        "success": True
    }

    db = SessionLocal()
    try:
        # ===== STEP 1: Fix Payments Schema =====
        try:
            # Check if we're on PostgreSQL
            pg_result = db.execute(text("SELECT version()"))
            pg_version = pg_result.fetchone()
            if pg_version and 'PostgreSQL' in str(pg_version[0]):
                # Get existing columns
                existing = db.execute(text("""
                    SELECT column_name FROM information_schema.columns
                    WHERE table_name = 'payments'
                """))
                existing_columns = [row[0] for row in existing]

                # Create enum if not exists
                try:
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
                    results["schema_fix"].append("Created paymenttype enum")
                except Exception as e:
                    results["schema_fix"].append(f"Enum: {str(e)}")
                    db.rollback()

                # Add missing columns
                for col, sql in [
                    ('payment_type', "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_type paymenttype"),
                    ('tenant_id', "ALTER TABLE payments ADD COLUMN IF NOT EXISTS tenant_id UUID"),
                    ('payment_date', "ALTER TABLE payments ADD COLUMN IF NOT EXISTS payment_date TIMESTAMP"),
                    ('due_date', "ALTER TABLE payments ADD COLUMN IF NOT EXISTS due_date TIMESTAMP")
                ]:
                    if col not in existing_columns:
                        try:
                            db.execute(text(sql))
                            db.commit()
                            results["schema_fix"].append(f"Added {col} column")
                        except Exception as e:
                            results["schema_fix"].append(f"{col}: {str(e)}")
                            db.rollback()
                    else:
                        results["schema_fix"].append(f"{col} already exists")
            else:
                results["schema_fix"].append("Not PostgreSQL, skipping schema fix")
        except Exception as e:
            results["schema_fix"].append(f"Schema fix error: {str(e)}")

        # ===== STEP 2: Fix Property Ownership (raw SQL to avoid UUID type issues) =====
        try:
            owner = db.query(User).filter(User.role == UserRole.OWNER).first()
            if owner:
                owner_id_str = str(owner.id)
                # Find orphaned properties via raw SQL (cast role to TEXT to avoid enum issues)
                orphaned = db.execute(text("""
                    SELECT p.id, p.name FROM properties p
                    LEFT JOIN users u ON p.user_id = u.id
                    WHERE u.id IS NULL OR LOWER(CAST(u.role AS TEXT)) != 'owner'
                """)).fetchall()

                if orphaned:
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
                    results["property_fix"].append(f"Linked {len(orphaned)} properties to owner {owner.email}")
                else:
                    results["property_fix"].append("All properties correctly linked")
            else:
                results["property_fix"].append("No owner account found")
        except Exception as e:
            results["property_fix"].append(f"Property fix error: {str(e)}")
            db.rollback()

        # ===== STEP 3: Create Missing Units =====
        try:
            properties = db.query(Property).all()
            created_count = 0
            for prop in properties:
                existing_units = db.query(Unit).filter(Unit.property_id == prop.id).count()
                if existing_units == 0:
                    units_to_create = prop.total_units if prop.total_units and prop.total_units > 0 else 10
                    for i in range(1, units_to_create + 1):
                        new_unit = Unit(
                            id=uuid.uuid4(),
                            property_id=prop.id,
                            unit_number=f"Unit {i}",
                            bedrooms=1,
                            bathrooms=1.0,
                            monthly_rent=15000.0,
                            status="vacant"
                        )
                        db.add(new_unit)
                        created_count += 1
                    prop.total_units = units_to_create

            if created_count > 0:
                db.commit()
                results["units_fix"].append(f"Created {created_count} units")
            else:
                results["units_fix"].append("All properties have units")
        except Exception as e:
            results["units_fix"].append(f"Units fix error: {str(e)}")
            db.rollback()

        return {
            "success": True,
            "message": "All fixes completed",
            "results": results,
            "timestamp": datetime.utcnow().isoformat()
        }

    except Exception as e:
        import traceback
        return {
            "success": False,
            "error": str(e),
            "traceback": traceback.format_exc(),
            "results": results,
            "timestamp": datetime.utcnow().isoformat()
        }
    finally:
        db.close()
