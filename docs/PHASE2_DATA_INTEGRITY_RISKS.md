# EduDuty — Phase 2, Stage A: Data Integrity Risk Assessment

**Date:** October 10, 2026  
**Status:** Audit & Design Complete  
**Scope:** Data Integrity Inventory, Severity Matrix, and Workflow Protection Mapping  
**Phase State:** Stage A Audit Only (No code or database modifications executed)

---

## 1. Prioritized Data Integrity Risk Inventory

| Risk ID | Title & Description | Severity | Evidence / Affected Files & Tables | Potential Impact | Recommended Mitigation | Verification Requirements | Status |
| :---: | :--- | :---: | :--- | :--- | :--- | :--- | :---: |
| **RISK-01** | Missing Unique Constraints on Eligibility & Attempt Records | **P0** | `backend/models.py:69-92` (`mst_eligibility`, `mst_attempts`) | Concurrent imports or API retries could insert duplicate eligibility or attempt rows for the same `(student_id, mst_exam_id)`. | Add explicit `UniqueConstraint('student_id', 'mst_exam_id')` to `MstEligibility` and `MstAttempt` in `models.py` and Alembic Stage B2. | Automated unit tests attempting duplicate insert; verify `IntegrityError` is raised. | **MITIGATED (Stage B2)** |
| **RISK-02** | SQLite Foreign Key Enforcement Default | **P1** | `backend/database.py:40-46` (`eduduty.db`) | SQLite by default does not enforce Foreign Key constraints unless `PRAGMA foreign_keys = ON;` is executed on connection. | Add `connect` event listener in `database.py` to set `PRAGMA foreign_keys = ON;` for SQLite connections. | Unit test attempting invalid foreign key insert (e.g. invalid `student_id`). | Pending |
| **RISK-03** | `schema.sql` Out-of-Sync with Application ORM | **P1** | `schema.sql`, `backend/models.py` | Fresh PostgreSQL deployments using `schema.sql` would crash because `timetable_versions`, `follow_up_statuses`, `User.supabase_uid`, and 4 AI views are missing. | Deprecate raw `schema.sql` in favor of Alembic version-controlled migrations (`001_baseline_schema.py`). | Run `alembic upgrade head` on fresh PostgreSQL instance; verify all 18 tables and 5 views exist. | In Progress (Stage B1) |
| **RISK-04** | PostgreSQL Connector Import Mismatch | **P1** | `backend/database.py:21`, `backend/requirements.txt` | `database.py` tries `import psycopg` (v3), but `requirements.txt` specifies `psycopg2-binary==2.9.13` (v2). Auto-detection fails and falls back to SQLite. | Update `_resolve_database_url` in `database.py` to attempt `psycopg2` import before falling back to SQLite. | Run backend with `DATABASE_URL` pointing to PostgreSQL; confirm log shows PostgreSQL connection. | Pending |
| **RISK-05** | Computed Attendance Percentage Storage | **P2** | `backend/models.py:50`, `schema.sql:50` | `schema.sql` defines `attendance_pct` as a Postgres stored generated column, while `models.py` computes it at application/CRUD level. | Standardize `attendance_pct` as an application-calculated Numeric column in `models.py` and Alembic baseline. | Upload attendance spreadsheet; verify `attendance_pct` is correctly computed and persisted. | In Progress (Stage B1) |

---

## 1.1 Stage B2 Uniqueness Constraint Resolution Details

### Added Database Constraints
1. `mst_eligibility`: Composite unique constraint `uq_mst_eligibility_student_exam` on `(student_id, mst_exam_id)`.
2. `mst_attempts`: Composite unique constraint `uq_mst_attempts_student_exam` on `(student_id, mst_exam_id)`.

### Nullability & Key Column Inspection
- Both `student_id` and `mst_exam_id` in both `mst_eligibility` and `mst_attempts` are declared `nullable=False` (`NOT NULL`) in table definitions and SQLAlchemy ORM models.
- Because key columns are `NOT NULL`, NULL-value treatment in SQL unique index evaluation (such as SQLite's treatment of NULLs as distinct) is not applicable. Every valid row must specify concrete integer values for both foreign keys.

### Preflight Duplicate Check & Safe Failure Procedure
- Migration revision `002_add_unique_constraints.py` performs a mandatory preflight SQL query checking for `(student_id, mst_exam_id)` groups with `COUNT(*) > 1` on both tables prior to DDL execution.
- If duplicates exist, the migration immediately halts with a `RuntimeError` diagnostic detailing the affected table, student IDs, exam IDs, and row counts.
- **Zero Record Data Loss:** The migration does not silently delete, truncate, or arbitrarily pick records. The preflight failure aborts the upgrade before constraint application, leaving existing records 100% intact.

---

---

## 2. Workflow Preservation Mapping & Regression Defense

The proposed Phase 2 migration design strictly preserves all critical application workflows:

| Critical Workflow | Entity Dependencies | Behavior Preservation | Regression Defense Test Strategy |
| :--- | :--- | :--- | :--- |
| **Student Eligibility Engine** | `AttendanceRecord`, `MstEligibility`, `SystemRule` | Preserves 50% eligible / 45% borderline thresholds and overall/lowest subject calculation. | `test_resource_authorization.py`, eligibility override unit tests. |
| **VT / Follow-Up Engine** | `FollowUpStatus`, `MstAttempt`, `MstExam` | Preserves `absent-both-mst-v1` rule, `NULL` appearance distinction (missing data != absent), and override/restore logic. | Follow-up recalculation unit tests, exact status transition assertions. |
| **Invigilation Scheduler** | `Faculty`, `InvigilationDuty`, `FacultyTimetable`, `Room` | Preserves greedy scheduling with 4 hard constraints (exemption, timetable clash, duty overlap, daily cap). | Duty auto-schedule unit tests, faculty availability grid tests. |
| **Natural Pair Seating** | `Student`, `Room`, `Seat`, `MstExam` | Preserves natural roll number sorting, Batch 1/2 zip pairing, and seating chart generation. | Seating plan generation unit tests. |
| **Attendance Importer** | `Student`, `Class`, `Subject`, `AttendanceRecord` | Preserves per-subject multi-sheet parsing, 50/50 batch splitting, 10 MiB limit, and atomic rollback on error. | `test_upload_attendance.py` (10 tests). |
| **AI Read/Write Pipeline** | AI Views, `AuditLog`, `MstEligibility`, `MstAttempt` | Preserves `read_db` connection isolation, view allow-lists, exact roll matching, and proposal-confirm flow. | `test_ai_read_isolation.py` (6 tests). |
| **PDF & HTML Exports** | `Student`, `AttendanceRecord`, `Seat`, `FollowUpStatus` | Preserves WeasyPrint rendering for student records, seating charts, and VT lists. | PDF export endpoint unit tests. |
| **Auth & Resource RBAC** | `User`, `InvigilationDuty`, `TimetableEntry`, `Student` | Preserves fail-closed JWT validation, role permissions, invigilator room scoping, and faculty class scoping. | `test_auth.py`, `test_rbac.py`, `test_resource_authorization.py`. |

---

## 3. Confirmed Defects vs Proposed Future Enhancements

### Confirmed Defects (Phase 2 Targets)
- Missing `UNIQUE (student_id, mst_exam_id)` constraints on `mst_eligibility` and `mst_attempts` in `models.py`.
- Outdated DDL script `schema.sql` missing tables and AI views.
- `psycopg` vs `psycopg2-binary` import discrepancy in `database.py`.

### Proposed Future Enhancements (Post-Phase 2)
- Multi-tenant university institutional hierarchy schemas (`institutions`, `campuses`, `departments`, `programs`).
- OR-Tools constraint solver abstraction for invigilation scheduling (Phase 8).
- Async background worker queue for notification emails (Phase 12).
