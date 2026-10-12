import jwt
import time
import pytest
import models



from tests.conftest import TEST_JWT_SECRET


def make_token(uid: str, email: str, role: str) -> str:
    payload = {
        "sub": uid,
        "email": email,
        "user_metadata": {"role": role},
        "iss": "https://test.supabase.co/auth/v1",
        "aud": "authenticated",
        "exp": int(time.time()) + 3600
    }
    return jwt.encode(payload, TEST_JWT_SECRET, algorithm="HS256")



def test_coordinator_can_override_eligibility(client, db):
    """EXAM_COORDINATOR role possesses 'eligibility.override' permission."""
    token = make_token("uid-coord-456", "coord@eduduty.ac.in", "EXAM_COORDINATOR")
    el = models.MstEligibility(id=99, student_id=1, mst_exam_id=1, overall_pct=48.0, status="Borderline")
    db.add(el)
    db.commit()

    res = client.post(
        "/eligibility/override/99",
        json={"override": True, "reason": "Approved medical certificate"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200
    assert res.json()["message"] == "Override applied successfully"


def test_viewer_cannot_override_eligibility(client):
    """VIEWER role lacks 'eligibility.override' permission and receives HTTP 403."""
    token = make_token("uid-view-999", "viewer@eduduty.ac.in", "VIEWER")
    res = client.post(
        "/eligibility/override/99",
        json={"override": True, "reason": "Unauthorized attempt"},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 403
    data = res.json()
    assert data["detail"]["error"]["code"] == "FORBIDDEN"
    assert "not authorized" in data["detail"]["error"]["message"].lower()


def test_faculty_cannot_generate_seating(client):
    """FACULTY role lacks 'seating.generate' permission."""
    token = make_token("uid-fac-789", "fac@eduduty.ac.in", "FACULTY")
    res = client.post(
        "/mst/seating/generate",
        json={"mst_exam_id": 1, "room_ids": [1]},
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 403
    assert res.json()["detail"]["error"]["code"] == "FORBIDDEN"
