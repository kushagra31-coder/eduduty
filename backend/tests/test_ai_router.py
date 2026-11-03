import pytest
from unittest.mock import AsyncMock, patch
from sqlalchemy import create_engine
from sqlalchemy.pool import StaticPool
from sqlalchemy.orm import sessionmaker

import models
import ai_service


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


@pytest.mark.asyncio
async def test_ai_router_resolves_student_pdf(test_db):
    cls = models.Class(name="CS-A", branch="CS", year=3)
    test_db.add(cls)
    test_db.commit()

    student = models.Student(roll_number="0827CS211001", name="Alice", class_id=cls.id)
    test_db.add(student)
    test_db.commit()

    res = await ai_service.handle_ai_message("Download pdf for 0827CS211001", test_db)
    assert res["type"] == "pdf_link"
    assert res["content"] == "/pdf/student/0827CS211001"


@pytest.mark.asyncio
async def test_ai_router_resolves_exam_and_room_pdf(test_db):
    exam = models.MstExam(label="MST-1")
    room = models.Room(room_number="101", capacity=30)
    test_db.add_all([exam, room])
    test_db.commit()

    res = await ai_service.handle_ai_message("Download seating pdf for MST-1 in Room 101", test_db)
    assert res["type"] == "pdf_link"
    assert res["content"] == f"/pdf/seating/{exam.id}/{room.id}"


@pytest.mark.asyncio
async def test_ai_router_does_not_return_hardcoded_seating_1_1(test_db):
    # When no entity can be resolved, message with 'pdf' keyword must NOT return /pdf/seating/1/1
    # It must fall through to the query path.
    with patch("ai_service._llm_chat", new=AsyncMock(side_effect=["SELECT 1", "Here is your answer."])):
        res = await ai_service.handle_ai_message("How can I download a pdf report?", test_db)
        assert res["type"] == "answer"
        assert res["content"] != "/pdf/seating/1/1"
        assert res["content"] == "Here is your answer."
