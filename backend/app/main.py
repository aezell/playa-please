"""
Playa Please - Main FastAPI Application

A personalized music player that integrates with YouTube Music.
"""
import logging
import os
from pathlib import Path
from contextlib import asynccontextmanager

from fastapi import FastAPI, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse, JSONResponse

from .config import get_settings
from .database import init_db
from .routers import auth_router, player_router, playlist_router

# Configure logging
logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s"
)
logger = logging.getLogger(__name__)

settings = get_settings()


@asynccontextmanager
async def lifespan(app: FastAPI):
    """
    Application lifespan handler.

    Runs on startup:
    - Initialize database tables

    Runs on shutdown:
    - Cleanup resources
    """
    # Startup
    logger.info("Starting Playa Please API...")
    init_db()
    logger.info("Database initialized")

    yield

    # Shutdown
    logger.info("Shutting down Playa Please API...")


# Create FastAPI application
app = FastAPI(
    title="Playa Please",
    description="A personalized music player with YouTube Music integration",
    version="1.0.0",
    lifespan=lifespan,
)

# Configure CORS for development
# Allow all origins in development
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],  # Allow all origins for development
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# Include routers
app.include_router(auth_router)
app.include_router(player_router)
app.include_router(playlist_router)


@app.get("/api/health")
async def health_check():
    """
    Health check endpoint.

    Returns:
        Simple status object indicating the API is running
    """
    return {
        "status": "healthy",
        "version": "1.0.0",
        "service": "playa-please"
    }


@app.exception_handler(Exception)
async def global_exception_handler(request: Request, exc: Exception):
    """
    Global exception handler for unhandled errors.

    Logs the error and returns a generic error response.
    """
    logger.error(f"Unhandled exception: {exc}", exc_info=True)
    return JSONResponse(
        status_code=500,
        content={
            "detail": "An internal error occurred",
            "type": type(exc).__name__
        }
    )


# Static file serving for production
# In production, serve the built frontend from ../frontend/dist
frontend_dist_path = Path(__file__).parent.parent.parent / "frontend" / "dist"

if frontend_dist_path.exists():
    logger.info(f"Serving static files from {frontend_dist_path}")

    # Mount static assets
    assets_path = frontend_dist_path / "assets"
    if assets_path.exists():
        app.mount("/assets", StaticFiles(directory=str(assets_path)), name="assets")

    # Serve index.html for all non-API routes (SPA fallback)
    @app.get("/{full_path:path}")
    async def serve_spa(request: Request, full_path: str):
        """
        Serve the SPA frontend for non-API routes.

        This enables client-side routing by serving index.html
        for all paths that don't match an API route.
        """
        # Don't serve SPA for API routes or auth routes
        if full_path.startswith("api/") or full_path.startswith("auth/"):
            return JSONResponse(
                status_code=404,
                content={"detail": "Not found"}
            )

        # Check if there's a static file at this path
        static_file = frontend_dist_path / full_path
        if static_file.exists() and static_file.is_file():
            return FileResponse(str(static_file))

        # Otherwise serve index.html for SPA routing
        index_path = frontend_dist_path / "index.html"
        if index_path.exists():
            return FileResponse(str(index_path))

        return JSONResponse(
            status_code=404,
            content={"detail": "Not found"}
        )
else:
    logger.info("Frontend dist not found, running in API-only mode")


# Development server entry point
if __name__ == "__main__":
    import uvicorn
    uvicorn.run(
        "app.main:app",
        host="0.0.0.0",
        port=8000,
        reload=True,
        log_level="info"
    )
