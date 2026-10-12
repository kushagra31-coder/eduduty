import io
import pandas as pd
import pytest
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
from fastapi.testclient import TestClient

import models
from main import app
from database import get_db


def test_flat_upload_requires_class_id_and_returns_422():
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
        c1 = models.Class(name="CI-1", branch="CSE", year=3)
        c2 = models.Class(name="EC-A", branch="ECE", year=2)
        db.add_all([c1, c2])
        db.commit()
        c2_id = c2.id
        db.close()

        # Create a simple flat Excel DataFrame
        df = pd.DataFrame([
            {"Roll Number": "0827EC211001", "Name": "Alice", "Total Classes": 40, "Attended": 35, "Batch": 1},
        ])
        excel_buf = io.BytesIO()
        with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        excel_bytes = excel_buf.getvalue()

        # 1. Flat upload without class_id must return 422
        res_no_class = client.post(
            "/upload-attendance/",
            files={"file": ("flat_attendance.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert res_no_class.status_code == 422
        assert "class_id is required" in res_no_class.json()["detail"]

        # 2. Flat upload with explicit class_id must succeed and link student to that class
        res_with_class = client.post(
            f"/upload-attendance/?class_id={c2_id}",
            files={"file": ("flat_attendance.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert res_with_class.status_code == 200

        db = TestingSessionLocal()
        student = db.query(models.Student).filter_by(roll_number="0827EC211001").first()
        assert student is not None
        assert student.class_id == c2_id  # Assigned to EC-A, not CI-1!
        assert student.batch_number == 1
        db.close()
    finally:
        app.dependency_overrides.clear()


def test_manual_batch_edit_survives_second_upload():
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
        db.add(cls)
        db.commit()
        cls_id = cls.id

        # Student 1 with manual batch edit to 2
        s1 = models.Student(roll_number="0827CS211001", name="Alice", class_id=cls_id, batch_number=2)
        # Student 2 without batch
        s2 = models.Student(roll_number="0827CS211002", name="Bob", class_id=cls_id, batch_number=None)
        db.add_all([s1, s2])
        db.commit()
        db.close()

        # Upload a second attendance sheet without batch column
        df = pd.DataFrame([
            {"Roll Number": "0827CS211001", "Name": "Alice", "Total Classes": 40, "Attended": 35},
            {"Roll Number": "0827CS211002", "Name": "Bob", "Total Classes": 40, "Attended": 30},
        ])
        excel_buf = io.BytesIO()
        with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        excel_bytes = excel_buf.getvalue()

        res = client.post(
            f"/upload-attendance/?class_id={cls_id}",
            files={"file": ("attendance_v2.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert res.status_code == 200

        db = TestingSessionLocal()
        alice = db.query(models.Student).filter_by(roll_number="0827CS211001").first()
        bob = db.query(models.Student).filter_by(roll_number="0827CS211002").first()
        # Alice's manually edited batch 2 must survive!
        assert alice.batch_number == 2
        db.close()
    finally:
        app.dependency_overrides.clear()


def test_cross_class_conflict_reported_in_import_summary():
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
        c1 = models.Class(name="CS-A", branch="CS", year=3)
        c2 = models.Class(name="CS-B", branch="CS", year=3)
        db.add_all([c1, c2])
        db.commit()
        c1_id = c1.id
        c2_id = c2.id

        # Student is registered in CS-A
        student = models.Student(roll_number="0827CS211099", name="Charlie", class_id=c1_id)
        db.add(student)
        db.commit()
        db.close()

        # Someone uploads attendance for CS-B containing Charlie's roll number
        df = pd.DataFrame([
            {"Roll Number": "0827CS211099", "Name": "Charlie", "Total Classes": 40, "Attended": 35},
        ])
        excel_buf = io.BytesIO()
        with pd.ExcelWriter(excel_buf, engine="openpyxl") as writer:
            df.to_excel(writer, index=False)
        excel_bytes = excel_buf.getvalue()

        res = client.post(
            f"/upload-attendance/?class_id={c2_id}",
            files={"file": ("cs_b_roster.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")},
        )
        assert res.status_code == 200
        data = res.json()

        # Conflict must be reported in summary
        assert "class_conflicts" in data
        conflicts = data["class_conflicts"]
        assert len(conflicts) == 1
        assert conflicts[0]["roll_number"] == "0827CS211099"
        assert conflicts[0]["existing_class"] == "CS-A"
        assert conflicts[0]["imported_class"] == "CS-B"

        # Student must NOT be moved to CS-B silently
        db = TestingSessionLocal()
        db_student = db.query(models.Student).filter_by(roll_number="0827CS211099").first()
        assert db_student.class_id == c1_id  # Still in CS-A!
        db.close()
    finally:
        app.dependency_overrides.clear()
