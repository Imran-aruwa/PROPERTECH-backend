
import uvicorn
import sys
import os

if __name__ == "__main__":
    reload = "--reload" in sys.argv
    
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=reload,
        log_level="info"
    )
