"""
Authentication router - Google OAuth 2.0 implementation

Handles:
- OAuth login flow
- OAuth callback and token storage
- Session management
- Current user info
"""
import secrets
from datetime import datetime, timedelta
from typing import Optional
from urllib.parse import urlencode

from fastapi import APIRouter, Depends, HTTPException, Response, Request, status
from fastapi.responses import RedirectResponse
from sqlalchemy.orm import Session
from itsdangerous import URLSafeTimedSerializer, BadSignature, SignatureExpired
import httpx

from ..config import get_settings
from ..database import get_db
from ..models import User
from ..schemas import User as UserSchema, AuthStatus

router = APIRouter(prefix="/auth", tags=["auth"])
settings = get_settings()

# Session serializer for signing cookies
serializer = URLSafeTimedSerializer(settings.secret_key)

# Google OAuth endpoints
GOOGLE_AUTH_URL = "https://accounts.google.com/o/oauth2/v2/auth"
GOOGLE_TOKEN_URL = "https://oauth2.googleapis.com/token"
GOOGLE_USERINFO_URL = "https://www.googleapis.com/oauth2/v2/userinfo"

# OAuth scopes needed for YouTube Music
SCOPES = [
    "openid",
    "email",
    "profile",
    "https://www.googleapis.com/auth/youtube",
    "https://www.googleapis.com/auth/youtube.readonly",
]

# Session cookie settings
SESSION_COOKIE_NAME = "session"
SESSION_MAX_AGE = 60 * 60 * 24 * 30  # 30 days in seconds


def create_session_token(user_id: str) -> str:
    """Create a signed session token for the user."""
    return serializer.dumps({"user_id": user_id})


def verify_session_token(token: str) -> Optional[str]:
    """
    Verify and decode a session token.

    Returns:
        User ID if valid, None otherwise
    """
    try:
        data = serializer.loads(token, max_age=SESSION_MAX_AGE)
        return data.get("user_id")
    except (BadSignature, SignatureExpired):
        return None


async def get_current_user(
    request: Request,
    db: Session = Depends(get_db)
) -> Optional[User]:
    """
    Dependency to get current authenticated user from session cookie.

    Returns:
        User model if authenticated, None otherwise
    """
    session_token = request.cookies.get(SESSION_COOKIE_NAME)
    if not session_token:
        return None

    user_id = verify_session_token(session_token)
    if not user_id:
        return None

    user = db.query(User).filter(User.id == user_id).first()
    return user


async def require_current_user(
    user: Optional[User] = Depends(get_current_user)
) -> User:
    """
    Dependency that requires an authenticated user.

    Raises:
        HTTPException: 401 if not authenticated
    """
    if not user:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Not authenticated"
        )
    return user


@router.get("/login")
async def login(request: Request):
    """
    Redirect to Google OAuth consent screen.

    This initiates the OAuth flow by redirecting the user to Google's
    authorization page with the appropriate scopes.
    """
    # Generate state for CSRF protection
    state = secrets.token_urlsafe(32)

    # Store state in a temporary cookie for verification
    callback_url = f"{settings.backend_url}/auth/callback"

    params = {
        "client_id": settings.google_client_id,
        "redirect_uri": callback_url,
        "response_type": "code",
        "scope": " ".join(SCOPES),
        "access_type": "offline",  # Request refresh token
        "prompt": "consent",  # Always show consent to get refresh token
        "state": state,
    }

    auth_url = f"{GOOGLE_AUTH_URL}?{urlencode(params)}"

    response = RedirectResponse(url=auth_url, status_code=status.HTTP_302_FOUND)

    # Store state in cookie for CSRF verification
    response.set_cookie(
        key="oauth_state",
        value=state,
        max_age=600,  # 10 minutes
        httponly=True,
        samesite="lax",
    )

    return response


@router.get("/callback")
async def callback(
    request: Request,
    code: Optional[str] = None,
    state: Optional[str] = None,
    error: Optional[str] = None,
    db: Session = Depends(get_db),
):
    """
    Handle OAuth callback from Google.

    Exchanges the authorization code for tokens, fetches user info,
    creates/updates user in database, and sets session cookie.
    """
    # Check for errors
    if error:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail=f"OAuth error: {error}"
        )

    if not code:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No authorization code provided"
        )

    # Verify state for CSRF protection
    stored_state = request.cookies.get("oauth_state")
    if not stored_state or stored_state != state:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid state parameter"
        )

    # Exchange code for tokens
    callback_url = f"{settings.backend_url}/auth/callback"

    async with httpx.AsyncClient() as client:
        token_response = await client.post(
            GOOGLE_TOKEN_URL,
            data={
                "client_id": settings.google_client_id,
                "client_secret": settings.google_client_secret,
                "code": code,
                "grant_type": "authorization_code",
                "redirect_uri": callback_url,
            },
        )

        if token_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail=f"Failed to exchange code for tokens: {token_response.text}"
            )

        token_data = token_response.json()

    access_token = token_data.get("access_token")
    refresh_token = token_data.get("refresh_token")
    expires_in = token_data.get("expires_in", 3600)

    if not access_token:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="No access token in response"
        )

    # Calculate token expiry
    token_expiry = datetime.utcnow() + timedelta(seconds=expires_in)

    # Fetch user info from Google
    async with httpx.AsyncClient() as client:
        userinfo_response = await client.get(
            GOOGLE_USERINFO_URL,
            headers={"Authorization": f"Bearer {access_token}"},
        )

        if userinfo_response.status_code != 200:
            raise HTTPException(
                status_code=status.HTTP_400_BAD_REQUEST,
                detail="Failed to fetch user info"
            )

        userinfo = userinfo_response.json()

    # Create or update user
    user_id = userinfo.get("id")
    email = userinfo.get("email")
    name = userinfo.get("name", email)
    picture = userinfo.get("picture")

    if not user_id or not email:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Invalid user info from Google"
        )

    # Check if user exists
    user = db.query(User).filter(User.id == user_id).first()

    if user:
        # Update existing user
        user.email = email
        user.name = name
        user.picture = picture
        user.access_token = access_token
        user.refresh_token = refresh_token or user.refresh_token  # Keep old if not provided
        user.token_expiry = token_expiry
    else:
        # Create new user
        user = User(
            id=user_id,
            email=email,
            name=name,
            picture=picture,
            access_token=access_token,
            refresh_token=refresh_token,
            token_expiry=token_expiry,
        )
        db.add(user)

    db.commit()
    db.refresh(user)

    # Create session token
    session_token = create_session_token(user.id)

    # Redirect to frontend with session cookie
    response = RedirectResponse(
        url=settings.frontend_url,
        status_code=status.HTTP_302_FOUND
    )

    # Set session cookie
    response.set_cookie(
        key=SESSION_COOKIE_NAME,
        value=session_token,
        max_age=SESSION_MAX_AGE,
        httponly=True,
        samesite="lax",
        secure=False,  # Set to True in production with HTTPS
    )

    # Clear OAuth state cookie
    response.delete_cookie("oauth_state")

    return response


@router.post("/logout")
async def logout(response: Response):
    """
    Log out the current user by clearing the session cookie.
    """
    response.delete_cookie(SESSION_COOKIE_NAME)
    return {"success": True, "message": "Logged out successfully"}


@router.get("/me", response_model=AuthStatus)
async def get_me(user: Optional[User] = Depends(get_current_user)):
    """
    Get current user info.

    Returns authentication status and user details if logged in.
    """
    if not user:
        return AuthStatus(authenticated=False, user=None)

    return AuthStatus(
        authenticated=True,
        user=UserSchema(
            id=user.id,
            email=user.email,
            name=user.name,
            picture=user.picture,
        )
    )


@router.post("/refresh")
async def refresh_tokens(
    user: User = Depends(require_current_user),
    db: Session = Depends(get_db),
):
    """
    Refresh the user's Google OAuth tokens.

    This endpoint can be called to proactively refresh tokens
    before they expire.
    """
    from ..services.ytmusic import refresh_user_tokens

    success = refresh_user_tokens(db, user)

    if not success:
        raise HTTPException(
            status_code=status.HTTP_400_BAD_REQUEST,
            detail="Failed to refresh tokens"
        )

    return {"success": True, "message": "Tokens refreshed"}
