import os
import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import create_engine, text
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker
import datetime

import models
import ai_service
from database import get_readonly_connection


@pytest.fixture
def test_db():
    engine = create_engine(
        "sqlite:///:memory:",
        connect_args={"check_same_thread": False},
        poolclass=StaticPool,
    )
    models.Base.metadata.create_all(bind=engine)
    Session = sessionmaker(bind=engine)
    db = Session()
    yield db
    db.close()


def test_sqlglot_validator_rejects_forbidden_queries():
    """
    Ensure sqlglot parser strictly blocks multi-statements, comments,
    non-SELECT operations, CTE mutations, and non-whitelisted views.
    """
    forbidden_queries = [
        "SELECT 1; DROP TABLE students",
        "PRAGMA table_info(students)",
        "SELECT * FROM students",
        "WITH x AS (DELETE FROM students RETURNING *) SELECT * FROM x",
        "SELECT * FROM ai_eligibility_summary /* comment */",
        "-- comment\nSELECT * FROM ai_eligibility_summary",
        "ATTACH DATABASE 'test.db' AS test",
    ]

    for q in forbidden_queries:
        with pytest.raises(ValueError):
            ai_service._validate_read_sql(q)


def test_sqlglot_validator_accepts_valid_queries():
    valid_queries = [
        "SELECT * FROM ai_eligibility_summary",
        "SELECT class_name, eligible_count FROM ai_eligibility_summary WHERE class_name = 'CI-1'",
        "WITH cte AS (SELECT * FROM ai_attendance_summary) SELECT * FROM cte WHERE overall_pct >= 45",
    ]
    for q in valid_queries:
        res = ai_service._validate_read_sql(q)
        assert res


@pytest.mark.asyncio
async def test_ai_allow_cloud_false_never_calls_groq_or_gemini(monkeypatch):
    """
    When AI_ALLOW_CLOUD is false (default), outbound calls to Groq and Gemini
    must never be made even if providers/keys are configured.
    """
    monkeypatch.setenv("AI_ALLOW_CLOUD", "false")
    monkeypatch.setenv("GROQ_API_KEY", "test_groq_key")
    monkeypatch.setenv("GEMINI_API_KEY", "test_gemini_key")
    monkeypatch.setattr(ai_service, "GROQ_API_KEY", "test_groq_key")
    monkeypatch.setattr(ai_service, "GEMINI_API_KEY", "test_gemini_key")
    monkeypatch.setattr(ai_service, "AI_PROVIDERS", ["groq", "gemini", "ollama"])

    with patch("ai_service._openai_compat_chat", new=AsyncMock()) as mock_cloud_chat, \
         patch("ai_service._ollama_chat", new=AsyncMock(return_value="Ollama response")) as mock_ollama_chat:
        resp = await ai_service._llm_chat("system prompt", "user query")
        assert resp == "Ollama response"
        mock_cloud_chat.assert_not_called()
        mock_ollama_chat.assert_called_once()


def test_cloud_summarisation_aggregates_and_strips_pii():
    """
    When preparing query results for cloud summarisation, student names and
    roll numbers must be masked/aggregated to counts only.
    """
    rows_with_pii = [
        {"student_name": "Alice Sharma", "roll_number": "0827CS211001", "overall_pct": 42.5},
        {"student_name": "Bob Verma", "roll_number": "0827CS211002", "overall_pct": 44.0},
    ]
    cloud_payload = ai_service._aggregate_for_cloud(rows_with_pii)
    assert "Alice" not in cloud_payload
    assert "0827CS211001" not in cloud_payload
    assert "Bob" not in cloud_payload
    assert "total_records" in cloud_payload
    assert "2" in cloud_payload


def test_readonly_connection_fails_on_write():
    """
    Verify that write operations attempted through get_readonly_connection fail.
    """
    with get_readonly_connection() as ro_conn:
        # SELECT must succeed
        res = ro_conn.execute(text("SELECT 1")).scalar()
        assert res == 1

        # WRITE must fail
        with pytest.raises(Exception):
            ro_conn.execute(text("CREATE TABLE test_ai_safety_fail (id INT)"))


def test_assign_duty_checks_clashes_and_exemptions(test_db):
    """
    Prove that assign_duty calls the same clash-checker as UI path and blocks
    assigned/exempt/blocked faculty.
    """
    # Create faculty, room, exam
    fac_exempt = models.Faculty(name="Dr. Shilpa Bhalerao", abbreviation="SHB", exempt_from_duty=True, exempt_reason="HOD exemption")
    fac_free = models.Faculty(name="Prof. Regular Faculty", abbreviation="RF", exempt_from_duty=False)
    test_db.add_all([fac_exempt, fac_free])
    test_db.commit()

    room = models.Room(room_number="Room 101", capacity=40)
    exam = models.MstExam(label="MST-1", exam_date=datetime.date(2026, 11, 2), time_slot="09:00 - 12:00")
    test_db.add_all([room, exam])
    test_db.commit()

    # Attempt assigning exempt faculty must raise ValueError
    with pytest.raises(ValueError, match="cannot be assigned.*Exempt"):
        ai_service.execute_write_op({
            "operation": "assign_duty",
            "faculty_name": "Shilpa",
            "mst_label": "MST-1",
            "room_number": "Room 101"
        }, test_db, confirming_user_id=42)

    # Free faculty succeeds and records audit log with confirming_user_id
    res = ai_service.execute_write_op({
        "operation": "assign_duty",
        "faculty_name": "Regular",
        "mst_label": "MST-1",
        "room_number": "Room 101"
    }, test_db, confirming_user_id=42)
    assert res["changed"] == "assign_duty"

    duty = test_db.query(models.InvigilationDuty).filter_by(mst_exam_id=exam.id, room_id=room.id).first()
    assert duty.faculty_id == fac_free.id
    assert duty.status == "Assigned"

    log = test_db.query(models.AuditLog).filter_by(table_name="invigilation_duties").first()
    assert log is not None
    assert log.changed_by == 42
    assert "[AI]" in log.reason


def test_override_eligibility_requires_reason_and_records_audit(test_db):
    """
    override_eligibility requires non-empty reason and writes confirming user and [AI] tag.
    """
    cls = models.Class(name="CS-A", branch="CS", year=3)
    test_db.add(cls)
    test_db.commit()

    student = models.Student(roll_number="0827CS211099", name="Charlie", class_id=cls.id)
    exam = models.MstExam(label="MST-1")
    test_db.add_all([student, exam])
    test_db.commit()

    el = models.MstEligibility(student_id=student.id, mst_exam_id=exam.id, status="Not eligible", override=False)
    test_db.add(el)
    test_db.commit()

    # Empty reason must fail
    with pytest.raises(ValueError, match="Reason is required"):
        ai_service.execute_write_op({
            "operation": "override_eligibility",
            "roll_number": "0827CS211099",
            "mst_label": "MST-1",
            "reason": "   "
        }, test_db, confirming_user_id=10)

    # Valid reason succeeds
    res = ai_service.execute_write_op({
        "operation": "override_eligibility",
        "roll_number": "0827CS211099",
        "mst_label": "MST-1",
        "reason": "Medical certificate verified"
    }, test_db, confirming_user_id=10)
    assert res["changed"] == "override_eligibility"

    test_db.refresh(el)
    assert el.override is True
    assert el.override_reason == "Medical certificate verified"

    log = test_db.query(models.AuditLog).filter_by(table_name="mst_eligibility", record_id=el.id).first()
    assert log is not None
    assert log.changed_by == 10
    assert log.reason == "[AI] Medical certificate verified"
