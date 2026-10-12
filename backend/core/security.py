import os
import time
import jwt
from typing import Set, Dict, Optional
from sqlalchemy.orm import Session
import models

# ── 1. Roles & Permission System ──────────────────────────────────────────────

SUPER_ADMIN = "SUPER_ADMIN"
ADMIN = "ADMIN"
EXAM_COORDINATOR = "EXAM_COORDINATOR"
FACULTY = "FACULTY"
INVIGILATOR = "INVIGILATOR"
VIEWER = "VIEWER"

ALL_ROLES = {SUPER_ADMIN, ADMIN, EXAM_COORDINATOR, FACULTY, INVIGILATOR, VIEWER}

# Centralized Role -> Permissions Mapping Matrix
ROLE_PERMISSIONS: Dict[str, Set[str]] = {
    SUPER_ADMIN: {
        "student.read", "student.create", "student.update", "student.delete",
        "faculty.read", "faculty.manage",
        "exam.read", "exam.create", "exam.update", "exam.approve",
        "attendance.read", "attendance.import", "attendance.mark",
        "eligibility.read", "eligibility.override",
        "seating.read", "seating.generate", "seating.manage",
        "duty.read", "duty.generate", "duty.assign", "duty.override",
        "vt.read", "vt.override",
        "reports.read", "reports.export",
        "audit.read",
        "ai.read", "ai.write",
        "system.manage",
    },
    ADMIN: {
        "student.read", "student.create", "student.update",
        "faculty.read", "faculty.manage",
        "exam.read", "exam.create", "exam.update", "exam.approve",
        "attendance.read", "attendance.import", "attendance.mark",
        "eligibility.read", "eligibility.override",
        "seating.read", "seating.generate", "seating.manage",
        "duty.read", "duty.generate", "duty.assign", "duty.override",
        "vt.read", "vt.override",
        "reports.read", "reports.export",
        "audit.read",
        "ai.read", "ai.write",
    },
    EXAM_COORDINATOR: {
        "student.read",
        "faculty.read",
        "exam.read", "exam.create", "exam.update",
        "attendance.read", "attendance.import", "attendance.mark",
        "eligibility.read", "eligibility.override",
        "seating.read", "seating.generate", "seating.manage",
        "duty.read", "duty.generate", "duty.assign", "duty.override",
        "vt.read", "vt.override",
        "reports.read", "reports.export",
        "audit.read",
        "ai.read", "ai.write",
    },
    FACULTY: {
        "student.read",
        "faculty.read",
        "exam.read",
        "attendance.read", "attendance.mark",
        "seating.read",
        "duty.read",
        "vt.read",
        "reports.read",
        "ai.read",
    },
    INVIGILATOR: {
        "student.read",
        "exam.read",
        "attendance.mark",
        "seating.read",
        "duty.read",
        "reports.read",
    },
    VIEWER: {
        "student.read",
        "faculty.read",
        "exam.read",
        "eligibility.read",
        "seating.read",
        "duty.read",
        "vt.read",
        "reports.read",
    },
}


def has_permission(user_role: str, permission: str) -> bool:
    """Check if the given user role possesses the required permission."""
    if not user_role or user_role not in ROLE_PERMISSIONS:
        return False
    # SUPER_ADMIN retains unrestricted permissions
    if user_role == SUPER_ADMIN:
        return True
    return permission in ROLE_PERMISSIONS.get(user_role, set())


# ── 2. JWT Verification & Identity Resolution ────────────────────────────────

def get_supabase_jwt_secret() -> Optional[str]:
    """Retrieve trusted HMAC secret key. Rejects empty, missing, or fallback anon key strings."""
    secret = os.getenv("SUPABASE_JWT_SECRET")
    if secret:
        secret = secret.strip()
    # Require at least 16 chars for HMAC key; never accept SUPABASE_ANON_KEY as a secret
    if secret and len(secret) >= 16:
        return secret
    return None


def get_allowed_algorithms() -> list[str]:
    """Retrieve allowed JWT signing algorithms."""
    alg_env = os.getenv("SUPABASE_JWT_ALGORITHM", "HS256")
    algs = [a.strip().upper() for a in alg_env.split(",") if a.strip()]
    return algs if algs else ["HS256"]


def get_expected_audience() -> Optional[str]:
    """Retrieve expected audience claim (defaults to 'authenticated')."""
    aud = os.getenv("SUPABASE_JWT_AUDIENCE", "authenticated")
    if aud:
        aud = aud.strip()
        if aud.lower() in ("none", "false", ""):
            return None
        return aud
    return None


def get_expected_issuer() -> Optional[str]:
    """Retrieve expected issuer claim (derived from SUPABASE_URL or SUPABASE_JWT_ISSUER)."""
    iss = os.getenv("SUPABASE_JWT_ISSUER")
    if iss:
        return iss.strip()
    supabase_url = os.getenv("SUPABASE_URL")
    if supabase_url:
        return f"{supabase_url.strip().rstrip('/')}/auth/v1"
    return None


def verify_supabase_jwt(token: str) -> dict:
    """
    Verify and decode a Bearer JWT token issued by Supabase Auth or local dev provider.
    Fails closed: signature verification is strictly enforced.
    Validates algorithm, signature, expiration, issuer, and audience.
    """
    if not token or not token.strip():
        raise ValueError("Missing authentication token")

    token = token.strip()
    if token.lower().startswith("bearer "):
        token = token[7:].strip()

    try:
        header = jwt.get_unverified_header(token)
    except Exception as e:
        raise ValueError(f"Invalid JWT header: {e}")

    alg = header.get("alg")
    allowed_algs = get_allowed_algorithms()
    if not alg or alg.upper() not in allowed_algs or alg.upper() == "NONE":
        raise ValueError(f"Unsupported JWT algorithm '{alg}'")

    secret = get_supabase_jwt_secret()
    public_key = os.getenv("SUPABASE_JWT_PUBLIC_KEY")

    if not secret and not public_key:
        raise ValueError("Authentication configuration missing: SUPABASE_JWT_SECRET or public key is not configured")

    verification_key = public_key if alg.upper() in ("RS256", "ES256") else secret
    if not verification_key:
        raise ValueError("Authentication configuration missing: Verification key for specified algorithm is not configured")

    expected_aud = get_expected_audience()
    expected_iss = get_expected_issuer()

    decode_kwargs = {
        "algorithms": allowed_algs,
        "options": {
            "verify_signature": True,
            "verify_exp": True,
            "verify_aud": bool(expected_aud),
            "verify_iss": bool(expected_iss),
        }
    }
    if expected_aud:
        decode_kwargs["audience"] = expected_aud
    if expected_iss:
        decode_kwargs["issuer"] = expected_iss

    try:
        payload = jwt.decode(token, verification_key, **decode_kwargs)
        return payload
    except jwt.ExpiredSignatureError:
        raise ValueError("Token has expired")
    except jwt.InvalidAudienceError:
        raise ValueError("Invalid token audience")
    except jwt.InvalidIssuerError:
        raise ValueError("Invalid token issuer")
    except jwt.InvalidAlgorithmError:
        raise ValueError(f"Unsupported JWT algorithm '{alg}'")
    except jwt.InvalidSignatureError:
        raise ValueError("Invalid token signature")
    except jwt.InvalidTokenError as e:
        raise ValueError(f"Invalid token signature: {e}")


def get_or_create_user_from_jwt(db: Session, payload: dict) -> models.User:
    """
    Map verified JWT claims to an EduDuty application User model.
    Derives user identity from 'sub' (Supabase UID), 'email', and 'user_metadata'.
    Unknown or unmapped roles default to VIEWER (read-only, minimal privilege).
    """
    sub = payload.get("sub") or payload.get("user_id")
    email = payload.get("email") or (f"user_{sub[:8]}@eduduty.internal" if sub else "unknown@eduduty.internal")
    
    user_metadata = payload.get("user_metadata") or {}
    app_metadata = payload.get("app_metadata") or {}
    
    if not isinstance(user_metadata, dict):
        user_metadata = {}
    if not isinstance(app_metadata, dict):
        app_metadata = {}

    name = user_metadata.get("name") or user_metadata.get("full_name") or email.split("@")[0]
    
    # Extract role from metadata or claims
    role = user_metadata.get("role") or app_metadata.get("role") or payload.get("role")
    
    # Fail-safe RBAC rule: Unknown or unmapped roles default to VIEWER (no elevated permissions)
    if not role or role not in ALL_ROLES:
        role = VIEWER

    # 1. Lookup by supabase_uid
    if sub:
        user = db.query(models.User).filter(models.User.supabase_uid == sub).first()
        if user:
            return user

    # 2. Lookup by email
    user = db.query(models.User).filter(models.User.email == email).first()
    if user:
        if sub and not user.supabase_uid:
            user.supabase_uid = sub
            db.commit()
        return user

    # 3. Create fresh EduDuty user
    user = models.User(
        supabase_uid=sub,
        name=name,
        role=role,
        email=email,
    )
    db.add(user)
    db.commit()
    db.refresh(user)
    return user


# ── 3. Development-Only Demo Identity Provider ────────────────────────────────

DEMO_ACCOUNTS = {
    "coord@eduduty.ac.in": {
        "sub": "00000000-0000-0000-0000-000000000002",
        "name": "Coordinator Demo",
        "role": EXAM_COORDINATOR,
        "faculty_id": None,
    },
    "faculty@eduduty.ac.in": {
        "sub": "00000000-0000-0000-0000-000000000003",
        "name": "Prof. Test Faculty",
        "role": FACULTY,
        "faculty_id": 1,
    },
    "admin@eduduty.ac.in": {
        "sub": "00000000-0000-0000-0000-000000000001",
        "name": "Admin Demo",
        "role": SUPER_ADMIN,
        "faculty_id": None,
    },
    "viewer@eduduty.ac.in": {
        "sub": "00000000-0000-0000-0000-000000000004",
        "name": "Viewer Demo",
        "role": VIEWER,
        "faculty_id": None,
    },
}


def is_demo_auth_enabled() -> bool:
    """
    Check if development-only demo authentication is permitted.
    Strictly disabled by default.
    Hard-disabled if APP_ENV or ENVIRONMENT is production.
    """
    app_env = os.getenv("APP_ENV", os.getenv("ENVIRONMENT", "development")).strip().lower()
    if app_env in ("production", "prod"):
        return False
    val = os.getenv("ENABLE_DEV_DEMO_AUTH", "false").strip().lower()
    return val in ("true", "1", "yes")


def create_demo_jwt(email: str) -> dict:
    """
    Generate a signed JWT for a predefined demo identity.
    Fails closed:
    - Verifies demo auth is explicitly enabled.
    - Strictly checks email against predefined DEMO_ACCOUNTS.
    - Client CANNOT select role, permissions, or sub.
    """
    if not is_demo_auth_enabled():
        raise PermissionError("Demo authentication is disabled in this environment.")

    email_clean = (email or "").strip().lower()
    if email_clean not in DEMO_ACCOUNTS:
        raise ValueError("Invalid demo account. Only preconfigured demo identities are allowed.")

    account = DEMO_ACCOUNTS[email_clean]
    secret = get_supabase_jwt_secret()
    if not secret:
        raise ValueError("Authentication configuration missing: SUPABASE_JWT_SECRET is not configured.")

    now = int(time.time())
    aud = get_expected_audience() or "authenticated"
    iss = get_expected_issuer() or "https://test.supabase.co/auth/v1"

    payload = {
        "sub": account["sub"],
        "email": email_clean,
        "aud": aud,
        "iss": iss,
        "iat": now,
        "exp": now + 3600,
        "role": "authenticated",
        "user_metadata": {
            "name": account["name"],
            "role": account["role"],
        },
        "app_metadata": {
            "role": account["role"],
            "provider": "eduduty-dev-demo",
        },
    }

    token = jwt.encode(payload, secret, algorithm="HS256")
    return {
        "access_token": token,
        "token_type": "bearer",
        "expires_in": 3600,
        "user": {
            "id": account["sub"],
            "email": email_clean,
            "name": account["name"],
            "role": account["role"],
            "faculty_id": account["faculty_id"],
        },
    }


