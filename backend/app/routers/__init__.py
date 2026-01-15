"""
Router package initialization
"""
from .auth import router as auth_router
from .player import router as player_router
from .playlist import router as playlist_router

__all__ = ["auth_router", "player_router", "playlist_router"]
