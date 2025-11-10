from fastapi import FastAPI
from fastapi.middleware.cors import CORSMiddleware
from app.config import settings
from app.api import auth, properties
from app.database import Base, engine

# Create database tables
Base.metadata.create_all(bind=engine)

app = FastAPI(
    title=settings.PROJECT_NAME,
    version=settings.VERSION,
    openapi_url=f"{settings.API_V1_STR}/openapi.json"
)

# CORS middleware
app.add_middleware(
    CORSMiddleware,
    allow_origins=[settings.FRONTEND_URL, "https://propertech-indol.vercel.app"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Health check
@app.get("/")
def root():
    return {
        "message": "PROPERTECH API is running",
        "version": settings.VERSION,
        "docs": "/docs"
    }

# Include routers
app.include_router(auth.router, prefix=f"{settings.API_V1_STR}/auth", tags=["authentication"])
app.include_router(properties.router, prefix=f"{settings.API_V1_STR}/properties", tags=["properties"])

if __name__ == "__main__":
    import uvicorn
    uvicorn.run("app.main:app",host="127.0.0.1"
, port=5050, reload=True)