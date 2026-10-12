import jwt
import time
import pytest


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



def test_cannot_spoof_identity_in_duty_assignment(client, db):
    """
    Sending 'changed_by: 999' in body MUST NOT alter the audit actor.
    The actor MUST be derived strictly from the authenticated current_user token.
    """
    token = make_token("uid-coord-456", "coord@eduduty.ac.in", "EXAM_COORDINATOR")
    res = client.post(
        "/mst/duties/auto-schedule/apply",
        json={
            "assignments": [{"mst_exam_id": 1, "room_id": 1, "faculty_id": 1}],
            "changed_by": 99999  # <--- Client attempt to spoof actor ID
        },
        headers={"Authorization": f"Bearer {token}"}
    )
    assert res.status_code == 200
    
    # Check audit log in DB to verify changed_by is current_user.id, NOT spoofed 99999
    import models
    log = db.query(models.AuditLog).filter(models.AuditLog.table_name == "invigilation_duties").order_by(models.AuditLog.id.desc()).first()
    assert log is not None
    assert log.changed_by != 99999
    assert log.changed_by > 0

