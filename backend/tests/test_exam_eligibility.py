import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

import models
import crud
from main import app, get_non_attempted_exams_for_class
from database import get_db


def test_get_non_attempted_exams_filters_attempted_exams():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(bind=engine)
    TestingSessionLocal = sessionmaker(bind=engine)
    db = TestingSessionLocal()

    try:
        cls = models.Class(name="CS-A", branch="CS", year=3)
        st = models.Student(roll_number="0827CS211001", name="Student One", class_id=1)
        exam1 = models.MstExam(label="MST-1", class_id=1)
        exam2 = models.MstExam(label="MST-2", class_id=1)
        db.add_all([cls, st, exam1, exam2])
        db.commit()

        # Add an attempt for exam1
        attempt = models.MstAttempt(
            student_id=st.id,
            mst_exam_id=exam1.id,
            status="Present",
        )
        db.add(attempt)
        db.commit()

        # get_non_attempted_exams_for_class must return only exam2
        non_attempted = get_non_attempted_exams_for_class(db, cls.id)
        assert len(non_attempted) == 1
        assert non_attempted[0].id == exam2.id
        assert non_attempted[0].label == "MST-2"
    finally:
        db.close()


def test_dashboard_stats_dynamic_exam_resolution():
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
        st = models.Student(roll_number="0827CS211001", name="Student One", class_id=1)
        exam1 = models.MstExam(id=1, label="MST-1", class_id=1)
        exam2 = models.MstExam(id=2, label="MST-2", class_id=1)
        db.add_all([cls, st, exam1, exam2])
        db.commit()

        # exam 1: Eligible
        el1 = models.MstEligibility(
            student_id=st.id,
            mst_exam_id=1,
            overall_pct=85.0,
            lowest_subject_pct=80.0,
            status="Eligible",
        )
        # exam 2: Not eligible
        el2 = models.MstEligibility(
            student_id=st.id,
            mst_exam_id=2,
            overall_pct=40.0,
            lowest_subject_pct=35.0,
            status="Not eligible",
        )
        db.add_all([el1, el2])
        db.commit()
        db.close()

        # Explicit query for exam 1
        res1 = client.get("/dashboard/stats?mst_exam_id=1")
        assert res1.status_code == 200
        data1 = res1.json()
        assert data1["exam_label"] == "MST-1"
        assert data1["eligible"] == 1
        assert data1["ineligible"] == 0

        # Explicit query for exam 2
        res2 = client.get("/dashboard/stats?mst_exam_id=2")
        assert res2.status_code == 200
        data2 = res2.json()
        assert data2["exam_label"] == "MST-2"
        assert data2["eligible"] == 0
        assert data2["ineligible"] == 1

        # Default query (without query param) resolves to latest exam (exam 2)
        res_default = client.get("/dashboard/stats")
        assert res_default.status_code == 200
        data_default = res_default.json()
        assert data_default["exam_label"] == "MST-2"
        assert data_default["ineligible"] == 1
    finally:
        app.dependency_overrides.clear()
