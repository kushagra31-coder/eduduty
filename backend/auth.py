import os
import datetime
from typing import Optional
import jwt
from fastapi import Depends, HTTPException, Security, status
from fastapi.security import HTTPBearer, HTTPAuthorizationCredentials
from sqlalchemy.orm import Session
from pydantic import BaseModel

import models
from database import get_db

# ── Env and Configuration ─────────────────────────────────────────────────────

ENV = os.getenv("ENV", "local").strip().lower()
AUTH_DISABLED = os.getenv("AUTH_DISABLED", "false").strip().lower() in ("true", "1", "yes")

def validate_auth_startup():
    """Verify that AUTH_DISABLED is only ever used in ENV=local."""
    curr_env = os.getenv("ENV", "local").strip().lower()
    auth_off = os.getenv("AUTH_DISABLED", "false").strip().lower() in ("true", "1", "yes")
    if auth_off and curr_env != "local":
        raise RuntimeError(
            f"Security violation: AUTH_DISABLED=true is only allowed when ENV=local (current ENV='{curr_env}')."
        )

# Run check on import
validate_auth_startup()

JWT_SECRET = (
    os.getenv("SUPABASE_JWT_SECRET")
    or os.getenv("JWT_SECRET")
    or "eduduty-dev-jwt-secret-key-32-chars-long-minimum-for-security!"
)
JWT_ALGORITHM = "HS256"

security = HTTPBearer(auto_error=False)

ROLES = {"hod", "coordinator", "faculty", "invigilator"}


class LoginRequest(BaseModel):
    email: str
    password: Optional[str] = None
    role: Optional[str] = "coordinator"
    name: Optional[str] = None


class TokenResponse(BaseModel):
    access_token: str
    token_type: str = "bearer"
    role: str
    user_id: int
    name: str


def create_jwt_token(
    user_id: int,
    role: str,
    email: str = "",
    name: str = "",
    expires_delta: Optional[datetime.timedelta] = None,
) -> str:
    if expires_delta:
        exp = datetime.datetime.now(datetime.timezone.utc) + expires_delta
    else:
        exp = datetime.datetime.now(datetime.timezone.utc) + datetime.timedelta(days=7)

    payload = {
        "sub": str(user_id),
        "user_id": user_id,
        "role": role,
        "email": email,
        "name": name,
        "exp": exp,
        "iat": datetime.datetime.now(datetime.timezone.utc),
    }
    return jwt.encode(payload, JWT_SECRET, algorithm=JWT_ALGORITHM)


def decode_jwt_token(token: str) -> dict:
    try:
        return jwt.decode(
            token,
            JWT_SECRET,
            algorithms=[JWT_ALGORITHM, "HS256"],
            options={"verify_aud": False},
        )
    except jwt.ExpiredSignatureError:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Token has expired",
            headers={"WWW-Authenticate": "Bearer"},
        )
    except Exception as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail=f"Could not validate credentials: {e}",
            headers={"WWW-Authenticate": "Bearer"},
        )


def get_current_user(
    credentials: Optional[HTTPAuthorizationCredentials] = Security(security),
    db: Session = Depends(get_db),
) -> models.User:
    """
    Authenticate request via Supabase/Bearer JWT.
    If AUTH_DISABLED is true AND ENV is local, a dev coordinator is provided.
    Otherwise, raises 401 if missing/invalid.
    """
    curr_env = os.getenv("ENV", "local").strip().lower()
    auth_off = os.getenv("AUTH_DISABLED", "false").strip().lower() in ("true", "1", "yes")

    if not credentials or not credentials.credentials:
        if auth_off and curr_env == "local":
            dev_user = db.query(models.User).filter_by(email="dev@eduduty.local").first()
            if not dev_user:
                dev_user = models.User(name="Dev Coordinator", role="coordinator", email="dev@eduduty.local")
                db.add(dev_user)
                db.commit()
                db.refresh(dev_user)
            return dev_user

        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail="Authentication token required",
            headers={"WWW-Authenticate": "Bearer"},
        )

    payload = decode_jwt_token(credentials.credentials)

    sub = payload.get("sub") or payload.get("user_id")
    email = payload.get("email") or f"user_{sub}@eduduty.local"
    name = payload.get("name") or payload.get("user_metadata", {}).get("name") or f"User {sub}"
    role = (
        payload.get("role")
        or payload.get("app_metadata", {}).get("role")
        or payload.get("user_metadata", {}).get("role")
        or "faculty"
    ).lower()

    if role not in ROLES:
        role = "faculty"

    user = None
    if sub and str(sub).isdigit():
        user = db.query(models.User).filter_by(id=int(sub)).first()
    if not user and email:
        user = db.query(models.User).filter_by(email=email).first()

    if not user:
        user = models.User(name=name, role=role, email=email)
        db.add(user)
        db.commit()
        db.refresh(user)
    else:
        if role and user.role != role:
            user.role = role
            db.commit()
            db.refresh(user)

    return user


def require_role(*allowed_roles: str):
    """Dependency factory checking that current user has one of allowed_roles."""
    allowed_set = {r.lower() for r in allowed_roles}

    def _role_checker(user: models.User = Depends(get_current_user)) -> models.User:
        if user.role.lower() not in allowed_set:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail=f"Access denied: user role '{user.role}' not permitted. Required: {sorted(allowed_set)}",
            )
        return user

    return _role_checker
