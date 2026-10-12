import sys
import os
import pytest
from fastapi.testclient import TestClient
from sqlalchemy import create_engine
from sqlalchemy.orm import sessionmaker

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from database import Base, get_db
import models
import main
from core import security

# In-memory SQLite for fast testing
SQLALCHEMY_TEST_DATABASE_URL = "sqlite:///:memory:"

# Isolated test secret and claims configuration
TEST_JWT_SECRET = "test-jwt-secret-key-32-chars-long-eduduty-test-key-12345"
os.environ["SUPABASE_JWT_SECRET"] = TEST_JWT_SECRET
os.environ["SUPABASE_JWT_ISSUER"] = "https://test.supabase.co/auth/v1"
os.environ["SUPABASE_JWT_AUDIENCE"] = "authenticated"
os.environ["SUPABASE_JWT_ALGORITHM"] = "HS256"

engine = create_engine(
    SQLALCHEMY_TEST_DATABASE_URL,
    connect_args={"check_same_thread": False},
)
TestingSessionLocal = sessionmaker(autocommit=False, autoflush=False, bind=engine)



@pytest.fixture(scope="session", autouse=True)
def setup_test_database():
    Base.metadata.create_all(bind=engine)
    # Seed default exam, class, faculty, and room
    db = TestingSessionLocal()
    c = models.Class(id=1, name="CI-1", branch="CSE", year=3)
    db.add(c)
    ex = models.MstExam(id=1, label="MST-1", class_id=1)
    db.add(ex)
    f = models.Faculty(id=1, name="Prof. Test Faculty", abbreviation="TF", department="CSE")
    db.add(f)
    r = models.Room(id=1, room_number="101", capacity=30)
    db.add(r)
    s = models.Student(id=1, roll_number="0827CI211001", name="Test Student", class_id=1, batch_number=1)
    db.add(s)
    
    # Create test users for different roles
    u_admin = models.User(id=1, supabase_uid="uid-admin-123", name="Super Admin User", role=security.SUPER_ADMIN, email="admin@eduduty.ac.in")
    u_coord = models.User(id=2, supabase_uid="uid-coord-456", name="Coordinator User", role=security.EXAM_COORDINATOR, email="coord@eduduty.ac.in")
    u_fac = models.User(id=3, supabase_uid="uid-fac-789", name="Faculty User", role=security.FACULTY, email="fac@eduduty.ac.in", faculty_id=1)
    u_view = models.User(id=4, supabase_uid="uid-view-999", name="Viewer User", role=security.VIEWER, email="viewer@eduduty.ac.in")
    db.add_all([u_admin, u_coord, u_fac, u_view])
    db.commit()
    db.close()
    yield
    Base.metadata.drop_all(bind=engine)


@pytest.fixture
def db():
    connection = engine.connect()
    transaction = connection.begin()
    session = TestingSessionLocal(bind=connection)

    yield session

    session.close()
    transaction.rollback()
    connection.close()


@pytest.fixture
def client(db):
    def _get_test_db():
        try:
            yield db
        finally:
            pass

    main.app.dependency_overrides[get_db] = _get_test_db
    with TestClient(main.app) as c:
        yield c
    main.app.dependency_overrides.clear()
