"""Refine AI reporting views for status classification, VT follow-up synchronization, and join cardinality

Revision ID: 004_fix_ai_views
Revises: 003_add_ai_views
Create Date: 2026-10-10 19:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '004_fix_ai_views'
down_revision: Union[str, None] = '003_add_ai_views'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. ai_eligibility_summary (adds explicit borderline_count classification)
    op.execute("DROP VIEW IF EXISTS ai_eligibility_summary;")
    op.execute("""
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
    """)

    # 2. ai_attendance_summary (grouped by student to eliminate join duplication across exams)
    op.execute("DROP VIEW IF EXISTS ai_attendance_summary;")
    op.execute("""
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
    """)

    # 3. ai_vt_candidates (derived from canonical follow_up_statuses table)
    op.execute("DROP VIEW IF EXISTS ai_vt_candidates;")
    op.execute("""
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
    """)

    # 4. ai_duty_roster (re-created for completeness)
    op.execute("DROP VIEW IF EXISTS ai_duty_roster;")
    op.execute("""
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
    """)

    # 5. v_vt_follow_up_status (re-created for completeness)
    op.execute("DROP VIEW IF EXISTS v_vt_follow_up_status;")
    op.execute("""
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
    """)


def downgrade() -> None:
    # Revert to 003 definitions
    op.execute("DROP VIEW IF EXISTS v_vt_follow_up_status;")
    op.execute("DROP VIEW IF EXISTS ai_duty_roster;")
    op.execute("DROP VIEW IF EXISTS ai_vt_candidates;")
    op.execute("DROP VIEW IF EXISTS ai_attendance_summary;")
    op.execute("DROP VIEW IF EXISTS ai_eligibility_summary;")

    op.execute("""
        CREATE VIEW ai_eligibility_summary AS
        SELECT
            c.name AS class_name,
            me.label AS mst_label,
            COUNT(CASE WHEN LOWER(el.status) = 'eligible' THEN 1 END) AS eligible_count,
            COUNT(CASE WHEN LOWER(el.status) IN ('not eligible', 'ineligible') THEN 1 END) AS ineligible_count,
            COUNT(CASE WHEN LOWER(el.status) = 'missing' THEN 1 END) AS missing_count
        FROM mst_eligibility el
        JOIN mst_exams me ON me.id = el.mst_exam_id
        JOIN students s ON s.id = el.student_id
        JOIN classes c ON c.id = s.class_id
        GROUP BY c.name, me.label;
    """)

    op.execute("""
        CREATE VIEW ai_attendance_summary AS
        SELECT
            c.name AS class_name,
            s.roll_number AS roll_number,
            s.name AS student_name,
            el.overall_pct AS overall_pct,
            el.lowest_subject_pct AS lowest_subject_pct
        FROM students s
        JOIN classes c ON c.id = s.class_id
        JOIN mst_eligibility el ON el.student_id = s.id;
    """)

    op.execute("""
        CREATE VIEW ai_vt_candidates AS
        SELECT
            c.name AS class_name,
            s.roll_number AS roll_number,
            s.name AS student_name,
            MAX(CASE WHEN me.label = 'MST-1' THEN ma.status END) AS mst1_status,
            MAX(CASE WHEN me.label = 'MST-2' THEN ma.status END) AS mst2_status
        FROM students s
        JOIN classes c ON c.id = s.class_id
        LEFT JOIN mst_attempts ma ON ma.student_id = s.id
        LEFT JOIN mst_exams me ON me.id = ma.mst_exam_id
        GROUP BY c.name, s.roll_number, s.name;
    """)

    op.execute("""
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
    """)

    op.execute("""
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
    """)
