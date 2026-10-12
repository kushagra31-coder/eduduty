import io
import pytest
import pandas as pd
from database import get_db
import models
from tests.test_auth import make_test_token, TEST_JWT_SECRET


def _get_auth_headers(role: str = "EXAM_COORDINATOR", uid: str = None) -> dict:
    """Helper to generate JWT headers for tests."""
    if uid is None:
        uid = f"uid-{role.lower()}-upload-test"
    email = f"{role.lower()}_{uid}@eduduty.ac.in"
    token = make_test_token(uid=uid, email=email, role=role)
    return {"Authorization": f"Bearer {token}"}


def _create_sample_excel_bytes() -> bytes:
    """Helper to create a valid Excel spreadsheet in bytes."""
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        # Sheet 1: Subject CS301
        df1 = pd.DataFrame([
            ["Subject Code:", "CS301", "", "Faculty Name:", "Dr. Sharma"],
            ["Enrollment No.", "Student Name", "Total Class", "Attended Class"],
            ["0827CI211001", "Test Student", 20, 18],
            ["0827CI211002", "Ananya Verma", 20, 14],
        ])
        df1.to_excel(writer, sheet_name="CS301", index=False, header=False)
    return output.getvalue()


def test_upload_valid_excel_spreadsheet(client):
    """Verify valid Excel upload imports records successfully."""
    headers = _get_auth_headers("EXAM_COORDINATOR")
    excel_bytes = _create_sample_excel_bytes()

    files = {"file": ("CI-1_IV.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    resp = client.post("/upload-attendance/", headers=headers, files=files)

    assert resp.status_code == 200
    data = resp.json()
    assert data["rows_imported"] == 2
    assert data["format"] == "subject_sheets"


def test_upload_empty_file_rejected(client):
    """Verify 0-byte upload is rejected with 400."""
    headers = _get_auth_headers("EXAM_COORDINATOR")
    files = {"file": ("empty.xlsx", b"", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    resp = client.post("/upload-attendance/", headers=headers, files=files)

    assert resp.status_code == 400
    assert "empty" in resp.json()["detail"].lower()


def test_upload_oversized_file_header_rejected(client):
    """Verify uploads exceeding 10 MiB with Content-Length header are rejected with 413."""
    headers = _get_auth_headers("EXAM_COORDINATOR")
    large_size = 10 * 1024 * 1024 + 100

    headers["Content-Length"] = str(large_size)
    files = {"file": ("large.xlsx", b"PK\x03\x04dummy", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    resp = client.post("/upload-attendance/", headers=headers, files=files)

    assert resp.status_code == 413
    assert "10 mib" in resp.json()["detail"].lower()


def test_upload_oversized_file_streaming_rejected(client):
    """Verify bounded streaming reader rejects files exceeding 10 MiB regardless of headers."""
    headers = _get_auth_headers("EXAM_COORDINATOR")
    headers["Content-Length"] = "100"  # Spoofed small content length

    oversized_bytes = b"PK\x03\x04" + b"X" * (10 * 1024 * 1024 + 200)
    files = {"file": ("large_spoofed.xlsx", oversized_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    resp = client.post("/upload-attendance/", headers=headers, files=files)

    assert resp.status_code == 413
    assert "10 mib" in resp.json()["detail"].lower()


def test_upload_misleading_magic_bytes_rejected(client):
    """Verify file with .xlsx extension containing non-Excel content (text/executable) is rejected with 400."""
    headers = _get_auth_headers("EXAM_COORDINATOR")
    fake_content = b"<html><body>Not an excel file</body></html>"
    files = {"file": ("fake.xlsx", fake_content, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    resp = client.post("/upload-attendance/", headers=headers, files=files)

    assert resp.status_code == 400
    assert "magic header" in resp.json()["detail"].lower() or "corrupt" in resp.json()["detail"].lower()


def test_upload_corrupt_spreadsheet_rejected(client):
    """Verify corrupt zip file starting with PK magic bytes is rejected with 400."""
    headers = _get_auth_headers("EXAM_COORDINATOR")
    corrupt_pk_bytes = b"PK\x03\x04" + b"corrupt garbage data not a real zip"
    files = {"file": ("corrupt.xlsx", corrupt_pk_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    resp = client.post("/upload-attendance/", headers=headers, files=files)

    assert resp.status_code == 400
    assert "corrupt" in resp.json()["detail"].lower() or "parse" in resp.json()["detail"].lower()


def test_upload_unsupported_extension_rejected(client):
    """Verify unsupported file extensions (.docx, .pdf, .txt) are rejected with 400."""
    headers = _get_auth_headers("EXAM_COORDINATOR")
    files = {"file": ("document.docx", b"PK\x03\x04dummy", "application/vnd.openxmlformats-officedocument.wordprocessingml.document")}

    resp = client.post("/upload-attendance/", headers=headers, files=files)

    assert resp.status_code == 400
    assert "extension" in resp.json()["detail"].lower() or "excel" in resp.json()["detail"].lower()


def test_upload_unauthorized_roles_rejected(client):
    """Verify unauthenticated requests (401) and unauthorized roles (403) are denied."""
    excel_bytes = _create_sample_excel_bytes()
    files = {"file": ("sample.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    # Unauthenticated request
    resp = client.post("/upload-attendance/", files=files)
    assert resp.status_code == 401

    # Unauthorized role (INVIGILATOR lacks attendance.import permission)
    headers = _get_auth_headers("INVIGILATOR", uid="uid-invig-000")
    resp = client.post("/upload-attendance/", headers=headers, files=files)
    assert resp.status_code == 403


def test_rejected_upload_does_not_mutate_database(client, db):
    """Verify failed/rejected uploads roll back all database transactions cleanly."""
    initial_att_count = db.query(models.AttendanceRecord).count()

    headers = _get_auth_headers("EXAM_COORDINATOR")
    corrupt_files = {"file": ("bad.xlsx", b"PK\x03\x04corrupt", "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}
    client.post("/upload-attendance/", headers=headers, files=corrupt_files)

    post_att_count = db.query(models.AttendanceRecord).count()
    assert post_att_count == initial_att_count


def test_atomic_rollback_on_mid_import_failure(client, db):
    """Verify that if a multi-sheet workbook fails after parsing sheet 1, sheet 1 changes are rolled back atomically."""
    headers = _get_auth_headers("EXAM_COORDINATOR")
    initial_att_count = db.query(models.AttendanceRecord).count()

    # Create a workbook where sheet 1 is valid, but sheet 2 has invalid sheet headers
    output = io.BytesIO()
    with pd.ExcelWriter(output, engine="openpyxl") as writer:
        df1 = pd.DataFrame([
            ["Subject Code:", "CS501", "", "Faculty Name:", "Dr. Patel"],
            ["Enrollment No.", "Student Name", "Total Class", "Attended Class"],
            ["0827CI211001", "Test Student", 20, 18],
        ])
        df1.to_excel(writer, sheet_name="CS501", index=False, header=False)

        # Sheet 2 has 20,000 rows (exceeds 10,000 row max dimension limit)
        df2 = pd.DataFrame([["data"] * 10] * 10005)
        df2.to_excel(writer, sheet_name="CS502_TOO_BIG", index=False, header=False)

    excel_bytes = output.getvalue()
    files = {"file": ("mid_fail.xlsx", excel_bytes, "application/vnd.openxmlformats-officedocument.spreadsheetml.sheet")}

    resp = client.post("/upload-attendance/", headers=headers, files=files)
    assert resp.status_code == 400

    # Confirm no attendance records were committed for CS501
    post_att_count = db.query(models.AttendanceRecord).count()
    assert post_att_count == initial_att_count
