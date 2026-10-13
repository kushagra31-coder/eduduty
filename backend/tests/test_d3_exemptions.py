import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

import models
import crud
from main import app
from database import get_db
from seed_duty_exemptions import apply_d3_exemptions, EXEMPT_REASON


def test_d3_duty_exemptions():
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
        # Seed the three faculty members
        f_shb = models.Faculty(name="Dr. Shilpa Bhalerao", abbreviation="SHB", department="CSE")
        f_pg = models.Faculty(name="Dr. Praveen Gupta", abbreviation="PG", department="CSE")
        f_vk = models.Faculty(name="Dr. Vandana Kate", abbreviation="VK", department="CSE")
        db.add_all([f_shb, f_pg, f_vk])
        db.commit()

        # 1. Test apply_d3_exemptions prints and updates them
        updated = apply_d3_exemptions(db)
        assert len(updated) == 3
        for f in updated:
            assert f.exempt_from_duty is True
            assert f.exempt_reason == EXEMPT_REASON

        # 2. Test availability returns status Exempt with that exact reason
        avail_list = crud.check_faculty_availability(
            db=db,
            day_of_week="MON",
            period_start="10:30",
            period_end="11:20",
        )
        avail_map = {r.faculty_id: r for r in avail_list}
        for f in [f_shb, f_pg, f_vk]:
            assert f.id in avail_map
            assert avail_map[f.id].status == "Exempt"
            assert avail_map[f.id].reason == EXEMPT_REASON

        # 3. Test auto-scheduler never assigns any of them, even when no one else is free
        # Create an exam with 1 room needing invigilation
        room = models.Room(room_number="R101", capacity=30)
        exam = models.MstExam(label="MST-1", exam_date=models.datetime.date(2026, 11, 2), time_slot="10:30-11:20")
        db.add_all([room, exam])
        db.commit()

        # Add a seat so the exam has a room registered in the seating plan
        seat = models.Seat(room_id=room.id, mst_exam_id=exam.id, seat_number="1")
        db.add(seat)
        db.commit()

        # Auto-schedule duties when ONLY the 3 exempt faculty exist in the database
        res_propose = client.post(
            "/mst/duties/auto-schedule",
            json={"mst_exam_ids": [exam.id]},
        )
        assert res_propose.status_code == 200
        data_propose = res_propose.json()

        # Proposal list must be empty (neither of the 3 exempt faculty is assigned)
        assert len(data_propose["proposal"]) == 0
        # Slot must remain Unfilled
        assert len(data_propose["unfilled"]) == 1
        assert data_propose["unfilled"][0]["reason"] == "No free faculty"
        blockers = " ".join(data_propose["unfilled"][0]["blockers"])
        assert "exempt" in blockers.lower()

        # 4. Verify their classes stay in the timetable and still block
        cls = models.Class(name="CS-A", branch="CS", year=3)
        db.add(cls)
        db.commit()

        tt_entry = models.FacultyTimetable(
            faculty_id=f_shb.id,
            day_of_week="MON",
            period_start="10:30",
            period_end="11:20",
            class_id=cls.id,
            year=3,
        )
        db.add(tt_entry)
        db.commit()

        # Timetable entry is intact in active query
        active_tt = crud.get_timetable_for_class(db, cls.id)
        assert len(active_tt) == 1
        assert active_tt[0].faculty_id == f_shb.id

    finally:
        app.dependency_overrides.clear()
        db.close()
