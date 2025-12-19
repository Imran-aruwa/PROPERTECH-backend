import uvicorn
import sys
import os

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

if __name__ == "__main__":
    # Check for flags
    use_migrations = "--migrate" in sys.argv or os.getenv("RUN_MIGRATIONS") == "true"
    reload = "--reload" in sys.argv

    # Initialize database
    if use_migrations:
        if not run_migrations():
            print("[WARN] Falling back to direct table creation...")
            init_database()
    else:
        # For local dev, use direct init (faster)
        init_database()

    # Start server
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=reload,
        log_level="info"
    )
