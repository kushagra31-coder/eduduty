import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

import models
import crud
from main import app
from database import get_db


def test_override_audit_values_and_reason_enforcement():
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

    try:
        db = TestingSessionLocal()
        cls = models.Class(name="CS-A", branch="CS", year=3)
        st = models.Student(roll_number="0827CS211005", name="Test Student", class_id=1)
        exam = models.MstExam(label="MST-1")
        db.add_all([cls, st, exam])
        db.commit()

        el = models.MstEligibility(
            student_id=st.id,
            mst_exam_id=exam.id,
            status="Not eligible",
            override=False,
            override_reason=None,
        )
        db.add(el)
        db.commit()
        el_id = el.id
        db.close()

        # 1. Non-empty reason enforcement on endpoint
        res_empty = client.post(
            f"/eligibility/override/{el_id}",
            json={"override": True, "reason": "   "},
        )
        assert res_empty.status_code == 400
        assert "non-empty reason is required" in res_empty.json()["detail"]

        # 2. Grant override
        res_grant = client.post(
            f"/eligibility/override/{el_id}",
            json={"override": True, "reason": "Medical certificate from hospital"},
        )
        assert res_grant.status_code == 200

        # Check audit log for grant
        db = TestingSessionLocal()
        log1 = db.query(models.AuditLog).filter_by(record_id=el_id).order_by(models.AuditLog.id.desc()).first()
        assert log1.old_value == "False"
        assert log1.new_value == "True"
        assert log1.reason == "Medical certificate from hospital"
        db.close()

        # 3. Update reason while override is True
        res_update = client.post(
            f"/eligibility/override/{el_id}",
            json={"override": True, "reason": "Updated: Approved by HOD"},
        )
        assert res_update.status_code == 200

        db = TestingSessionLocal()
        log2 = db.query(models.AuditLog).filter_by(record_id=el_id).order_by(models.AuditLog.id.desc()).first()
        # When already True, old_value must be "True", not fake "False"
        assert log2.old_value == "True"
        assert log2.new_value == "True"
        assert log2.reason == "Updated: Approved by HOD"
        db.close()

        # 4. Remove override
        res_remove = client.post(
            f"/eligibility/override/{el_id}",
            json={"override": False, "reason": "Disapproved upon re-check"},
        )
        assert res_remove.status_code == 200

        db = TestingSessionLocal()
        rec = db.query(models.MstEligibility).filter_by(id=el_id).first()
        assert rec.override is False
        assert rec.override_reason is None

        log3 = db.query(models.AuditLog).filter_by(record_id=el_id).order_by(models.AuditLog.id.desc()).first()
        assert log3.old_value == "True"
        assert log3.new_value == "False"
        assert log3.reason == "Disapproved upon re-check"
        db.close()
    finally:
        app.dependency_overrides.clear()
