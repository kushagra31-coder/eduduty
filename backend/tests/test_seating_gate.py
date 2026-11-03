import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

import models
from main import app
from database import get_db


def test_d2_seating_and_rollcall_gate_thresholds():
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
        room = models.Room(room_number="R101", capacity=30)
        exam = models.MstExam(label="MST-1", class_id=1)

        # Ensure system_rules key seat_min_pct = 45 is present
        rule = models.SystemRule(key="seat_min_pct", value="45.0", description="Minimum attendance % to be seated")
        db.add_all([cls, room, exam, rule])

        # 7 students:
        # s1: 44.99% -> excluded
        # s2: 45.00% -> seated (Borderline)
        # s3: 49.99% -> seated (Borderline)
        # s4: 50.00% -> seated (Eligible)
        # s5: Missing -> excluded
        # s6: Missing + override=True -> seated
        # s7: Not eligible (30%) + override=True -> seated
        s1 = models.Student(roll_number="ROLL4499", name="Student 44.99", class_id=1, batch_number=1, active=True)
        s2 = models.Student(roll_number="ROLL4500", name="Student 45.00", class_id=1, batch_number=1, active=True)
        s3 = models.Student(roll_number="ROLL4999", name="Student 49.99", class_id=1, batch_number=2, active=True)
        s4 = models.Student(roll_number="ROLL5000", name="Student 50.00", class_id=1, batch_number=2, active=True)
        s5 = models.Student(roll_number="ROLLMISS", name="Student Missing", class_id=1, batch_number=1, active=True)
        s6 = models.Student(roll_number="ROLLMOVR", name="Student MissOvr", class_id=1, batch_number=2, active=True)
        s7 = models.Student(roll_number="ROLLNEVR", name="Student NotElOvr", class_id=1, batch_number=1, active=True)

        db.add_all([s1, s2, s3, s4, s5, s6, s7])
        db.commit()
        exam_id = exam.id
        room_id = room.id
        s_ids = [s.id for s in [s1, s2, s3, s4, s5, s6, s7]]
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

        # Insert eligibility records
        db = TestingSessionLocal()
        el1 = models.MstEligibility(student_id=s_ids[0], mst_exam_id=exam_id, overall_pct=44.99, status="Not eligible", override=False)
        el2 = models.MstEligibility(student_id=s_ids[1], mst_exam_id=exam_id, overall_pct=45.00, status="Borderline", override=False)
        el3 = models.MstEligibility(student_id=s_ids[2], mst_exam_id=exam_id, overall_pct=49.99, status="Borderline", override=False)
        el4 = models.MstEligibility(student_id=s_ids[3], mst_exam_id=exam_id, overall_pct=50.00, status="Eligible", override=False)
        el5 = models.MstEligibility(student_id=s_ids[4], mst_exam_id=exam_id, overall_pct=None, status="Missing", override=False)
        el6 = models.MstEligibility(student_id=s_ids[5], mst_exam_id=exam_id, overall_pct=None, status="Missing", override=True, override_reason="Special approval")
        el7 = models.MstEligibility(student_id=s_ids[6], mst_exam_id=exam_id, overall_pct=30.00, status="Not eligible", override=True, override_reason="Medical")
        db.add_all([el1, el2, el3, el4, el5, el6, el7])
        db.commit()
        db.close()

        # 2. Call seating generation with D2 eligibility gate
        res_seat = client.post(
            "/mst/seating/generate",
            json={"mst_exam_id": exam_id, "room_ids": [room_id]},
        )
        assert res_seat.status_code == 200
        data_seat = res_seat.json()

        # 5 seated: s2 (45.00), s3 (49.99), s4 (50.00), s6 (Missing+override), s7 (Not eligible+override)
        assert data_seat["students_seated"] == 5

        # Excluded list must contain reasons:
        excluded_map = {e["roll_number"]: e["reason"] for e in data_seat["excluded"]}
        assert "ROLL4499" in excluded_map
        assert "44.99%" in excluded_map["ROLL4499"] or "threshold" in excluded_map["ROLL4499"] or "Not eligible" in excluded_map["ROLL4499"]

        assert "ROLLMISS" in excluded_map
        assert "Missing" in excluded_map["ROLLMISS"]

        assert len(data_seat["excluded"]) == 2

        # 3. Call roll-call with D2 eligibility gate
        res_roll = client.get(f"/mst/attendance/rollcall/{exam_id}")
        assert res_roll.status_code == 200
        roll_students = res_roll.json()
        roll_rolls = [r["roll_number"] for r in roll_students]

        assert "ROLL4500" in roll_rolls
        assert "ROLL4999" in roll_rolls
        assert "ROLL5000" in roll_rolls
        assert "ROLLMOVR" in roll_rolls
        assert "ROLLNEVR" in roll_rolls
        assert "ROLL4499" not in roll_rolls
        assert "ROLLMISS" not in roll_rolls
        assert len(roll_students) == 5

        # Check Borderline amber badge indicator in roll call
        borderline_rolls = {r["roll_number"] for r in roll_students if r.get("is_borderline")}
        assert "ROLL4500" in borderline_rolls
        assert "ROLL4999" in borderline_rolls
        assert "ROLL5000" not in borderline_rolls

        # 4. Check seat chart API returns is_borderline for seat chart UI
        res_chart = client.get(f"/mst/seating/{exam_id}")
        assert res_chart.status_code == 200
        chart_data = res_chart.json()
        assert len(chart_data) == 1
        seats = chart_data[0]["seats"]
        # Confirm seated students have is_borderline populated
        seen_borderline = False
        for s in seats:
            for side in ["left", "right"]:
                stud = s.get(side)
                if stud and stud.get("is_borderline"):
                    seen_borderline = True
        assert seen_borderline is True

    finally:
        app.dependency_overrides.clear()


def test_d1_seating_pairing_80_students():
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
        cls = models.Class(name="CS-80", branch="CS", year=3)
        room = models.Room(room_number="HALL1", capacity=50)  # capacity for 50 benches (100 students)
        exam = models.MstExam(label="MST-PAIR", class_id=1)
        db.add_all([cls, room, exam])

        # 80 students sorted by roll:
        # Batch 1 = first 40 (ROLL01..ROLL40)
        # Batch 2 = last 40 (ROLL41..ROLL80)
        students = []
        for i in range(1, 81):
            batch = 1 if i <= 40 else 2
            roll = f"ROLL{i:02d}"
            name = f"Student {i:02d}"
            students.append(models.Student(
                roll_number=roll,
                name=name,
                class_id=1,
                batch_number=batch,
                active=True,
            ))
        db.add_all(students)
        db.commit()

        # Add eligibility for all 80 students
        elig_records = [
            models.MstEligibility(
                student_id=s.id,
                mst_exam_id=exam.id,
                overall_pct=80.0,
                status="Eligible",
                override=False,
            )
            for s in students
        ]
        db.add_all(elig_records)
        db.commit()
        exam_id = exam.id
        room_id = room.id
        db.close()

        # Generate seating
        res = client.post(
            "/mst/seating/generate",
            json={"mst_exam_id": exam_id, "room_ids": [room_id]},
        )
        assert res.status_code == 200
        data = res.json()
        assert data["students_seated"] == 80
        assert data["seats_created"] == 40
        assert len(data["unseated"]) == 0
        assert len(data["excluded"]) == 0

        # Query seat chart
        res_chart = client.get(f"/mst/seating/{exam_id}")
        assert res_chart.status_code == 200
        chart = res_chart.json()
        assert len(chart) == 1
        seats = chart[0]["seats"]
        assert len(seats) == 40

        # Bench 1 = seat 1: left = ROLL01, right = ROLL41
        bench1 = seats[0]
        assert bench1["seat_number"] == "1"
        assert bench1["left"]["roll_number"] == "ROLL01"
        assert bench1["right"]["roll_number"] == "ROLL41"

        # Bench 40 = seat 40: left = ROLL40, right = ROLL80
        bench40 = seats[39]
        assert bench40["seat_number"] == "40"
        assert bench40["left"]["roll_number"] == "ROLL40"
        assert bench40["right"]["roll_number"] == "ROLL80"

        # Verify every bench i (1..40) has roll i + roll i+40
        for i, seat in enumerate(seats, start=1):
            expected_left = f"ROLL{i:02d}"
            expected_right = f"ROLL{i+40:02d}"
            assert seat["left"]["roll_number"] == expected_left
            assert seat["right"]["roll_number"] == expected_right

    finally:
        app.dependency_overrides.clear()
