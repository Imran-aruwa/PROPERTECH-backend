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
import asyncio
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
    inspections_router,
    market_router,
    workflows_router,
    leases_router,
    accounting_router,
    listings_router,
    mpesa_router,
    automation_router,
    chat_router,
    price_optimization_router,
    vacancy_prevention_router,
    vendor_intelligence_router,
    profit_engine_router,
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
    # Production domains
    "https://propertechsoftware.co.ke",
    "https://www.propertechsoftware.co.ke",
    "https://propertechsoftware.com",
    "https://www.propertechsoftware.com",
    # Configured frontend URL (from env)
    settings.FRONTEND_URL,
    # Local development
    "http://localhost:3000",
    "http://localhost:3001",
    "http://127.0.0.1:3000",
    "http://127.0.0.1:3001",
]

# Deduplicate
allowed_origins = list(dict.fromkeys(o for o in allowed_origins if o))

if settings.DEBUG:
    allowed_origins.extend([
        "http://localhost:8000",
        "http://localhost:8080",
    ])


app.add_middleware(
    CORSMiddleware,
    allow_origins=allowed_origins,
    # Also allow Railway subdomains and Vercel preview deployments
    allow_origin_regex=r"https://(.*\.railway\.app|.*\.vercel\.app)",
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
app.include_router(market_router, prefix="/api/market", tags=["Market Intelligence"])
app.include_router(workflows_router, prefix="/api/workflows", tags=["Workflows"])
app.include_router(leases_router, prefix="/api/leases", tags=["Leases"])
app.include_router(accounting_router, prefix="/api/accounting", tags=["Accounting"])
app.include_router(listings_router, prefix="/api/listings", tags=["Listings"])
app.include_router(mpesa_router, prefix="/api/mpesa", tags=["Mpesa Intelligence"])
app.include_router(automation_router, prefix="/api/automation", tags=["Autopilot"])
app.include_router(chat_router, prefix="/api", tags=["Chat"])
app.include_router(price_optimization_router, prefix="/api/price-optimization", tags=["Rent Optimizer"])
app.include_router(vacancy_prevention_router, prefix="/api/vacancy", tags=["Vacancy Prevention"])
app.include_router(vendor_intelligence_router, prefix="/api", tags=["Vendor Intelligence"])
app.include_router(profit_engine_router, prefix="/api", tags=["Profit Engine"])

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
    """Health check endpoint for Railway/monitoring — always returns 200 immediately."""
    return {"status": "ok", "timestamp": datetime.utcnow().isoformat()}


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


def _run_blocking_startup():
    """
    All synchronous startup work — migrations, schema fixes, seeding.
    Called via asyncio.to_thread() so the event loop stays free to serve
    health-check requests while this runs in a background thread.
    """
    # Test database connection
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

                # Ensure properties.area column exists (Market Intelligence feature)
                db.execute(text(
                    "ALTER TABLE properties ADD COLUMN IF NOT EXISTS area VARCHAR(100)"
                ))
                db.commit()
                logger.info("[OK] Properties.area column ensured")

                # Ensure all unit columns exist (added in later iterations of the model)
                try:
                    db.execute(text("ALTER TABLE tenants ADD COLUMN IF NOT EXISTS occupancy_type VARCHAR(20) DEFAULT 'renting'"))
                    db.execute(text("ALTER TABLE units ADD COLUMN IF NOT EXISTS has_master_bedroom BOOLEAN DEFAULT false"))
                    db.execute(text("ALTER TABLE units ADD COLUMN IF NOT EXISTS has_servant_quarters BOOLEAN DEFAULT false"))
                    db.execute(text("ALTER TABLE units ADD COLUMN IF NOT EXISTS sq_bathrooms INTEGER DEFAULT 0"))
                    db.execute(text("ALTER TABLE units ADD COLUMN IF NOT EXISTS occupancy_type VARCHAR(50) DEFAULT 'available'"))
                    db.execute(text("ALTER TABLE units ADD COLUMN IF NOT EXISTS description TEXT"))
                    db.execute(text("ALTER TABLE units ADD COLUMN IF NOT EXISTS toilets INTEGER DEFAULT 1"))
                    db.execute(text("ALTER TABLE units ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP"))
                    db.execute(text("ALTER TABLE properties ADD COLUMN IF NOT EXISTS photos TEXT"))
                    db.execute(text("ALTER TABLE properties ADD COLUMN IF NOT EXISTS total_units INTEGER DEFAULT 0"))
                    db.execute(text("ALTER TABLE properties ADD COLUMN IF NOT EXISTS updated_at TIMESTAMP"))
                    db.commit()
                    logger.info("[OK] Units/properties extra columns ensured")
                except Exception as unit_col_err:
                    logger.warning(f"[WARN] Units/properties column fix: {unit_col_err}")
                    db.rollback()

                # Ensure workflow automation tables exist (create_all handles this,
                # but we also ensure enum types exist for PostgreSQL)
                try:
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE triggerevent AS ENUM (
                                'rent_overdue', 'lease_expiring_soon',
                                'maintenance_request_opened', 'maintenance_request_resolved',
                                'unit_vacated', 'tenant_onboarded'
                            );
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE actiontype AS ENUM (
                                'send_notification', 'send_email',
                                'create_task', 'update_field', 'escalate'
                            );
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE workflowstatus AS ENUM ('active', 'inactive', 'draft');
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE workflowlogstatus AS ENUM ('success', 'failed', 'skipped');
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.commit()
                    logger.info("[OK] Workflow enum types ensured")
                except Exception as wf_enum_err:
                    logger.warning(f"[WARN] Workflow enum creation: {wf_enum_err}")
                    db.rollback()

                # Ensure lease enum types and tables exist (Digital Lease Management)
                try:
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE leasestatus AS ENUM (
                                'draft', 'sent', 'signed', 'active', 'expired', 'terminated'
                            );
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE paymentcycle AS ENUM (
                                'monthly', 'quarterly', 'annually'
                            );
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.commit()
                    logger.info("[OK] Lease enum types ensured")
                except Exception as lease_enum_err:
                    logger.warning(f"[WARN] Lease enum creation: {lease_enum_err}")
                    db.rollback()

                # Accounting enum types
                try:
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE entrytype AS ENUM ('income', 'expense');
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE entrycategory AS ENUM (
                                'rental_income', 'deposit_received', 'late_fee',
                                'service_charge', 'other_income',
                                'mortgage_interest', 'repairs_maintenance',
                                'property_management_fees', 'insurance',
                                'land_rates', 'ground_rent', 'legal_fees',
                                'advertising', 'depreciation', 'utilities',
                                'caretaker_salary', 'security', 'other'
                            );
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE taxrecordstatus AS ENUM ('draft', 'filed', 'paid');
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.commit()
                    logger.info("[OK] Accounting enum types ensured")
                except Exception as acc_enum_err:
                    logger.warning(f"[WARN] Accounting enum creation: {acc_enum_err}")
                    db.rollback()

                # Mpesa Payment Intelligence enum types
                try:
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE shortcodetype AS ENUM ('paybill', 'till');
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE mpesaenvironment AS ENUM ('sandbox', 'production');
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE transactiontype AS ENUM ('paybill', 'till', 'stk_push');
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE reconciliationstatus AS ENUM (
                                'unmatched', 'matched', 'partial', 'duplicate', 'disputed'
                            );
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE remindertype AS ENUM (
                                'pre_due', 'due_today', 'day_1', 'day_3',
                                'day_7', 'day_14', 'final_notice'
                            );
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE reminderchannel AS ENUM ('sms', 'whatsapp');
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE reminderstatus AS ENUM ('pending', 'sent', 'failed', 'delivered');
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE reconciliationaction AS ENUM (
                                'auto_matched', 'manual_matched', 'flagged', 'disputed'
                            );
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.commit()
                    logger.info("[OK] Mpesa enum types ensured")
                except Exception as mpesa_enum_err:
                    logger.warning(f"[WARN] Mpesa enum creation: {mpesa_enum_err}")
                    db.rollback()

                # Vacancy Listing Syndication enum types
                try:
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE listingstatus AS ENUM ('draft', 'active', 'paused', 'filled');
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE syndicationplatform AS ENUM (
                                'whatsapp', 'facebook', 'twitter',
                                'property24', 'buyrentkenya', 'jiji', 'direct_link'
                            );
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE syndicationstatus AS ENUM (
                                'pending', 'published', 'failed', 'expired'
                            );
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE leadstatus_listing AS ENUM (
                                'new', 'contacted', 'viewing_scheduled', 'approved', 'rejected'
                            );
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.execute(text("""
                        DO $$ BEGIN
                            CREATE TYPE analyticseventtype AS ENUM (
                                'view', 'inquiry', 'share', 'click'
                            );
                        EXCEPTION WHEN duplicate_object THEN null;
                        END $$;
                    """))
                    db.commit()
                    logger.info("[OK] Listing syndication enum types ensured")
                except Exception as listing_enum_err:
                    logger.warning(f"[WARN] Listing enum creation: {listing_enum_err}")
                    db.rollback()

                # Price Optimization Engine — ensure tables exist
                # (SQLAlchemy create_all handles this; we just ensure the schema is correct)
                try:
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS rent_reviews (
                            id UUID PRIMARY KEY,
                            owner_id UUID NOT NULL REFERENCES users(id),
                            unit_id UUID NOT NULL REFERENCES units(id),
                            property_id UUID NOT NULL REFERENCES properties(id),
                            trigger VARCHAR(50) NOT NULL,
                            current_rent NUMERIC(12,2) NOT NULL,
                            recommended_rent NUMERIC(12,2) NOT NULL,
                            min_rent NUMERIC(12,2) NOT NULL,
                            max_rent NUMERIC(12,2) NOT NULL,
                            confidence_score INTEGER DEFAULT 50,
                            reasoning JSONB,
                            market_data_snapshot JSONB,
                            status VARCHAR(20) NOT NULL DEFAULT 'pending',
                            accepted_rent NUMERIC(12,2),
                            reviewed_by UUID REFERENCES users(id),
                            reviewed_at TIMESTAMPTZ,
                            applied_at TIMESTAMPTZ,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS market_comparables (
                            id UUID PRIMARY KEY,
                            owner_id UUID NOT NULL REFERENCES users(id),
                            property_id UUID REFERENCES properties(id),
                            unit_type VARCHAR(50) NOT NULL,
                            bedrooms INTEGER,
                            location_area VARCHAR(200) NOT NULL,
                            asking_rent NUMERIC(12,2) NOT NULL,
                            actual_rent NUMERIC(12,2),
                            vacancy_days INTEGER,
                            source VARCHAR(30) NOT NULL DEFAULT 'manual',
                            data_date DATE NOT NULL,
                            notes TEXT,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS price_optimization_settings (
                            id UUID PRIMARY KEY,
                            owner_id UUID NOT NULL UNIQUE REFERENCES users(id),
                            is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                            auto_apply BOOLEAN NOT NULL DEFAULT FALSE,
                            max_increase_pct NUMERIC(5,2) NOT NULL DEFAULT 10.0,
                            max_decrease_pct NUMERIC(5,2) NOT NULL DEFAULT 15.0,
                            target_vacancy_days INTEGER NOT NULL DEFAULT 14,
                            min_rent_floor NUMERIC(12,2),
                            comparable_radius_km NUMERIC(5,2) NOT NULL DEFAULT 2.0,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS vacancy_history (
                            id UUID PRIMARY KEY,
                            unit_id UUID NOT NULL REFERENCES units(id),
                            owner_id UUID NOT NULL REFERENCES users(id),
                            vacant_from TIMESTAMPTZ NOT NULL,
                            vacant_until TIMESTAMPTZ,
                            days_vacant INTEGER,
                            rent_at_vacancy NUMERIC(12,2) NOT NULL,
                            rent_when_filled NUMERIC(12,2),
                            price_changes_count INTEGER NOT NULL DEFAULT 0,
                            filled_by_tenant_id UUID REFERENCES users(id),
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    db.commit()
                    logger.info("[OK] Price Optimization Engine tables ensured")
                except Exception as price_opt_err:
                    logger.warning(f"[WARN] Price Optimization table creation: {price_opt_err}")
                    db.rollback()

                # Vacancy Prevention Engine — ensure tables exist
                try:
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS vacancy_leads (
                            id UUID PRIMARY KEY,
                            owner_id UUID NOT NULL REFERENCES users(id),
                            property_id UUID REFERENCES properties(id),
                            unit_id UUID REFERENCES units(id),
                            lead_name VARCHAR(255) NOT NULL,
                            lead_phone VARCHAR(50) NOT NULL,
                            lead_email VARCHAR(255),
                            source VARCHAR(50) NOT NULL DEFAULT 'manual',
                            status VARCHAR(50) NOT NULL DEFAULT 'new',
                            preferred_unit_type VARCHAR(50),
                            preferred_move_in DATE,
                            budget_min NUMERIC(12,2),
                            budget_max NUMERIC(12,2),
                            notes TEXT,
                            last_contacted_at TIMESTAMPTZ,
                            follow_up_due_at TIMESTAMPTZ,
                            converted_tenant_id UUID REFERENCES users(id),
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS vacancy_lead_activities (
                            id UUID PRIMARY KEY,
                            lead_id UUID NOT NULL REFERENCES vacancy_leads(id) ON DELETE CASCADE,
                            owner_id UUID NOT NULL REFERENCES users(id),
                            activity_type VARCHAR(50) NOT NULL,
                            content TEXT NOT NULL,
                            performed_by UUID NOT NULL REFERENCES users(id),
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS listing_syndications (
                            id UUID PRIMARY KEY,
                            owner_id UUID NOT NULL REFERENCES users(id),
                            unit_id UUID NOT NULL REFERENCES units(id),
                            listing_id UUID,
                            title VARCHAR(500) NOT NULL,
                            description TEXT,
                            monthly_rent NUMERIC(12,2) NOT NULL,
                            bedrooms INTEGER,
                            bathrooms INTEGER,
                            unit_type VARCHAR(50) NOT NULL,
                            amenities JSONB DEFAULT '[]',
                            photos JSONB DEFAULT '[]',
                            location_area VARCHAR(200),
                            status VARCHAR(20) NOT NULL DEFAULT 'draft',
                            view_count INTEGER NOT NULL DEFAULT 0,
                            enquiry_count INTEGER NOT NULL DEFAULT 0,
                            platforms JSONB DEFAULT '[]',
                            published_at TIMESTAMPTZ,
                            filled_at TIMESTAMPTZ,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS renewal_campaigns (
                            id UUID PRIMARY KEY,
                            owner_id UUID NOT NULL REFERENCES users(id),
                            lease_id UUID NOT NULL REFERENCES leases(id),
                            tenant_id UUID REFERENCES users(id),
                            unit_id UUID NOT NULL REFERENCES units(id),
                            campaign_status VARCHAR(30) NOT NULL DEFAULT 'scheduled',
                            trigger_days_before_expiry INTEGER NOT NULL,
                            offer_type VARCHAR(20) NOT NULL DEFAULT 'standard',
                            incentive_description TEXT,
                            proposed_rent NUMERIC(12,2),
                            current_rent NUMERIC(12,2) NOT NULL,
                            tenant_response VARCHAR(30),
                            response_received_at TIMESTAMPTZ,
                            follow_up_count INTEGER NOT NULL DEFAULT 0,
                            last_follow_up_at TIMESTAMPTZ,
                            outcome VARCHAR(20),
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS vacancy_prevention_settings (
                            id UUID PRIMARY KEY,
                            owner_id UUID NOT NULL UNIQUE REFERENCES users(id),
                            is_enabled BOOLEAN NOT NULL DEFAULT TRUE,
                            auto_create_listing BOOLEAN NOT NULL DEFAULT TRUE,
                            auto_syndicate BOOLEAN NOT NULL DEFAULT FALSE,
                            renewal_campaign_days JSONB DEFAULT '[60, 30, 7]',
                            lead_follow_up_hours INTEGER NOT NULL DEFAULT 24,
                            auto_sms_new_leads BOOLEAN NOT NULL DEFAULT TRUE,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    db.commit()
                    logger.info("[OK] Vacancy Prevention Engine tables ensured")
                except Exception as vp_err:
                    logger.warning(f"[WARN] Vacancy Prevention table creation: {vp_err}")
                    db.rollback()

                # Vendor & Maintenance Intelligence Engine — ensure tables exist
                try:
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS vendors (
                            id UUID PRIMARY KEY,
                            owner_id UUID NOT NULL REFERENCES users(id),
                            name VARCHAR(255) NOT NULL,
                            category VARCHAR(50) NOT NULL,
                            phone VARCHAR(50) NOT NULL,
                            email VARCHAR(255),
                            location_area VARCHAR(200),
                            rating NUMERIC(3,2),
                            total_jobs INTEGER NOT NULL DEFAULT 0,
                            completed_jobs INTEGER NOT NULL DEFAULT 0,
                            avg_response_hours NUMERIC(6,2),
                            avg_completion_days NUMERIC(6,2),
                            total_paid NUMERIC(14,2) NOT NULL DEFAULT 0,
                            is_preferred BOOLEAN NOT NULL DEFAULT FALSE,
                            is_blacklisted BOOLEAN NOT NULL DEFAULT FALSE,
                            blacklist_reason TEXT,
                            notes TEXT,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS maintenance_schedules (
                            id UUID PRIMARY KEY,
                            owner_id UUID NOT NULL REFERENCES users(id),
                            property_id UUID REFERENCES properties(id),
                            unit_id UUID REFERENCES units(id),
                            title VARCHAR(500) NOT NULL,
                            category VARCHAR(50) NOT NULL,
                            description TEXT,
                            frequency VARCHAR(20) NOT NULL,
                            next_due DATE NOT NULL,
                            last_completed DATE,
                            estimated_cost NUMERIC(12,2),
                            preferred_vendor_id UUID REFERENCES vendors(id),
                            is_active BOOLEAN NOT NULL DEFAULT TRUE,
                            auto_create_job BOOLEAN NOT NULL DEFAULT FALSE,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS vendor_jobs (
                            id UUID PRIMARY KEY,
                            owner_id UUID NOT NULL REFERENCES users(id),
                            vendor_id UUID NOT NULL REFERENCES vendors(id),
                            maintenance_request_id UUID REFERENCES maintenance_requests(id),
                            unit_id UUID NOT NULL REFERENCES units(id),
                            property_id UUID NOT NULL REFERENCES properties(id),
                            title VARCHAR(500) NOT NULL,
                            description TEXT,
                            category VARCHAR(50) NOT NULL,
                            priority VARCHAR(20) NOT NULL DEFAULT 'normal',
                            status VARCHAR(20) NOT NULL DEFAULT 'assigned',
                            quoted_amount NUMERIC(12,2),
                            final_amount NUMERIC(12,2),
                            paid BOOLEAN NOT NULL DEFAULT FALSE,
                            paid_at TIMESTAMPTZ,
                            payment_method VARCHAR(50),
                            assigned_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            started_at TIMESTAMPTZ,
                            completed_at TIMESTAMPTZ,
                            due_date DATE,
                            owner_rating INTEGER,
                            owner_review TEXT,
                            rated_at TIMESTAMPTZ,
                            photos_before JSONB DEFAULT '[]',
                            photos_after JSONB DEFAULT '[]',
                            notes TEXT,
                            schedule_id UUID REFERENCES maintenance_schedules(id),
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS maintenance_cost_budgets (
                            id UUID PRIMARY KEY,
                            owner_id UUID NOT NULL REFERENCES users(id),
                            property_id UUID REFERENCES properties(id),
                            year INTEGER NOT NULL,
                            month INTEGER,
                            budget_amount NUMERIC(14,2) NOT NULL,
                            actual_amount NUMERIC(14,2) NOT NULL DEFAULT 0,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    # Add assigned_vendor_id to maintenance_requests if not present
                    db.execute(text(
                        "ALTER TABLE maintenance_requests ADD COLUMN IF NOT EXISTS "
                        "assigned_vendor_id UUID REFERENCES vendors(id)"
                    ))
                    db.commit()
                    logger.info("[OK] Vendor Intelligence Engine tables ensured")
                except Exception as vendor_err:
                    logger.warning(f"[WARN] Vendor Intelligence table creation: {vendor_err}")
                    db.rollback()

                # Profit Optimization Engine — ensure tables exist
                try:
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS financial_snapshots (
                            id UUID PRIMARY KEY,
                            owner_id UUID NOT NULL REFERENCES users(id),
                            property_id UUID REFERENCES properties(id),
                            unit_id UUID REFERENCES units(id),
                            snapshot_period VARCHAR(7) NOT NULL,
                            revenue_gross NUMERIC(14,2) NOT NULL DEFAULT 0,
                            revenue_expected NUMERIC(14,2) NOT NULL DEFAULT 0,
                            vacancy_loss NUMERIC(14,2) NOT NULL DEFAULT 0,
                            maintenance_cost NUMERIC(14,2) NOT NULL DEFAULT 0,
                            other_expenses NUMERIC(14,2) NOT NULL DEFAULT 0,
                            late_fees_collected NUMERIC(14,2) NOT NULL DEFAULT 0,
                            net_operating_income NUMERIC(14,2) NOT NULL DEFAULT 0,
                            occupancy_rate NUMERIC(5,2) NOT NULL DEFAULT 0,
                            collection_rate NUMERIC(5,2) NOT NULL DEFAULT 0,
                            computed_at TIMESTAMPTZ,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            CONSTRAINT uq_financial_snapshot UNIQUE (owner_id, snapshot_period, property_id, unit_id)
                        )
                    """))
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS expense_records (
                            id UUID PRIMARY KEY,
                            owner_id UUID NOT NULL REFERENCES users(id),
                            property_id UUID REFERENCES properties(id),
                            unit_id UUID REFERENCES units(id),
                            category VARCHAR(50) NOT NULL,
                            description VARCHAR(500) NOT NULL,
                            amount NUMERIC(12,2) NOT NULL,
                            expense_date DATE NOT NULL,
                            vendor_job_id UUID REFERENCES vendor_jobs(id),
                            receipt_url VARCHAR(500),
                            notes TEXT,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS profit_targets (
                            id UUID PRIMARY KEY,
                            owner_id UUID NOT NULL REFERENCES users(id),
                            property_id UUID REFERENCES properties(id),
                            target_type VARCHAR(30) NOT NULL,
                            target_value NUMERIC(10,2) NOT NULL,
                            period VARCHAR(10) NOT NULL DEFAULT 'monthly',
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            updated_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS financial_reports (
                            id UUID PRIMARY KEY,
                            owner_id UUID NOT NULL REFERENCES users(id),
                            report_period VARCHAR(7) NOT NULL,
                            report_type VARCHAR(20) NOT NULL DEFAULT 'monthly',
                            status VARCHAR(20) NOT NULL DEFAULT 'generating',
                            generated_at TIMESTAMPTZ,
                            data JSONB,
                            pdf_url VARCHAR(500),
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    db.commit()
                    logger.info("[OK] Profit Optimization Engine tables ensured")
                except Exception as profit_err:
                    logger.warning(f"[WARN] Profit Engine table creation: {profit_err}")
                    db.rollback()

                # Automation / Autopilot enum types and schema
                try:
                    db.execute(text("ALTER TABLE users ADD COLUMN IF NOT EXISTS theme_preference VARCHAR(10) DEFAULT 'system'"))
                    db.commit()
                    logger.info("[OK] users.theme_preference column ensured")
                except Exception as theme_err:
                    logger.warning(f"[WARN] theme_preference column: {theme_err}")
                    db.rollback()

                # Inspection schema fixes — add new columns added by universal engine migration
                try:
                    db.execute(text("ALTER TABLE inspections ADD COLUMN IF NOT EXISTS is_external BOOLEAN DEFAULT false"))
                    db.execute(text("ALTER TABLE inspections ADD COLUMN IF NOT EXISTS template_id UUID"))
                    db.execute(text("ALTER TABLE inspections ADD COLUMN IF NOT EXISTS overall_score FLOAT"))
                    db.execute(text("ALTER TABLE inspections ADD COLUMN IF NOT EXISTS pass_fail VARCHAR(10)"))
                    db.execute(text("ALTER TABLE inspections ADD COLUMN IF NOT EXISTS inspector_name VARCHAR(255)"))
                    db.execute(text("ALTER TABLE inspections ADD COLUMN IF NOT EXISTS inspector_credentials VARCHAR(500)"))
                    db.execute(text("ALTER TABLE inspections ADD COLUMN IF NOT EXISTS inspector_company VARCHAR(255)"))
                    db.execute(text("ALTER TABLE inspections ADD COLUMN IF NOT EXISTS report_url VARCHAR(500)"))
                    db.execute(text("ALTER TABLE inspection_items ADD COLUMN IF NOT EXISTS score INTEGER"))
                    db.execute(text("ALTER TABLE inspection_items ADD COLUMN IF NOT EXISTS severity VARCHAR(10)"))
                    db.execute(text("ALTER TABLE inspection_items ADD COLUMN IF NOT EXISTS pass_fail VARCHAR(10)"))
                    db.execute(text("ALTER TABLE inspection_items ADD COLUMN IF NOT EXISTS requires_followup BOOLEAN DEFAULT false"))
                    db.execute(text("ALTER TABLE inspection_items ADD COLUMN IF NOT EXISTS photo_required BOOLEAN DEFAULT false"))
                    # Drop restrictive check constraints added by old migration (block new types/categories)
                    db.execute(text("ALTER TABLE inspections DROP CONSTRAINT IF EXISTS ck_inspections_type"))
                    db.execute(text("ALTER TABLE inspection_items DROP CONSTRAINT IF EXISTS ck_items_category"))
                    db.commit()
                    logger.info("[OK] Inspection schema fixes applied")
                except Exception as insp_err:
                    logger.warning(f"[WARN] Inspection schema fix: {insp_err}")
                    db.rollback()

                # Offline Inspection & Sync Engine (Feature #7) — new tables + columns
                try:
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS inspection_rooms (
                            id UUID PRIMARY KEY,
                            inspection_id UUID NOT NULL REFERENCES inspections(id) ON DELETE CASCADE,
                            client_uuid UUID NOT NULL UNIQUE,
                            name VARCHAR(255) NOT NULL,
                            order_index INTEGER NOT NULL DEFAULT 0,
                            condition_summary VARCHAR(20),
                            notes TEXT,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW()
                        )
                    """))
                    db.execute(text("""
                        CREATE TABLE IF NOT EXISTS sync_queue (
                            id UUID PRIMARY KEY,
                            device_id VARCHAR(255) NOT NULL,
                            owner_id UUID NOT NULL REFERENCES users(id),
                            payload JSONB NOT NULL,
                            status VARCHAR(20) NOT NULL DEFAULT 'pending',
                            attempts INTEGER NOT NULL DEFAULT 0,
                            result JSONB,
                            error_detail TEXT,
                            created_at TIMESTAMPTZ NOT NULL DEFAULT NOW(),
                            processed_at TIMESTAMPTZ
                        )
                    """))
                    # New columns on existing inspection tables
                    db.execute(text("ALTER TABLE inspection_items ADD COLUMN IF NOT EXISTS room_id UUID REFERENCES inspection_rooms(id)"))
                    db.execute(text("ALTER TABLE inspection_items ADD COLUMN IF NOT EXISTS requires_maintenance BOOLEAN DEFAULT false"))
                    db.execute(text("ALTER TABLE inspection_items ADD COLUMN IF NOT EXISTS maintenance_priority VARCHAR(20) DEFAULT 'normal'"))
                    db.execute(text("ALTER TABLE inspection_items ADD COLUMN IF NOT EXISTS vendor_job_id UUID"))
                    db.execute(text("ALTER TABLE inspection_templates ADD COLUMN IF NOT EXISTS rooms JSONB"))
                    db.execute(text("ALTER TABLE inspection_templates ADD COLUMN IF NOT EXISTS is_system_template BOOLEAN DEFAULT false"))
                    # Indexes for performance
                    db.execute(text("CREATE INDEX IF NOT EXISTS idx_inspection_rooms_inspection ON inspection_rooms(inspection_id)"))
                    db.execute(text("CREATE INDEX IF NOT EXISTS idx_sync_queue_device ON sync_queue(device_id)"))
                    db.execute(text("CREATE INDEX IF NOT EXISTS idx_sync_queue_status ON sync_queue(status)"))
                    db.commit()
                    logger.info("[OK] Offline Inspection Engine tables/columns ensured")
                except Exception as offline_insp_err:
                    logger.warning(f"[WARN] Offline Inspection schema: {offline_insp_err}")
                    db.rollback()

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

    # ── Autopilot: start scheduler, wire event bus, seed templates ────────────
    logger.info("Starting Autopilot scheduler and event bus...")
    try:
        from app.services.scheduler import create_scheduler
        from app.services.event_bus import event_bus
        from app.services.automation_engine import AutomationEngine, set_engine
        from app.services.seed_templates import seed_system_templates
        from app.database import SessionLocal

        # Start APScheduler
        _scheduler = create_scheduler()
        _scheduler.start()
        logger.info("[OK] Autopilot scheduler started")

        # Create AutomationEngine and wire to event bus
        _db = SessionLocal()
        _engine = AutomationEngine(_db)
        set_engine(_engine)
        event_bus.subscribe("*", _engine.handle_event)
        logger.info("[OK] AutomationEngine subscribed to event bus")

        # Seed system templates (idempotent)
        seed_system_templates(_db)
        _db.close()
        logger.info("[OK] Autopilot system templates seeded")

    except Exception as autopilot_err:
        logger.warning(f"[WARN] Autopilot startup failed: {autopilot_err} — continuing anyway")

    # ── Price Optimization: subscribe to vacancy events ────────────────────────
    logger.info("Wiring Price Optimization Engine to event bus...")
    try:
        from app.services.event_bus import event_bus, PropertyEvent
        from app.services.price_optimization_service import PriceOptimizationService
        from app.services.vacancy_history_service import VacancyHistoryService
        from app.models.automation import AutomationActionLog
        from app.database import SessionLocal
        import uuid as _uuid
        import json as _json

        async def _on_unit_vacated(event: PropertyEvent) -> None:
            """
            Fires when a unit goes vacant.
            1. Starts vacancy history record.
            2. Creates a pending RentReview.
            3. If auto_apply=True, immediately applies the recommendation.
            """
            unit_id = event.payload.get("unit_id")
            owner_id = event.owner_id
            current_rent = float(event.payload.get("monthly_rent", 0))
            if not unit_id:
                return

            db = SessionLocal()
            try:
                owner_uuid = _uuid.UUID(owner_id)

                # 1. Track vacancy
                vh_svc = VacancyHistoryService(db)
                try:
                    vh_svc.start_vacancy(unit_id, owner_id, current_rent)
                except Exception as vh_err:
                    logger.warning(f"[price_opt] start_vacancy failed: {vh_err}")

                # 2. Create review
                svc = PriceOptimizationService(db, owner_uuid)
                try:
                    review = svc.create_review(unit_id=unit_id, trigger="unit_vacant")
                except Exception as rev_err:
                    logger.warning(f"[price_opt] create_review on unit_vacated failed: {rev_err}")
                    return

                # 3. Auto-apply if setting is on
                from app.models.price_optimization import PriceOptimizationSettings as _POS
                settings = db.query(_POS).filter(_POS.owner_id == owner_uuid).first()
                if settings and settings.auto_apply:
                    try:
                        svc.apply_recommendation(
                            review_id=str(review.id),
                            accepted_rent=float(review.recommended_rent),
                            reviewed_by=owner_uuid,
                        )
                        # Log to automation_actions_log for Autopilot Audit visibility
                        log_entry = AutomationActionLog(
                            id=_uuid.uuid4(),
                            execution_id=_uuid.UUID(int=0),  # synthetic
                            owner_id=owner_uuid,
                            action_type="auto_apply_rent_recommendation",
                            action_payload={
                                "unit_id": unit_id,
                                "old_rent": current_rent,
                                "new_rent": float(review.recommended_rent),
                                "review_id": str(review.id),
                                "trigger": "unit_vacant",
                            },
                            result_status="success",
                            result_data={
                                "message": (
                                    f"Rent auto-changed from KES {current_rent:,.0f} "
                                    f"to KES {float(review.recommended_rent):,.0f} "
                                    f"(auto_apply=True)"
                                ),
                                "review_id": str(review.id),
                            },
                            executed_at=datetime.utcnow(),
                            reversible=True,
                        )
                        db.add(log_entry)
                        db.commit()
                        logger.info(
                            f"[price_opt] AUTO-APPLIED rent for unit {unit_id}: "
                            f"KES {current_rent:,.0f} → KES {float(review.recommended_rent):,.0f}"
                        )
                    except Exception as apply_err:
                        logger.error(f"[price_opt] auto_apply failed: {apply_err}", exc_info=True)
            finally:
                db.close()

        async def _on_tenant_onboarded(event: PropertyEvent) -> None:
            """Fires when a tenant is onboarded — closes the open vacancy record."""
            unit_id = event.payload.get("unit_id")
            tenant_id = event.payload.get("tenant_id")
            rent_when_filled = float(event.payload.get("monthly_rent", 0))
            if not unit_id:
                return

            db = SessionLocal()
            try:
                vh_svc = VacancyHistoryService(db)
                vh_svc.end_vacancy(unit_id, tenant_id, rent_when_filled)
            except Exception as exc:
                logger.warning(f"[price_opt] end_vacancy on tenant_onboarded failed: {exc}")
            finally:
                db.close()

        event_bus.subscribe("unit_vacated", _on_unit_vacated)
        event_bus.subscribe("tenant_onboarded", _on_tenant_onboarded)
        logger.info("[OK] Price Optimization Engine subscribed to unit_vacated + tenant_onboarded")

    except Exception as po_startup_err:
        logger.warning(f"[WARN] Price Optimization startup failed: {po_startup_err} — continuing anyway")

    # ── Vacancy Prevention: subscribe to vacancy + lease events ───────────────
    logger.info("Wiring Vacancy Prevention Engine to event bus...")
    try:
        from app.services.event_bus import event_bus as _event_bus, PropertyEvent as _PE
        from app.services.vacancy_prevention_service import VacancyPreventionService as _VPS
        from app.models.vacancy_prevention import ListingSyndication as _LS, RenewalCampaign as _RC
        from app.database import SessionLocal as _SL2
        import uuid as _uuid2

        async def _vp_on_unit_vacated(event: _PE) -> None:
            unit_id = event.payload.get("unit_id")
            if not unit_id:
                return
            db = _SL2()
            try:
                owner_uuid = _uuid2.UUID(event.owner_id)
                svc = _VPS(db, owner_uuid)
                if svc.get_or_create_settings().is_enabled:
                    svc.handle_unit_vacated(unit_id)
            except Exception as exc:
                logger.warning(f"[vacancy] vp_on_unit_vacated failed: {exc}")
            finally:
                db.close()

        async def _vp_on_unit_vacant_7d(event: _PE) -> None:
            """Unit still vacant after 7 days — alert owner and suggest price review."""
            unit_id = event.payload.get("unit_id")
            owner_id = event.owner_id
            unit_number = event.payload.get("unit_number", "")
            monthly_rent = event.payload.get("monthly_rent", 0)
            days_vacant = event.payload.get("days_vacant", 7)
            db = _SL2()
            try:
                from app.models.user import User as _U
                owner_uuid = _uuid2.UUID(owner_id)
                svc = _VPS(db, owner_uuid)
                if not svc.get_or_create_settings().is_enabled:
                    return
                owner = db.query(_U).filter(_U.id == owner_uuid).first()
                if owner and hasattr(owner, "phone") and owner.phone:
                    from app.services.vacancy_prevention_service import _send_sms
                    msg = (
                        f"PROPERTECH: Unit {unit_number} has been vacant for {days_vacant} days "
                        f"(rent KES {float(monthly_rent):,.0f}). "
                        f"Log in to review your price or promote the listing."
                    )
                    _send_sms(owner.phone, msg)
            except Exception as exc:
                logger.warning(f"[vacancy] vp_on_unit_vacant_7d failed: {exc}")
            finally:
                db.close()

        async def _vp_on_lease_expiring(event: _PE) -> None:
            lease_id = event.payload.get("lease_id")
            days_remaining = int(event.payload.get("days_remaining", 0))
            event_type = event.payload.get("event_type", event.event_type)
            if not lease_id:
                return
            # Map event type to days_before trigger
            if "60" in event_type:
                days_before = 60
            elif "30" in event_type:
                days_before = 30
            elif "7" in event_type or "7d" in event_type:
                days_before = 7
            else:
                days_before = days_remaining
            db = _SL2()
            try:
                owner_uuid = _uuid2.UUID(event.owner_id)
                svc = _VPS(db, owner_uuid)
                if svc.get_or_create_settings().is_enabled:
                    svc.handle_lease_expiring(lease_id=lease_id, days_before=days_before)
            except Exception as exc:
                logger.warning(f"[vacancy] vp_on_lease_expiring failed: {exc}")
            finally:
                db.close()

        async def _vp_on_tenant_onboarded(event: _PE) -> None:
            unit_id = event.payload.get("unit_id")
            if not unit_id:
                return
            db = _SL2()
            try:
                owner_uuid = _uuid2.UUID(event.owner_id)
                unit_uuid = _uuid2.UUID(unit_id)
                now = datetime.utcnow()

                # Mark active listing as filled
                synd = db.query(_LS).filter(
                    _LS.unit_id == unit_uuid,
                    _LS.owner_id == owner_uuid,
                    _LS.status == "active",
                ).first()
                if synd:
                    synd.status = "filled"
                    synd.filled_at = now
                    logger.info(f"[vacancy] Syndication {synd.id} marked filled")

                # Mark renewal campaign as renewed if applicable
                campaign = db.query(_RC).filter(
                    _RC.unit_id == unit_uuid,
                    _RC.owner_id == owner_uuid,
                    _RC.campaign_status.in_(["active", "responded"]),
                    _RC.outcome == None,  # noqa: E711
                ).first()
                if campaign:
                    campaign.outcome = "renewed"
                    campaign.campaign_status = "accepted"

                db.commit()
            except Exception as exc:
                logger.warning(f"[vacancy] vp_on_tenant_onboarded failed: {exc}")
            finally:
                db.close()

        _event_bus.subscribe("unit_vacated", _vp_on_unit_vacated)
        _event_bus.subscribe("unit_vacant_7d", _vp_on_unit_vacant_7d)
        _event_bus.subscribe("lease_expiring_60d", _vp_on_lease_expiring)
        _event_bus.subscribe("lease_expiring_30d", _vp_on_lease_expiring)
        _event_bus.subscribe("lease_expiring_7d", _vp_on_lease_expiring)
        _event_bus.subscribe("tenant_onboarded", _vp_on_tenant_onboarded)
        logger.info("[OK] Vacancy Prevention Engine subscribed to 6 events")

    except Exception as vp_startup_err:
        logger.warning(f"[WARN] Vacancy Prevention startup failed: {vp_startup_err} — continuing anyway")

    # ── Vendor Intelligence: subscribe to maintenance events ──────────────────
    logger.info("Wiring Vendor Intelligence Engine to event bus...")
    try:
        from app.services.event_bus import event_bus as _vi_bus, PropertyEvent as _VI_PE
        from app.database import SessionLocal as _SL3
        import uuid as _uuid3

        async def _vi_on_maintenance_created(event: _VI_PE) -> None:
            """
            Fires when a maintenance request is created.
            If owner has preferred vendor for this category, suggest via log.
            """
            mr_id = event.payload.get("maintenance_request_id")
            category = event.payload.get("category", "general")
            owner_id = event.owner_id
            if not mr_id:
                return
            db = _SL3()
            try:
                from app.models.vendor_intelligence import Vendor as _V
                owner_uuid = _uuid3.UUID(owner_id)
                # Find preferred vendor in same category
                preferred = db.query(_V).filter(
                    _V.owner_id == owner_uuid,
                    _V.category == category,
                    _V.is_preferred == True,
                    _V.is_blacklisted == False,
                ).first()
                if preferred:
                    from app.models.automation import AutomationActionLog
                    import uuid as _u
                    log = AutomationActionLog(
                        id=_u.uuid4(),
                        execution_id=_u.UUID(int=0),
                        owner_id=owner_uuid,
                        action_type="vendor_suggestion",
                        action_payload={
                            "maintenance_request_id": mr_id,
                            "suggested_vendor_id": str(preferred.id),
                            "suggested_vendor_name": preferred.name,
                            "category": category,
                        },
                        result_status="success",
                        result_data={
                            "message": (
                                f"Preferred vendor '{preferred.name}' available "
                                f"for {category} work."
                            )
                        },
                        executed_at=datetime.utcnow(),
                        reversible=False,
                    )
                    db.add(log)
                    db.commit()
                    logger.info(
                        f"[vendor] Suggested preferred vendor {preferred.name} "
                        f"for maintenance request {mr_id}"
                    )
            except Exception as exc:
                logger.warning(f"[vendor] vi_on_maintenance_created failed: {exc}")
            finally:
                db.close()

        async def _vi_on_maintenance_overdue(event: _VI_PE) -> None:
            """
            Fires when a maintenance request is overdue (>48h open).
            If no vendor job exists for this request, log alert.
            """
            mr_id = event.payload.get("maintenance_request_id")
            owner_id = event.owner_id
            if not mr_id:
                return
            db = _SL3()
            try:
                from app.models.vendor_intelligence import VendorJob as _VJ
                owner_uuid = _uuid3.UUID(owner_id)
                mr_uuid = _uuid3.UUID(mr_id)
                existing_job = db.query(_VJ).filter(
                    _VJ.maintenance_request_id == mr_uuid,
                    _VJ.owner_id == owner_uuid,
                    _VJ.status.notin_(["cancelled", "disputed"]),
                ).first()
                if not existing_job:
                    from app.models.automation import AutomationActionLog
                    import uuid as _u
                    log = AutomationActionLog(
                        id=_u.uuid4(),
                        execution_id=_u.UUID(int=0),
                        owner_id=owner_uuid,
                        action_type="maintenance_overdue_no_vendor",
                        action_payload={"maintenance_request_id": mr_id},
                        result_status="success",
                        result_data={
                            "message": (
                                f"Maintenance request {mr_id} is overdue "
                                f"with no vendor assigned."
                            )
                        },
                        executed_at=datetime.utcnow(),
                        reversible=False,
                    )
                    db.add(log)
                    db.commit()
                    logger.info(f"[vendor] Overdue MR {mr_id} has no vendor job assigned")
            except Exception as exc:
                logger.warning(f"[vendor] vi_on_maintenance_overdue failed: {exc}")
            finally:
                db.close()

        _vi_bus.subscribe("maintenance_request_created", _vi_on_maintenance_created)
        _vi_bus.subscribe("maintenance_overdue", _vi_on_maintenance_overdue)
        logger.info("[OK] Vendor Intelligence Engine subscribed to maintenance events")

    except Exception as vi_startup_err:
        logger.warning(f"[WARN] Vendor Intelligence startup failed: {vi_startup_err} — continuing anyway")

    # ── Offline Inspection Engine: seed system templates for all owners ────────
    logger.info("Seeding inspection system templates...")
    try:
        from app.services.offline_inspection_service import InspectionService
        from app.database import SessionLocal
        from app.models.user import User as _UserM, UserRole as _UR

        _seed_db = SessionLocal()
        try:
            owners = _seed_db.query(_UserM).filter(_UserM.role == _UR.OWNER).all()
            for _owner in owners:
                try:
                    InspectionService(_seed_db, _owner.id).seed_system_templates()
                except Exception as _se:
                    logger.warning(f"[WARN] Template seed for owner {_owner.id}: {_se}")
            logger.info(f"[OK] Inspection templates seeded for {len(owners)} owner(s)")
        finally:
            _seed_db.close()
    except Exception as seed_insp_err:
        logger.warning(f"[WARN] Inspection template seeding failed: {seed_insp_err} — continuing anyway")

    # Print plan summary and warn about missing Paystack plan codes
    try:
        from app.seeds.seed_plans import print_plan_summary
        print_plan_summary()
    except Exception as plans_err:
        logger.warning(f"[WARN] Plan summary failed: {plans_err} — continuing anyway")

    logger.info("="*70)
    logger.info("[OK] Blocking startup tasks complete!")
    logger.info("="*70)


@app.on_event("startup")
async def startup_event():
    """Run on application startup — logs banner then offloads all blocking work to a thread."""
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

    # Run all blocking DB/migration work in a thread pool so the event loop stays
    # free to serve health-check requests while startup is in progress.
    await asyncio.to_thread(_run_blocking_startup)
    logger.info("[OK] Application startup complete!")


@app.on_event("shutdown")
async def shutdown_event():
    """Run on application shutdown"""
    logger.info("="*70)
    logger.info("Shutting down application...")
    logger.info("="*70)

    # Stop APScheduler
    try:
        from app.services.scheduler import get_scheduler
        s = get_scheduler()
        if s and s.running:
            s.shutdown(wait=False)
            logger.info("[OK] Autopilot scheduler stopped")
    except Exception:
        pass

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


