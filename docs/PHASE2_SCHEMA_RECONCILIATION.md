# EduDuty — Phase 2, Stage A: Schema Reconciliation Report

**Date:** October 10, 2026  
**Status:** Audit & Design Complete  
**Scope:** Complete Schema Comparison & Discrepancy Reconciliation Across Repository Artifacts  
**Phase State:** Stage A Audit Only (No code, schema, or runtime changes applied)

---

## 1. Executive Summary

This report documents the schema reconciliation performed for the EduDuty platform. Four independent representations of the database schema were audited:

1. **SQLAlchemy ORM Models (`backend/models.py`)** — The authoritative runtime schema used by FastAPI endpoints.
2. **Raw DDL Script (`schema.sql`)** — Outdated baseline PostgreSQL DDL script in workspace root.
3. **Migration Script (`timetable_migration.sql`)** — Ad-hoc SQL ALTER statements for timetable extensions.
4. **Runtime Database (`eduduty.db` / `create_all()`)** — Auto-generated SQLite tables initialized during application startup.

---

## 2. Table-by-Table Schema Reconciliation Matrix

| Entity / Table | `models.py` (ORM) | `schema.sql` (Raw DDL) | `timetable_migration.sql` | Discrepancy & Drift Summary | Canonical Target Schema |
| :--- | :--- | :--- | :--- | :--- | :--- |
| **`classes`** | `id`, `name` (unique), `branch`, `year`, `section` | Matches `models.py` | — | **In Sync.** No discrepancy. | `id`, `name` (unique, NOT NULL), `branch`, `year`, `section`. |
| **`students`** | `id`, `roll_number` (unique), `name`, `class_id` (FK), `batch_number`, `pair_seat`, `active` | Matches `models.py` | — | **In Sync.** Foreign key to `classes.id` present. | `id`, `roll_number` (unique, NOT NULL), `name`, `class_id` (FK), `batch_number`, `pair_seat`, `active`. |
| **`faculty`** | `id`, `name`, `department`, `exempt_from_duty`, `exempt_reason`, `max_duties_per_day`, `abbreviation` | Missing `abbreviation` | Adds `abbreviation VARCHAR(10)` | **Drift:** `schema.sql` lacks `abbreviation`. `models.py` includes `abbreviation` (added via migration). | `id`, `name`, `department`, `exempt_from_duty`, `exempt_reason`, `max_duties_per_day`, `abbreviation`. |
| **`subjects`** | `id`, `name`, `code` | Matches `models.py` | — | **In Sync.** No discrepancy. | `id`, `name` (NOT NULL), `code`. |
| **`attendance_records`** | `id`, `student_id` (FK), `faculty_id` (FK), `subject_id` (FK), `semester`, `classes_conducted`, `classes_attended`, `attendance_pct` (Numeric), `upload_date`, `source_file`, `approved` | `attendance_pct` defined as `GENERATED ALWAYS AS (...) STORED` | — | **Drift:** `schema.sql` uses Postgres generated stored column; `models.py` uses plain `Numeric` computed at CRUD level. | `id`, `student_id` (FK), `faculty_id` (FK), `subject_id` (FK), `semester`, `classes_conducted`, `classes_attended`, `attendance_pct` (Numeric), `upload_date`, `source_file`, `approved`. |
| **`system_rules`** | `key` (PK), `value`, `description` | Matches `models.py` | — | **In Sync.** Seeded with default thresholds. | `key` (PK), `value` (NOT NULL), `description`. |
| **`mst_exams`** | `id`, `label`, `exam_date`, `time_slot`, `class_id` (FK) | Matches `models.py` | — | **In Sync.** No discrepancy. | `id`, `label` (NOT NULL), `exam_date`, `time_slot`, `class_id` (FK). |
| **`mst_eligibility`** | `id`, `student_id` (FK), `mst_exam_id` (FK), `overall_pct`, `lowest_subject_pct`, `status`, `override`, `override_reason`, `override_by` | Includes `UNIQUE (student_id, mst_exam_id)` | — | **Defect:** `models.py` **lacks the UNIQUE constraint** on `(student_id, mst_exam_id)`. `schema.sql` includes it. | `id`, `student_id` (FK), `mst_exam_id` (FK), `overall_pct`, `lowest_subject_pct`, `status`, `override`, `override_reason`, `override_by`, **`UNIQUE (student_id, mst_exam_id)`**. |
| **`mst_attempts`** | `id`, `student_id` (FK), `mst_exam_id` (FK), `room_id`, `seat_id`, `status`, `marked_by` (FK), `marked_at`, `remarks` | Includes `UNIQUE (student_id, mst_exam_id)` | — | **Defect:** `models.py` **lacks the UNIQUE constraint** on `(student_id, mst_exam_id)`. `schema.sql` includes it. | `id`, `student_id` (FK), `mst_exam_id` (FK), `room_id`, `seat_id`, `status`, `marked_by` (FK), `marked_at`, `remarks`, **`UNIQUE (student_id, mst_exam_id)`**. |
| **`rooms`** | `id`, `room_number`, `capacity` | Matches `models.py` | — | **In Sync.** No discrepancy. | `id`, `room_number` (NOT NULL), `capacity`. |
| **`seats`** | `id`, `room_id` (FK), `mst_exam_id` (FK), `seat_number`, `left_student` (FK), `right_student` (FK) | Matches `models.py` | — | **In Sync.** No discrepancy. | `id`, `room_id` (FK), `mst_exam_id` (FK), `seat_number`, `left_student` (FK), `right_student` (FK). |
| **`timetable_versions`** | `id`, `class_id` (FK), `semester`, `session`, `doc_no`, `active`, `created_at` | **NOT PRESENT** | Defines `CREATE TABLE timetable_versions` | **Major Drift:** Table is completely missing from `schema.sql`. Defined in `timetable_migration.sql` & `models.py`. | `id`, `class_id` (FK), `semester`, `session`, `doc_no`, `active`, `created_at`. |
| **`faculty_timetable`** | `id`, `faculty_id` (FK), `day_of_week`, `period_start`, `period_end`, `subject_code`, `subject_name`, `room`, `batch`, `class_id` (FK), `year`, `semester`, `timetable_version_id` (FK) | Single `time_slot VARCHAR(20)` column | Adds `period_start`, `period_end`, `subject_code`, `subject_name`, `room`, `batch`, `semester`, `timetable_version_id` | **Major Drift:** `schema.sql` has legacy single `time_slot` column. `models.py` and `timetable_migration.sql` extend it for period-based scheduling. | `id`, `faculty_id` (FK), `day_of_week`, `period_start`, `period_end`, `subject_code`, `subject_name`, `room`, `batch`, `class_id` (FK), `year`, `semester`, `timetable_version_id` (FK). |
| **`invigilation_duties`** | `id`, `mst_exam_id` (FK), `room_id` (FK), `faculty_id` (FK), `status`, `assigned_at` | Matches `models.py` | — | **In Sync.** No discrepancy. | `id`, `mst_exam_id` (FK), `room_id` (FK), `faculty_id` (FK), `status`, `assigned_at`. |
| **`duty_replacements`** | `id`, `duty_id` (FK), `original_faculty` (FK), `replacement_faculty` (FK), `reason`, `changed_by`, `changed_at` | Matches `models.py` | — | **In Sync.** No discrepancy. | `id`, `duty_id` (FK), `original_faculty` (FK), `replacement_faculty` (FK), `reason`, `changed_by`, `changed_at`. |
| **`users`** | `id`, `supabase_uid` (unique), `name`, `role`, `email` (unique), `faculty_id` (FK) | `id`, `name`, `role`, `email` | — | **Drift:** `schema.sql` lacks `supabase_uid` and `faculty_id`. Added to `models.py` during Phase 1 Auth integration. | `id`, `supabase_uid` (unique), `name`, `role`, `email` (unique), `faculty_id` (FK). |
| **`audit_logs`** | `id`, `table_name`, `record_id`, `field_changed`, `old_value`, `new_value`, `changed_by` (FK), `reason`, `changed_at` | Matches `models.py` | — | **In Sync.** No discrepancy. | `id`, `table_name`, `record_id`, `field_changed`, `old_value`, `new_value`, `changed_by` (FK), `reason`, `changed_at`. |
| **`follow_up_statuses`** | `id`, `student_id` (FK, unique), `rule_version`, `mst_1_exam_id` (FK), `mst_2_exam_id` (FK), `mst_1_appeared`, `mst_2_appeared`, `calculated_status`, `final_status`, `override`, `override_reason`, `override_by`, `overridden_at`, `calculated_at`, `updated_at` | **NOT PRESENT** | — | **Major Drift:** Table is completely missing from `schema.sql`. Defined in `models.py` for VT follow-up tracking. | `id`, `student_id` (FK, unique), `rule_version`, `mst_1_exam_id` (FK), `mst_2_exam_id` (FK), `mst_1_appeared`, `mst_2_appeared`, `calculated_status`, `final_status`, `override`, `override_reason`, `override_by`, `overridden_at`, `calculated_at`, `updated_at`. |

---

## 3. Database Views Reconciliation (AI Read-Only Query Layer)

The AI Q&A read pipeline (`ai_service.py`) depends on 5 database views. Below is the view reconciliation status:

| View Name | `schema.sql` | PostgreSQL DDL Definition Status | Purpose / References |
| :--- | :---: | :--- | :--- |
| **`ai_eligibility_summary`** | Present | Aggregates eligible/ineligible/missing count per class & MST exam. | Used by AI Q&A (`READ_SYSTEM_PROMPT`). |
| **`ai_attendance_summary`** | **Missing** | Computes overall and lowest subject attendance percentage per student. | Required by AI Q&A for borderline queries. |
| **`ai_vt_candidates`** | **Missing** | Lists candidates for VT based on MST-1 & MST-2 appearance status. | Required by AI Q&A for VT candidate lookup. |
| **`ai_duty_roster`** | **Missing** | Displays invigilation duties by date, room, and assigned faculty name. | Required by AI Q&A for roster queries. |
| **`v_vt_follow_up_status`** | **Missing** | Joins `follow_up_statuses` with `students` and `classes` for VT review. | Required by AI Q&A for VT status lookup. |

---

## 4. Key Schema Discrepancy Findings

1. **Missing Unique Constraints in ORM (`MstEligibility`, `MstAttempt`):**
   - `models.py` lacks `UniqueConstraint("student_id", "mst_exam_id")`. `schema.sql` includes this constraint. Adding explicit `UniqueConstraint` in `models.py` prevents duplicate records during concurrent operations.
2. **Outdated `schema.sql` DDL File:**
   - `schema.sql` is severely behind `models.py`. It lacks `timetable_versions`, `follow_up_statuses`, `User.supabase_uid`, `User.faculty_id`, `Faculty.abbreviation`, extended timetable columns, and 4 out of 5 AI database views.
3. **Database Driver Connector Discrepancy (`database.py`):**
   - `database.py:21` attempts `import psycopg` (psycopg v3), but `requirements.txt` installs `psycopg2-binary==2.9.13` (psycopg v2). This prevents local PostgreSQL auto-detection and triggers fallback to SQLite.

---

## 5. Canonical Schema Recommendation

`backend/models.py` serves as the authoritative source of truth for all EduDuty entities, augmented with explicit `UniqueConstraint` declarations on `MstEligibility` and `MstAttempt`. `schema.sql` should be replaced by version-controlled Alembic migrations.
