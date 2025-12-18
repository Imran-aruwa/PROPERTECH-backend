import uvicorn
import sys
import os

if __name__ == "__main__":
    # Initialize database tables before starting server
    from app.database import init_db
    print("[STARTUP] Initializing database tables...")
    init_db()
    print("[STARTUP] Database initialization complete!")
    
    reload = "--reload" in sys.argv
    uvicorn.run(
        "app.main:app",
        host="127.0.0.1",
        port=8000,
        reload=reload,
        log_level="info"
    )
