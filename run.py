import uvicorn
import sys
import os
from contextlib import asynccontextmanager

def run_migrations():
    """Run Alembic migrations."""
    try:
        from alembic.config import Config
        from alembic import command

        alembic_cfg = Config("alembic.ini")
        print("[STARTUP] Running database migrations...")
        command.upgrade(alembic_cfg, "head")
        print("[STARTUP] Migrations complete!")
        return True
    except Exception as e:
        print(f"[WARN] Migration failed: {e}")
        return False

def init_database():
    """Initialize database tables directly (fallback)."""
    from app.database import init_db
    print("[STARTUP] Initializing database tables...")
    init_db()
    print("[STARTUP] Database initialization complete!")

@asynccontextmanager
async def lifespan(app):
    """FastAPI lifespan events for startup."""
    print("[STARTUP] Starting ProperTech API...")
    
    # Run migrations or init DB
    use_migrations = os.getenv("RUN_MIGRATIONS") == "true"
    if use_migrations:
        if not run_migrations():
            print("[WARN] Falling back to direct table creation...")
            init_database()
    else:
        init_database()
    
    print("[STARTUP] Database ready!")
    print(f"[STARTUP] Server binding to host={os.getenv('HOST', '0.0.0.0')} port={os.getenv('PORT', 8000)}")
    yield
    print("[SHUTDOWN] Server shutting down...")

if __name__ == "__main__":
    # Production-ready Railway/Vercel binding
    host = os.environ.get("HOST", "0.0.0.0")
    port = int(os.environ.get("PORT", 8000))
    
    # Disable reload in production
    reload = os.getenv("ENV") == "development"
    
    uvicorn.run(
        "app.main:app",
        host=host,
        port=port,
        reload=reload,
        log_level="info",
        workers=1,  # Single worker for Railway
        lifespan="auto"  # Use lifespan context manager
    )
