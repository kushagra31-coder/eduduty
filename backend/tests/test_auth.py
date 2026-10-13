import os
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

import models
import auth
from main import app
from database import get_db


def test_auth_disabled_fails_on_non_local_env(monkeypatch):
    monkeypatch.setenv("ENV", "production")
    monkeypatch.setenv("AUTH_DISABLED", "true")
    with pytest.raises(RuntimeError, match="Security violation: AUTH_DISABLED=true is only allowed when ENV=local"):
        auth.validate_auth_startup()

    # Allowed when ENV is local
    monkeypatch.setenv("ENV", "local")
    monkeypatch.setenv("AUTH_DISABLED", "true")
    # Should not raise
    auth.validate_auth_startup()


def test_auth_role_matrix_and_audit_user():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)

    def override_get_db():
        db = TestingSessionLocal()
        try:
            yield db
        finally:
            db.close()

    app.dependency_overrides[get_db] = override_get_db
    client = TestClient(app)

    db = TestingSessionLocal()
    cls = models.Class(name="CS-A", branch="CS", year=3)
    st = models.Student(roll_number="0827CS211099", name="Auth Test Student", class_id=1)
    exam = models.MstExam(label="MST-1")
    db.add_all([cls, st, exam])
    db.commit()

    elig = models.MstEligibility(
        student_id=st.id,
        mst_exam_id=exam.id,
        status="Not eligible",
        override=False,
    )
    coord_user = models.User(id=101, name="Coordinator User", role="coordinator", email="coord@test.edu")
    fac_user = models.User(id=102, name="Faculty User", role="faculty", email="faculty@test.edu")
    invig_user = models.User(id=103, name="Invigilator User", role="invigilator", email="invig@test.edu")
    db.add_all([elig, coord_user, fac_user, invig_user])
    db.commit()

    coord_token = auth.create_jwt_token(user_id=101, role="coordinator", email="coord@test.edu", name="Coordinator User")
    fac_token = auth.create_jwt_token(user_id=102, role="faculty", email="faculty@test.edu", name="Faculty User")
    invig_token = auth.create_jwt_token(user_id=103, role="invigilator", email="invig@test.edu", name="Invigilator User")

    # 1. Health is public
    res_health = client.get("/health")
    assert res_health.status_code == 200

    # 2. No token on protected route -> 401
    res_no_tok = client.post(
        f"/eligibility/override/{elig.id}",
        json={"override": True, "reason": "Medical ground approval"},
    )
    assert res_no_tok.status_code == 401

    # 3. Faculty token on coordinator/HOD route -> 403
    res_fac = client.post(
        f"/eligibility/override/{elig.id}",
        json={"override": True, "reason": "Medical ground approval"},
        headers={"Authorization": f"Bearer {fac_token}"},
    )
    assert res_fac.status_code == 403

    # 4. Coordinator token -> 200 and audit row has changed_by = coordinator.id
    res_coord = client.post(
        f"/eligibility/override/{elig.id}",
        json={"override": True, "reason": "Medical ground approval"},
        headers={"Authorization": f"Bearer {coord_token}"},
    )
    assert res_coord.status_code == 200

    audit = db.query(models.AuditLog).filter_by(
        table_name="mst_eligibility",
        record_id=elig.id,
        field_changed="override",
    ).first()
    assert audit is not None
    assert audit.changed_by == 101  # Coordinator's user ID

    # 5. Duty routes: faculty gets 403, coordinator gets 200
    res_duty_fac = client.post(
        "/mst/duties/assign",
        json={"mst_exam_id": exam.id, "room_id": 1, "faculty_id": 1},
        headers={"Authorization": f"Bearer {fac_token}"},
    )
    assert res_duty_fac.status_code == 403

    res_duty_coord = client.post(
        "/mst/duties/assign",
        json={"mst_exam_id": exam.id, "room_id": 1, "faculty_id": 1},
        headers={"Authorization": f"Bearer {coord_token}"},
    )
    assert res_duty_coord.status_code == 200

    duty_audit = db.query(models.AuditLog).filter_by(
        table_name="invigilation_duties",
        field_changed="faculty_id",
    ).first()
    assert duty_audit is not None
    assert duty_audit.changed_by == 101

    # 6. /auth/login returns valid token
    login_res = client.post("/auth/login", json={"email": "newcoord@test.edu", "role": "coordinator", "name": "New Coord"})
    assert login_res.status_code == 200
    tok_data = login_res.json()
    assert "access_token" in tok_data
    decoded = auth.decode_jwt_token(tok_data["access_token"])
    assert decoded["email"] == "newcoord@test.edu"
    assert decoded["role"] == "coordinator"

    app.dependency_overrides.clear()
