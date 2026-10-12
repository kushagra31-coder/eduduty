import pytest
from pydantic import ValidationError
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

import models
import schemas
import crud
from main import app
from database import get_db


def test_timetable_time_format_validation():
    # Valid times pass
    entry = schemas.TimetableEntryBase(
        faculty_id=1,
        day_of_week="MON",
        period_start="10:30",
        period_end="11:20",
        class_id=1,
        year=2,
    )
    assert entry.period_start == "10:30"
    assert entry.period_end == "11:20"

    # Single-digit hour without leading zero is rejected
    with pytest.raises(ValidationError):
        schemas.TimetableEntryBase(
            faculty_id=1,
            day_of_week="MON",
            period_start="9:30",
            period_end="10:20",
            class_id=1,
            year=2,
        )

    # Hour 24+ is rejected
    with pytest.raises(ValidationError):
        schemas.TimetableEntryBase(
            faculty_id=1,
            day_of_week="MON",
            period_start="24:00",
            period_end="25:00",
            class_id=1,
            year=2,
        )

    # Minute 60+ is rejected
    with pytest.raises(ValidationError):
        schemas.TimetableEntryBase(
            faculty_id=1,
            day_of_week="MON",
            period_start="10:60",
            period_end="11:00",
            class_id=1,
            year=2,
        )


def test_active_timetable_query_left_join():
    engine = create_engine("sqlite:///:memory:")
    models.Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db = TestingSessionLocal()

    try:
        test_class = models.Class(name="CS-A", branch="CS", year=3)
        fac = models.Faculty(name="Test Faculty")
        db.add_all([test_class, fac])
        db.commit()

        # 1. Unversioned entry (legacy row)
        unversioned = models.FacultyTimetable(
            faculty_id=fac.id,
            day_of_week="MON",
            period_start="10:30",
            period_end="11:20",
            class_id=test_class.id,
            year=3,
            timetable_version_id=None,
        )

        # 2. Inactive version entry
        old_ver = models.TimetableVersion(
            class_id=test_class.id,
            semester="V",
            session="Jul-Dec 2025",
            active=False,
        )
        db.add(old_ver)
        db.commit()

        inactive_entry = models.FacultyTimetable(
            faculty_id=fac.id,
            day_of_week="TUE",
            period_start="10:30",
            period_end="11:20",
            class_id=test_class.id,
            year=3,
            semester="V",
            timetable_version_id=old_ver.id,
        )

        # 3. Active version entry
        new_ver = models.TimetableVersion(
            class_id=test_class.id,
            semester="V",
            session="Jul-Dec 2026",
            active=True,
        )
        db.add(new_ver)
        db.commit()

        active_entry = models.FacultyTimetable(
            faculty_id=fac.id,
            day_of_week="WED",
            period_start="10:30",
            period_end="11:20",
            class_id=test_class.id,
            year=3,
            semester="V",
            timetable_version_id=new_ver.id,
        )

        db.add_all([unversioned, inactive_entry, active_entry])
        db.commit()

        # active_timetable_query must include unversioned (None) and active, but EXCLUDE inactive
        active_entries = crud.active_timetable_query(db).all()
        active_days = {e.day_of_week for e in active_entries}

        assert "MON" in active_days       # unversioned included
        assert "WED" in active_days       # active included
        assert "TUE" not in active_days   # inactive version excluded
        assert len(active_entries) == 2
    finally:
        db.close()


def test_atomic_put_timetable_endpoint():
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
        test_class = models.Class(name="IT-A", branch="IT", year=2)
        fac = models.Faculty(name="Dr. Smith")
        db.add_all([test_class, fac])
        db.commit()
        class_id = test_class.id
        faculty_id = fac.id
        db.close()

        # Initial save of Version 1
        res1 = client.put(
            f"/timetable/class/{class_id}/III",
            json={
                "session": "Jul-Dec 2026",
                "entries": [
                    {
                        "faculty_id": faculty_id,
                        "day_of_week": "MON",
                        "period_start": "10:30",
                        "period_end": "11:20",
                        "subject_code": "CS301",
                        "class_id": class_id,
                        "year": 2,
                        "semester": "III",
                    }
                ],
            },
        )
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["status"] == "success"
        v1_id = data1["version_id"]

        # Check GET returns the version 1 entry
        get_res1 = client.get(f"/timetable/class/{class_id}/III")
        assert get_res1.status_code == 200
        assert len(get_res1.json()) == 1
        assert get_res1.json()[0]["day_of_week"] == "MON"

        # Save Version 2 for the same class and semester
        res2 = client.put(
            f"/timetable/class/{class_id}/III",
            json={
                "session": "Jul-Dec 2026",
                "entries": [
                    {
                        "faculty_id": faculty_id,
                        "day_of_week": "THU",
                        "period_start": "11:20",
                        "period_end": "12:10",
                        "subject_code": "CS302",
                        "class_id": class_id,
                        "year": 2,
                        "semester": "III",
                    }
                ],
            },
        )
        assert res2.status_code == 200
        data2 = res2.json()
        v2_id = data2["version_id"]
        assert v2_id != v1_id

        # Verify in DB: Version 1 is now inactive, Version 2 is active
        db = TestingSessionLocal()
        v1 = db.query(models.TimetableVersion).filter_by(id=v1_id).first()
        v2 = db.query(models.TimetableVersion).filter_by(id=v2_id).first()
        assert v1.active is False
        assert v2.active is True
        db.close()

        # Check GET now returns ONLY the active Version 2 entry
        get_res2 = client.get(f"/timetable/class/{class_id}/III")
        assert get_res2.status_code == 200
        assert len(get_res2.json()) == 1
        assert get_res2.json()[0]["day_of_week"] == "THU"

        # Try submitting an invalid time format - must fail with 422
        res_invalid = client.put(
            f"/timetable/class/{class_id}/III",
            json={
                "entries": [
                    {
                        "faculty_id": faculty_id,
                        "day_of_week": "FRI",
                        "period_start": "9:00",  # invalid format
                        "period_end": "10:00",
                        "class_id": class_id,
                        "year": 2,
                    }
                ]
            },
        )
        assert res_invalid.status_code == 422
    finally:
        app.dependency_overrides.clear()
