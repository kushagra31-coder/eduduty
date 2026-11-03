import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

import models
from main import app
from database import get_db


def test_mark_bulk_attendance_and_eligibility_gate():
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
        cls = models.Class(name="CI-1", branch="CSE", year=3)
        db.add(cls)
        db.commit()

        exam = models.MstExam(label="MST-1", class_id=cls.id)
        db.add(exam)
        db.commit()
        exam_id = exam.id

        s_elig = models.Student(roll_number="0827CS211001", name="Alice", class_id=cls.id)
        s_over = models.Student(roll_number="0827CS211002", name="Bob", class_id=cls.id)
        s_inelig = models.Student(roll_number="0827CS211003", name="Charlie", class_id=cls.id)
        db.add_all([s_elig, s_over, s_inelig])
        db.commit()

        s_elig_id = s_elig.id
        s_over_id = s_over.id
        s_inelig_id = s_inelig.id
        db.close()

        # 1. Gate: Calling mark-bulk BEFORE eligibility computed MUST return 409
        res_409 = client.post(
            "/mst/attendance/mark-bulk",
            json={
                "mst_exam_id": exam_id,
                "student_ids": [s_elig_id, s_over_id],
                "status": "Present",
            },
        )
        assert res_409.status_code == 409
        assert "Eligibility not computed" in res_409.json()["detail"]

        # Now compute eligibility records:
        # s_elig -> "Eligible", override=False
        # s_over -> "Not eligible", override=True (permitted by override)
        # s_inelig -> "Not eligible", override=False (blocked)
        db = TestingSessionLocal()
        e1 = models.MstEligibility(student_id=s_elig_id, mst_exam_id=exam_id, status="Eligible", override=False)
        e2 = models.MstEligibility(student_id=s_over_id, mst_exam_id=exam_id, status="Not eligible", override=True)
        e3 = models.MstEligibility(student_id=s_inelig_id, mst_exam_id=exam_id, status="Not eligible", override=False)
        db.add_all([e1, e2, e3])
        db.commit()
        db.close()

        # 2. Call mark-bulk with all 3 students
        res_bulk = client.post(
            "/mst/attendance/mark-bulk",
            json={
                "mst_exam_id": exam_id,
                "student_ids": [s_elig_id, s_over_id, s_inelig_id],
                "status": "Present",
            },
        )
        assert res_bulk.status_code == 200
        data = res_bulk.json()

        # s_elig and s_over must be marked, s_inelig must be skipped
        assert data["marked_count"] == 2
        assert s_elig_id in data["student_ids"]
        assert s_over_id in data["student_ids"]
        assert len(data["skipped"]) == 1
        assert data["skipped"][0]["student_id"] == s_inelig_id

        # 3. Verify single transaction audit logs: exactly one audit row per marked student
        db = TestingSessionLocal()
        logs = db.query(models.AuditLog).filter(
            models.AuditLog.table_name == "mst_attempts",
            models.AuditLog.field_changed == "status"
        ).all()
        assert len(logs) == 2

        # 4. Verify DB attempts table
        att_elig = db.query(models.MstAttempt).filter_by(mst_exam_id=exam_id, student_id=s_elig_id).first()
        att_over = db.query(models.MstAttempt).filter_by(mst_exam_id=exam_id, student_id=s_over_id).first()
        att_inelig = db.query(models.MstAttempt).filter_by(mst_exam_id=exam_id, student_id=s_inelig_id).first()

        assert att_elig is not None and att_elig.status == "Present"
        assert att_over is not None and att_over.status == "Present"
        assert att_inelig is None  # Never marked!
        db.close()
    finally:
        app.dependency_overrides.clear()
