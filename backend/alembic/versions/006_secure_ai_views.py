"""Secure AI reporting views with PostgreSQL security_invoker semantics and faculty_id projection

Revision ID: 006_secure_ai_views
Revises: 005_ai_views_integrity
Create Date: 2026-10-11 16:15:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '006_secure_ai_views'
down_revision: Union[str, None] = '005_ai_views_integrity'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    with_clause = "WITH (security_invoker = true)" if is_pg else ""

    # 1. ai_eligibility_summary (security_invoker = true)
    op.execute("DROP VIEW IF EXISTS ai_eligibility_summary;")
    op.execute(f"""
        CREATE VIEW ai_eligibility_summary {with_clause} AS
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

    # 2. ai_attendance_summary (security_invoker = true, preserves 005 mst_label integrity)
    op.execute("DROP VIEW IF EXISTS ai_attendance_summary;")
    op.execute(f"""
        CREATE VIEW ai_attendance_summary {with_clause} AS
        SELECT
            c.name AS class_name,
            me.label AS mst_label,
            s.roll_number AS roll_number,
            s.name AS student_name,
            el.overall_pct AS overall_pct,
            el.lowest_subject_pct AS lowest_subject_pct
        FROM students s
        JOIN classes c ON c.id = s.class_id
        JOIN mst_eligibility el ON el.student_id = s.id
        JOIN mst_exams me ON me.id = el.mst_exam_id;
    """)

    # 3. ai_vt_candidates (security_invoker = true)
    op.execute("DROP VIEW IF EXISTS ai_vt_candidates;")
    op.execute(f"""
        CREATE VIEW ai_vt_candidates {with_clause} AS
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

    # 4. ai_duty_roster (security_invoker = true, adds f.id AS faculty_id)
    op.execute("DROP VIEW IF EXISTS ai_duty_roster;")
    op.execute(f"""
        CREATE VIEW ai_duty_roster {with_clause} AS
        SELECT
            me.label AS mst_label,
            me.exam_date AS exam_date,
            r.room_number AS room_number,
            f.name AS faculty_name,
            f.id AS faculty_id,
            idut.status AS duty_status
        FROM invigilation_duties idut
        JOIN mst_exams me ON me.id = idut.mst_exam_id
        JOIN rooms r ON r.id = idut.room_id
        LEFT JOIN faculty f ON f.id = idut.faculty_id;
    """)

    # 5. v_vt_follow_up_status (security_invoker = true)
    op.execute("DROP VIEW IF EXISTS v_vt_follow_up_status;")
    op.execute(f"""
        CREATE VIEW v_vt_follow_up_status {with_clause} AS
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

    if is_pg:
        op.execute("""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ai_reader') THEN
                    GRANT SELECT ON ai_eligibility_summary, ai_attendance_summary, ai_vt_candidates, ai_duty_roster, v_vt_follow_up_status TO ai_reader;
                END IF;
            END
            $$;
        """)


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"
    # Restore exact revision 005 definitions without security_invoker and without faculty_id in ai_duty_roster

    # 1. ai_eligibility_summary
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

    # 2. ai_attendance_summary (005 definition)
    op.execute("DROP VIEW IF EXISTS ai_attendance_summary;")
    op.execute("""
        CREATE VIEW ai_attendance_summary AS
        SELECT
            c.name AS class_name,
            me.label AS mst_label,
            s.roll_number AS roll_number,
            s.name AS student_name,
            el.overall_pct AS overall_pct,
            el.lowest_subject_pct AS lowest_subject_pct
        FROM students s
        JOIN classes c ON c.id = s.class_id
        JOIN mst_eligibility el ON el.student_id = s.id
        JOIN mst_exams me ON me.id = el.mst_exam_id;
    """)

    # 3. ai_vt_candidates
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

    # 4. ai_duty_roster (004/005 definition without faculty_id)
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

    # 5. v_vt_follow_up_status
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

    if is_pg:
        op.execute("""
            DO $$
            BEGIN
                IF EXISTS (SELECT FROM pg_roles WHERE rolname = 'ai_reader') THEN
                    GRANT SELECT ON ai_eligibility_summary, ai_attendance_summary, ai_vt_candidates, ai_duty_roster, v_vt_follow_up_status TO ai_reader;
                END IF;
            END
            $$;
        """)

