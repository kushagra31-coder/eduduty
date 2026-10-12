import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

import models
from main import app
from database import get_db


def test_seating_and_rollcall_eligibility_gate():
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
        room = models.Room(room_number="R101", capacity=10)
        exam = models.MstExam(label="MST-1", class_id=1)

        # 4 students:
        # s1: batch 1, eligible
        # s2: batch 2, ineligible
        # s3: batch 2, ineligible but overridden -> eligible
        # s4: batch 1, borderline -> ineligible
        s1 = models.Student(roll_number="0827CS211001", name="Alice", class_id=1, batch_number=1, active=True)
        s2 = models.Student(roll_number="0827CS211002", name="Bob", class_id=1, batch_number=2, active=True)
        s3 = models.Student(roll_number="0827CS211003", name="Charlie", class_id=1, batch_number=2, active=True)
        s4 = models.Student(roll_number="0827CS211004", name="David", class_id=1, batch_number=1, active=True)

        db.add_all([cls, room, exam, s1, s2, s3, s4])
        db.commit()
        exam_id = exam.id
        room_id = room.id
        s1_id, s2_id, s3_id, s4_id = s1.id, s2.id, s3.id, s4.id
        db.close()

        # 1. Calling seating/generate or rollcall BEFORE eligibility exists MUST return 409
        res_seat_409 = client.post(
            "/mst/seating/generate",
            json={"mst_exam_id": exam_id, "room_ids": [room_id]},
        )
        assert res_seat_409.status_code == 409
        assert "No eligibility records found" in res_seat_409.json()["detail"]

        res_roll_409 = client.get(f"/mst/attendance/rollcall/{exam_id}")
        assert res_roll_409.status_code == 409
        assert "No eligibility records found" in res_roll_409.json()["detail"]

        # Now insert eligibility records
        db = TestingSessionLocal()
        el1 = models.MstEligibility(student_id=s1_id, mst_exam_id=exam_id, status="Eligible", override=False)
        el2 = models.MstEligibility(student_id=s2_id, mst_exam_id=exam_id, status="Not eligible", override=False)
        el3 = models.MstEligibility(student_id=s3_id, mst_exam_id=exam_id, status="Not eligible", override=True, override_reason="Medical")
        el4 = models.MstEligibility(student_id=s4_id, mst_exam_id=exam_id, status="Borderline", override=False)
        db.add_all([el1, el2, el3, el4])
        db.commit()
        db.close()

        # 2. Call seating generation with eligibility gate
        res_seat = client.post(
            "/mst/seating/generate",
            json={"mst_exam_id": exam_id, "room_ids": [room_id]},
        )
        assert res_seat.status_code == 200
        data_seat = res_seat.json()

        # Only 2 students eligible: s1 and s3
        assert data_seat["students_seated"] == 2
        assert "0827CS211002" in data_seat["excluded"]  # Bob excluded
        assert "0827CS211004" in data_seat["excluded"]  # David excluded
        assert len(data_seat["excluded"]) == 2

        # 3. Call roll-call with eligibility gate
        res_roll = client.get(f"/mst/attendance/rollcall/{exam_id}")
        assert res_roll.status_code == 200
        roll_students = res_roll.json()
        roll_rolls = [r["roll_number"] for r in roll_students]

        assert "0827CS211001" in roll_rolls  # Alice (eligible)
        assert "0827CS211003" in roll_rolls  # Charlie (override)
        assert "0827CS211002" not in roll_rolls  # Bob excluded
        assert "0827CS211004" not in roll_rolls  # David excluded
        assert len(roll_students) == 2
    finally:
        app.dependency_overrides.clear()
