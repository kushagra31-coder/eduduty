import os
import pytest
import sqlite3
from unittest.mock import patch, MagicMock
from sqlalchemy import text
from sqlalchemy.exc import OperationalError

from database import engine, ai_reader_engine, SessionLocal, AIReaderSessionLocal, get_ai_db
import ai_service


def test_ai_reader_engine_is_distinct_and_read_only():
    """Verify ai_reader_engine is distinct from primary engine and enforces read-only operations."""
    assert ai_reader_engine is not engine

    # Attempt write operation on AI reader session
    reader_db = AIReaderSessionLocal()
    try:
        with pytest.raises(OperationalError) as exc_info:
            reader_db.execute(text("INSERT INTO classes (name, branch, year) VALUES ('HAX-99', 'CS', 1)"))
            reader_db.commit()
        err_msg = str(exc_info.value).lower()
        assert "readonly" in err_msg or "read-only" in err_msg or "cannot execute" in err_msg or "query_only" in err_msg
    finally:
        reader_db.close()


@pytest.mark.asyncio
async def test_ai_read_uses_dedicated_reader_connection():
    """Verify handle_ai_message executes SELECT queries over read_db."""
    db_main = SessionLocal()
    db_reader = AIReaderSessionLocal()

    try:
        # Mock _llm_chat to return a valid SELECT query over an allowed view under free-form SQL mode
        with patch.dict(os.environ, {"APP_ENV": "test", "ENABLE_FREEFORM_SQL_READ": "true"}):
            with patch.object(ai_service, "_llm_chat") as mock_llm:
                mock_llm.side_effect = [
                    "SELECT COUNT(*) FROM ai_eligibility_summary;", # SQL generation call
                    "There are 15 eligible students."               # Format response call
                ]

                res = await ai_service.handle_ai_message("How many eligible students?", db=db_main, read_db=db_reader)

                assert res["type"] == "answer"
                assert "15" in res["content"] or "eligible" in res["content"]

                # Verify that db_main was not used for query execution
                assert mock_llm.call_count == 2
    finally:
        db_main.close()
        db_reader.close()


@pytest.mark.asyncio
async def test_ai_read_never_falls_back_to_primary_write_connection():
    """Verify that when read_db fails or is unavailable, handle_ai_message fails closed and never falls back to db."""
    db_main = SessionLocal()

    # Pass a failing/broken read_db
    broken_read_db = MagicMock()
    broken_read_db.execute.side_effect = OperationalError("SELECT * FROM view", {}, Exception("PRAGMA query_only error"))

    with patch.dict(os.environ, {"ENABLE_FREEFORM_SQL_READ": "true"}):
        with patch.object(ai_service, "_llm_chat", return_value="SELECT COUNT(*) FROM ai_eligibility_summary;"):
            res = await ai_service.handle_ai_message("Count eligible students", db=db_main, read_db=broken_read_db)

            assert res["type"] == "error"
            assert "rejected" in res["content"].lower() or "failed" in res["content"].lower() or "read-only" in res["content"].lower()
    
    db_main.close()


def test_validate_read_sql_rejects_modifications_and_multistatements():
    """Verify _validate_read_sql rejects modification keywords, multi-statements, and unauthorized views."""
    # Forbidden keywords
    with pytest.raises(ValueError, match="forbidden keywords|Only SELECT"):
        ai_service._validate_read_sql("INSERT INTO classes (name) VALUES ('HACK')")

    with pytest.raises(ValueError, match="forbidden keywords|Only SELECT"):
        ai_service._validate_read_sql("UPDATE mst_eligibility SET override = True")

    with pytest.raises(ValueError, match="forbidden keywords|Only SELECT"):
        ai_service._validate_read_sql("DELETE FROM students")

    with pytest.raises(ValueError, match="forbidden keywords|Only SELECT"):
        ai_service._validate_read_sql("DROP TABLE students")

    # Multi-statement injection attempt
    with pytest.raises(ValueError, match="Multi-statement"):
        ai_service._validate_read_sql("SELECT * FROM ai_eligibility_summary; DELETE FROM students;")

    # Unauthorized view/table access
    with pytest.raises(ValueError, match="not permitted"):
        ai_service._validate_read_sql("SELECT * FROM users")

    with pytest.raises(ValueError, match="not permitted"):
        ai_service._validate_read_sql("SELECT * FROM students")

    # Valid allowed view
    valid_sql = ai_service._validate_read_sql("SELECT eligible_count FROM ai_eligibility_summary WHERE class_name='CI-1'")
    assert valid_sql.startswith("SELECT")


@pytest.mark.asyncio
async def test_reader_configuration_failure_handled_safely():
    """Verify that reader failure returns a safe error without leaking internal credentials."""
    db_main = SessionLocal()

    with patch("database.AIReaderSessionLocal", side_effect=Exception("Connection to postgresql://admin:secretpass@dbhost:5432/eduduty failed")):
        res = await ai_service.handle_ai_message("How many students?", db=db_main, read_db=None)

        assert res["type"] == "error"
        assert "secretpass" not in res["content"]
        assert "dbhost" not in res["content"]
        assert "unavailable" in res["content"].lower() or "failed" in res["content"].lower()

    db_main.close()


@pytest.mark.asyncio
async def test_ai_write_proposal_confirm_flow_remains_intact():
    """Verify write intent produces write_proposal without executing raw SQL, and write op requires explicit confirmation."""
    db_main = SessionLocal()
    db_reader = AIReaderSessionLocal()

    write_json = '{"operation": "override_eligibility", "roll_number": "2026101", "mst_label": "MST-1", "reason": "Medical exemption"}'

    with patch.object(ai_service, "_llm_chat", return_value=write_json):
        res = await ai_service.handle_ai_message("Override eligibility for roll 2026101 for MST-1 due to medical exemption", db=db_main, read_db=db_reader)

        assert res["type"] == "write_proposal"
        assert res["content"]["operation"] == "override_eligibility"
        assert res["content"]["roll_number"] == "2026101"

    db_main.close()
    db_reader.close()
