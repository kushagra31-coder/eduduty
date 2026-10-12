import os
import time
import jwt
import pytest
from tests.conftest import TEST_JWT_SECRET


def make_test_token(
    uid: str = "uid-admin-123",
    email: str = "admin@eduduty.ac.in",
    role: str = "SUPER_ADMIN",
    secret: str = TEST_JWT_SECRET,
    alg: str = "HS256",
    iss: str = "https://test.supabase.co/auth/v1",
    aud: str = "authenticated",
    exp: int = None,
) -> str:
    if exp is None:
        exp = int(time.time()) + 3600
    payload = {
        "sub": uid,
        "email": email,
        "user_metadata": {"role": role},
        "iss": iss,
        "aud": aud,
        "exp": exp,
    }
    return jwt.encode(payload, secret, algorithm=alg)


def test_unauthenticated_request_rejected(client):
    """Requests without Authorization header must receive HTTP 401."""
    res = client.get("/eligibility/1")
    assert res.status_code == 401
    data = res.json()
    assert "error" in data["detail"]
    assert data["detail"]["error"]["code"] == "UNAUTHORIZED"


def test_invalid_token_rejected(client):
    """Requests with malformed JWT tokens must receive HTTP 401."""
    res = client.get("/eligibility/1", headers={"Authorization": "Bearer malformed.jwt.token"})
    assert res.status_code == 401
    data = res.json()
    assert "error" in data["detail"]
    assert data["detail"]["error"]["code"] == "INVALID_TOKEN"


def test_valid_token_authenticated(client):
    """Requests with valid JWT tokens must successfully authenticate."""
    valid_token = make_test_token()
    res = client.get("/eligibility/1", headers={"Authorization": f"Bearer {valid_token}"})
    assert res.status_code == 200


def test_forged_signature_rejected(client):
    """Tokens signed with a forged/incorrect secret key must be rejected with HTTP 401."""
    forged_token = make_test_token(secret="forged-secret-key-that-does-not-match-32-chars")
    res = client.get("/eligibility/1", headers={"Authorization": f"Bearer {forged_token}"})
    assert res.status_code == 401
    data = res.json()
    assert data["detail"]["error"]["code"] == "INVALID_TOKEN"
    assert "invalid token signature" in data["detail"]["error"]["message"].lower()


def test_expired_token_rejected(client):
    """Requests with expired JWT tokens must be rejected with HTTP 401."""
    expired_token = make_test_token(exp=int(time.time()) - 3600)
    res = client.get("/eligibility/1", headers={"Authorization": f"Bearer {expired_token}"})
    assert res.status_code == 401
    data = res.json()
    assert "expired" in data["detail"]["error"]["message"].lower()


def test_wrong_issuer_rejected(client):
    """Tokens with an unexpected issuer claim must be rejected with HTTP 401."""
    wrong_iss_token = make_test_token(iss="https://untrusted-issuer.com/auth/v1")
    res = client.get("/eligibility/1", headers={"Authorization": f"Bearer {wrong_iss_token}"})
    assert res.status_code == 401
    data = res.json()
    assert "invalid token issuer" in data["detail"]["error"]["message"].lower()


def test_wrong_audience_rejected(client):
    """Tokens with an unexpected audience claim must be rejected with HTTP 401."""
    wrong_aud_token = make_test_token(aud="untrusted-audience")
    res = client.get("/eligibility/1", headers={"Authorization": f"Bearer {wrong_aud_token}"})
    assert res.status_code == 401
    data = res.json()
    assert "invalid token audience" in data["detail"]["error"]["message"].lower()


def test_missing_verification_config_fails_closed(client, monkeypatch):
    """When JWT verification secret is unconfigured/missing, requests fail closed with HTTP 401."""
    monkeypatch.delenv("SUPABASE_JWT_SECRET", raising=False)
    monkeypatch.delenv("SUPABASE_JWT_PUBLIC_KEY", raising=False)
    valid_token = make_test_token()
    res = client.get("/eligibility/1", headers={"Authorization": f"Bearer {valid_token}"})
    assert res.status_code == 401
    data = res.json()
    assert "configuration missing" in data["detail"]["error"]["message"].lower()


def test_unsupported_algorithm_rejected(client):
    """Tokens with unsupported algorithms (e.g. HS512 or none) must be rejected with HTTP 401."""
    token_hs512 = make_test_token(alg="HS512")
    res = client.get("/eligibility/1", headers={"Authorization": f"Bearer {token_hs512}"})
    assert res.status_code == 401
    data = res.json()
    assert "unsupported jwt algorithm" in data["detail"]["error"]["message"].lower()


def test_unknown_role_defaults_to_viewer(client):
    """Unknown or unmapped roles default to VIEWER (minimal read-only) and receive HTTP 403 on protected routes."""
    unknown_role_token = make_test_token(uid="uid-unknown-999", email="unknown@eduduty.ac.in", role="UNKNOWN_HACKER_ROLE")
    # VIEWER can read eligibility (HTTP 200)
    res_read = client.get("/eligibility/1", headers={"Authorization": f"Bearer {unknown_role_token}"})
    assert res_read.status_code == 200
    
    # VIEWER cannot generate seating (HTTP 403)
    res_seating = client.post(
        "/mst/seating/generate",
        json={"mst_exam_id": 1, "room_ids": [1]},
        headers={"Authorization": f"Bearer {unknown_role_token}"}
    )
    assert res_seating.status_code == 403
    data = res_seating.json()
    assert data["detail"]["error"]["code"] == "FORBIDDEN"
    assert "role 'viewer' is not authorized" in data["detail"]["error"]["message"].lower()


# ── Demo Auth & Escalation Prevention Tests ───────────────────────────────────

def test_demo_auth_disabled_by_default(client, monkeypatch):
    """When ENABLE_DEV_DEMO_AUTH is disabled or missing, demo login returns HTTP 403."""
    monkeypatch.setenv("ENABLE_DEV_DEMO_AUTH", "false")
    res = client.post("/auth/demo-login", json={"email": "coord@eduduty.ac.in"})
    assert res.status_code == 403
    data = res.json()
    assert data["detail"]["error"]["code"] == "DEMO_AUTH_DISABLED"


def test_demo_auth_production_fail_closed(client, monkeypatch):
    """In production environments, demo login must fail closed with HTTP 403 regardless of flags."""
    monkeypatch.setenv("ENABLE_DEV_DEMO_AUTH", "true")
    monkeypatch.setenv("APP_ENV", "production")
    res = client.post("/auth/demo-login", json={"email": "coord@eduduty.ac.in"})
    assert res.status_code == 403
    data = res.json()
    assert data["detail"]["error"]["code"] == "DEMO_AUTH_DISABLED"


def test_demo_auth_unauthorized_email_rejected(client, monkeypatch):
    """Attempting to log into an arbitrary or unwhitelisted email is rejected with HTTP 401."""
    monkeypatch.setenv("ENABLE_DEV_DEMO_AUTH", "true")
    monkeypatch.setenv("APP_ENV", "development")
    res = client.post("/auth/demo-login", json={"email": "intruder@malicious.com"})
    assert res.status_code == 401
    data = res.json()
    assert data["detail"]["error"]["code"] == "INVALID_DEMO_ACCOUNT"


def test_demo_auth_role_escalation_impossible(client, monkeypatch):
    """
    Client cannot inject or escalate roles. Submitting role='SUPER_ADMIN' for a viewer or coordinator
    must result in the server issuing a token strictly matching the server-configured role.
    """
    monkeypatch.setenv("ENABLE_DEV_DEMO_AUTH", "true")
    monkeypatch.setenv("APP_ENV", "development")
    # Attacker tries to pass role='SUPER_ADMIN' for viewer account
    res = client.post(
        "/auth/demo-login",
        json={"email": "viewer@eduduty.ac.in", "role": "SUPER_ADMIN", "is_admin": True}
    )
    assert res.status_code == 200
    token_data = res.json()
    assert token_data["user"]["role"] == "VIEWER"

    # Verify that the minted token actually decodes to VIEWER and cannot perform admin actions
    token = token_data["access_token"]
    res_seating = client.post(
        "/mst/seating/generate",
        json={"mst_exam_id": 1, "room_ids": [1]},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res_seating.status_code == 403
    assert res_seating.json()["detail"]["error"]["code"] == "FORBIDDEN"


def test_demo_auth_valid_session_end_to_end(client, monkeypatch):
    """
    Legitimate demo login for coordinator returns a verified token that successfully
    authorizes coordinator operations across the real FastAPI dependency pipeline.
    """
    monkeypatch.setenv("ENABLE_DEV_DEMO_AUTH", "true")
    monkeypatch.setenv("APP_ENV", "development")
    res = client.post("/auth/demo-login", json={"email": "coord@eduduty.ac.in"})
    assert res.status_code == 200
    token_data = res.json()
    assert "access_token" in token_data
    token = token_data["access_token"]

    # Verify this token authenticates and accesses coordinator endpoints
    res_exams = client.get("/mst/exams", headers={"Authorization": f"Bearer {token}"})
    assert res_exams.status_code == 200
    assert isinstance(res_exams.json(), list)


def test_auth_status_endpoint(client, monkeypatch):
    """GET /auth/status accurately reports configuration without leaking secrets."""
    monkeypatch.setenv("ENABLE_DEV_DEMO_AUTH", "true")
    monkeypatch.setenv("APP_ENV", "development")
    res = client.get("/auth/status")
    assert res.status_code == 200
    data = res.json()
    assert data["demo_auth_enabled"] is True
    assert len(data["demo_accounts"]) >= 4
    # Ensure no secrets or tokens are in status output
    assert "secret" not in str(data).lower()
    assert "access_token" not in str(data)




