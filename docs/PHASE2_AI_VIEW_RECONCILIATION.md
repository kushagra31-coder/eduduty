# EduDuty — Phase 2, Stage B3 / B3.1: AI Database View Reconciliation Report

**Date:** October 10, 2026  
**Status:** Stage B3.1 Complete  
**Scope:** AI Reporting Views Audit, Revision `003_add_ai_views` -> `004_fix_ai_views`, SQL Reconciliation, Privacy Audit, and Automated Verification  
**Revisions:** `001_baseline_schema` -> `002_add_unique_constraints` -> `003_add_ai_views` -> `004_fix_ai_views`  
**Test Suite Verdict:** **`55 PASSED, 0 FAILED`**

---

## 1. Executive Summary & View Reconciliation Matrix

Stage B3 and B3.1 introduce database-level version control for the 5 approved AI reporting views consumed by the read-only AI pipeline (`backend/ai_service.py`). Stage B3.1 refined these views in revision `004_fix_ai_views` to correct status classifications (`borderline_count`), eliminate join cardinality duplication, and re-anchor VT candidate lookup directly to the canonical `follow_up_statuses` engine.

| View Name | Depended Entities / Tables | Exposed Columns | Privacy & Security Isolation Summary | Dialect Compatibility |
| :--- | :--- | :--- | :--- | :--- |
| **`ai_eligibility_summary`** | `mst_eligibility`, `mst_exams`, `students`, `classes` | `class_name`, `mst_label`, `eligible_count`, `borderline_count`, `ineligible_count`, `missing_count` | Exposes only class-level aggregated counts. Includes explicit `borderline_count` for Borderline / conditionally_eligible students. No student identities exposed. | Portable ANSI SQL (`CASE WHEN LOWER(...)`). Tested on SQLite 3; Postgres ready. |
| **`ai_attendance_summary`** | `students`, `classes`, `mst_eligibility` | `class_name`, `roll_number`, `student_name`, `overall_pct`, `lowest_subject_pct` | Exposes student name/roll number with attendance percentages for borderline identification. Grouped by student to eliminate exam join duplication. | Standard ANSI JOINs with `GROUP BY`. |
| **`ai_vt_candidates`** | `students`, `classes`, `follow_up_statuses` | `class_name`, `roll_number`, `student_name`, `mst1_status`, `mst2_status` | Derived directly from canonical `follow_up_statuses` table. Returns `'Present'`, `'Absent'`, or `'Missing'`. | Standard ANSI JOINs. |
| **`ai_duty_roster`** | `invigilation_duties`, `mst_exams`, `rooms`, `faculty` | `mst_label`, `exam_date`, `room_number`, `faculty_name`, `duty_status` | Exposes exam duties and assigned faculty. `LEFT JOIN` preserves unfilled duties. Excludes faculty phone, department exemption reasons, and max daily duty settings. | Standard ANSI JOINs. |
| **`v_vt_follow_up_status`** | `follow_up_statuses`, `students`, `classes`, `mst_exams` | `roll_number`, `student_name`, `class_name`, `mst_1_label`, `mst_2_label`, `mst_1_appeared`, `mst_2_appeared`, `calculated_status`, `final_status`, `overridden`, `override_reason`, `rule_version`, `updated_at` | Exposes VT follow-up review statuses. `LEFT JOIN` on optional exam IDs. Excludes internal override user IDs. | Standard ANSI JOINs. |

---

## 2. Detailed View Definitions & SQL Standard (Revision `004_fix_ai_views`)

### View 1: `ai_eligibility_summary`
```sql
CREATE VIEW ai_eligibility_summary AS
SELECT
    c.name AS class_name,
    me.label AS mst_label,
    COUNT(CASE WHEN LOWER(el.status) = 'eligible' THEN 1 END) AS eligible_count,
    COUNT(CASE WHEN LOWER(el.status) IN ('borderline', 'conditionally_eligible') THEN 1 END) AS borderline_count,
    COUNT(CASE WHEN LOWER(el.status) IN ('not eligible', 'ineligible') THEN 1 END) AS ineligible_count,
    COUNT(CASE WHEN LOWER(el.status) = 'missing' THEN 1 END) AS missing_count
FROM mst_eligibility el
JOIN mst_exams me ON me.id = el.mst_exam_id
JOIN students s ON s.id = el.student_id
JOIN classes c ON c.id = s.class_id
GROUP BY c.name, me.label;
```

### View 2: `ai_attendance_summary`
```sql
CREATE VIEW ai_attendance_summary AS
SELECT
    c.name AS class_name,
    s.roll_number AS roll_number,
    s.name AS student_name,
    MAX(el.overall_pct) AS overall_pct,
    MIN(el.lowest_subject_pct) AS lowest_subject_pct
FROM students s
JOIN classes c ON c.id = s.class_id
JOIN mst_eligibility el ON el.student_id = s.id
GROUP BY c.name, s.roll_number, s.name;
```

### View 3: `ai_vt_candidates`
```sql
CREATE VIEW ai_vt_candidates AS
SELECT
    c.name AS class_name,
    s.roll_number AS roll_number,
    s.name AS student_name,
    CASE WHEN fs.mst_1_appeared IS NULL THEN 'Missing' WHEN fs.mst_1_appeared THEN 'Present' ELSE 'Absent' END AS mst1_status,
    CASE WHEN fs.mst_2_appeared IS NULL THEN 'Missing' WHEN fs.mst_2_appeared THEN 'Present' ELSE 'Absent' END AS mst2_status
FROM students s
JOIN classes c ON c.id = s.class_id
LEFT JOIN follow_up_statuses fs ON fs.student_id = s.id;
```

### View 4: `ai_duty_roster`
```sql
CREATE VIEW ai_duty_roster AS
SELECT
    me.label AS mst_label,
    me.exam_date AS exam_date,
    r.room_number AS room_number,
    f.name AS faculty_name,
    idut.status AS duty_status
FROM invigilation_duties idut
JOIN mst_exams me ON me.id = idut.mst_exam_id
JOIN rooms r ON r.id = idut.room_id
LEFT JOIN faculty f ON f.id = idut.faculty_id;
```

### View 5: `v_vt_follow_up_status`
```sql
CREATE VIEW v_vt_follow_up_status AS
SELECT
    s.roll_number AS roll_number,
    s.name AS student_name,
    c.name AS class_name,
    e1.label AS mst_1_label,
    e2.label AS mst_2_label,
    fus.mst_1_appeared AS mst_1_appeared,
    fus.mst_2_appeared AS mst_2_appeared,
    fus.calculated_status AS calculated_status,
    fus.final_status AS final_status,
    fus.override AS overridden,
    fus.override_reason AS override_reason,
    fus.rule_version AS rule_version,
    fus.updated_at AS updated_at
FROM follow_up_statuses fus
JOIN students s ON s.id = fus.student_id
JOIN classes c ON c.id = s.class_id
LEFT JOIN mst_exams e1 ON e1.id = fus.mst_1_exam_id
LEFT JOIN mst_exams e2 ON e2.id = fus.mst_2_exam_id;
```

---

## 3. Privacy & Sensitive Data Exclusion Audit

- **User Security Fields Excluded:** `users.supabase_uid`, `users.email`, `users.role`, and user primary keys are completely absent from all view projections.
- **Faculty Sensitivity Excluded:** `faculty.exempt_reason`, `faculty.exempt_from_duty`, and `faculty.max_duties_per_day` are excluded from `ai_duty_roster`.
- **System Traceability:** `follow_up_statuses.override_by` is excluded from `v_vt_follow_up_status` (exposing only non-identifying rationale `override_reason`).

---

## 4. Verification & Downgrade Safety

- **Fresh Migration Verification:** Executed `alembic upgrade head` across revisions `001` -> `002` -> `003` -> `004` on fresh temporary databases.
- **Reversibility & Downgrade Safety:** `downgrade()` in `004_fix_ai_views.py` cleanly reverts view DDL to revision `003` definitions.
- **Database Immutability:** Main database `eduduty.db` modification timestamp confirmed unchanged during test runs.
- **PostgreSQL Execution Status:** **Unverified locally** on a live PostgreSQL instance. View syntax adheres strictly to portable ANSI SQL standard. Production deployment gate remains open for Stage B4.
