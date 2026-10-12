# EduDuty — Database Architecture & Schema Audit Report

**Date:** October 6, 2026  
**Status:** Complete  
**Scope:** SQLAlchemy Models vs `schema.sql` vs Migration Files vs Runtime SQLite Database (`eduduty.db`)  

---

## 1. Database Configuration & Engine Resolution Audit

### Finding DB-01: Development Fallback to Local SQLite (`database.py`)
- **Location:** `backend/database.py:7-36`
- **Mechanism:**
  ```python
  def _resolve_database_url() -> str:
      env_url = os.getenv("DATABASE_URL")
      if env_url: return env_url
      # Try PostgreSQL on 54322, fallback to SQLite:
      return "sqlite:///./eduduty.db"
  ```
- **Architectural Violation:** `architecture (1).md` states:
  > "Production: PostgreSQL. The application must NEVER silently fall back to SQLite in production."
- **Dependencies Issues:** Line 21 in `database.py` tries `import psycopg` (psycopg v3), but `backend/requirements.txt` specifies `psycopg2-binary==2.9.13`. This connector mismatch causes the PostgreSQL check to fail and silently fall back to SQLite even if PostgreSQL is running locally!

---

## 2. Schema Drift Analysis

The repository contains three independent definitions of the database schema:
1. `backend/models.py` (SQLAlchemy ORM models used at runtime)
2. `schema.sql` (Raw PostgreSQL DDL file in workspace root)
3. `timetable_migration.sql` (Manual ALTER TABLE migration script in root)

Significant schema drift was identified across these sources:

| Entity / Table | `models.py` (ORM) | `schema.sql` (DDL) | Identified Schema Drift / Discrepancy |
| :--- | :--- | :--- | :--- |
| `mst_eligibility` | Has `student_id`, `mst_exam_id`, `overall_pct`, `lowest_subject_pct`, `status`, `override`, `override_reason`, `override_by` | Has `UNIQUE (student_id, mst_exam_id)` constraint | `models.py` **lacks the UNIQUE constraint** on `(student_id, mst_exam_id)`. Concurrent imports could create duplicate eligibility rows in SQLite. |
| `mst_attempts` | Has `student_id`, `mst_exam_id`, `room_id`, `seat_id`, `status`, `marked_by`, `marked_at`, `remarks` | Has `UNIQUE (student_id, mst_exam_id)` constraint | `models.py` **lacks the UNIQUE constraint** on `(student_id, mst_exam_id)`. |
| `faculty_timetable` | Has `period_start`, `period_end`, `subject_code`, `subject_name`, `room`, `batch`, `semester`, `timetable_version_id` | Single `time_slot VARCHAR(20)` column | `schema.sql` is severely outdated. `models.py` uses extended timetable fields added in `timetable_migration.sql`. |
| `timetable_versions` | Defined in `models.py` (`id`, `class_id`, `semester`, `session`, `doc_no`, `active`, `created_at`) | **NOT PRESENT** in `schema.sql` | `schema.sql` is missing the `timetable_versions` table entirely! |
| `follow_up_statuses` | Defined in `models.py` (`id`, `student_id`, `rule_version`, `mst_1_appeared`, `mst_2_appeared`, `calculated_status`, `final_status`, etc.) | **NOT PRESENT** in `schema.sql` | `schema.sql` is missing the `follow_up_statuses` table entirely! |
| `attendance_records` | `attendance_pct` defined as standard `Column(Numeric(5,2))` | `attendance_pct` defined as `GENERATED ALWAYS AS (...) STORED` | In `models.py`, `attendance_pct` is not automatically calculated by ORM on insert. |

---

## 3. Migration & Version Control Audit

### Finding DB-02: Absence of Alembic Migration Framework
- **Location:** `backend/`
- **Finding:**
  - `backend/main.py` uses `models.Base.metadata.create_all(bind=engine)` to initialize tables.
  - No `alembic` directory, `alembic.ini`, or migration history exists in the backend repository.
- **Risk:** `create_all()` only creates missing tables; it **cannot apply column changes, index updates, or migration scripts** to existing databases. Schema changes currently require manual SQL scripts (`timetable_migration.sql`) or wiping the database file.

---

## 4. Key Constraints & Data Integrity Audit

1. **Foreign Keys:**
   - Present on primary tables (`Student.class_id`, `AttendanceRecord.student_id`, `InvigilationDuty.mst_exam_id`).
   - SQLite by default does NOT enforce foreign keys unless `PRAGMA foreign_keys = ON;` is executed on connection.
2. **Nullable Fields:**
   - `MstEligibility.overall_pct` and `lowest_subject_pct` are nullable (correct for missing attendance).
   - `FollowUpStatus.mst_1_appeared` and `mst_2_appeared` are nullable booleans (correct: `NULL` represents missing data, distinguishing it from `False` = explicit absence).

---

## 5. Target State Alignment Recommendations

1. Initialize Alembic inside `backend/alembic`.
2. Generate an initial baseline Alembic revision reflecting current `models.py`.
3. Add explicit `UniqueConstraint('student_id', 'mst_exam_id')` to `MstEligibility` and `MstAttempt` models in `models.py`.
4. Deprecate `schema.sql` and `apply_schema.py` in favor of Alembic migrations.
