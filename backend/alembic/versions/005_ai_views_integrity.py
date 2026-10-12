"""Refine ai_attendance_summary to include mst_label and eliminate synthetic cross-exam aggregation

Revision ID: 005_ai_views_integrity
Revises: 004_fix_ai_views
Create Date: 2026-10-10 19:30:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '005_ai_views_integrity'
down_revision: Union[str, None] = '004_fix_ai_views'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # Refine ai_attendance_summary to include mst_label for per-exam accuracy
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


def downgrade() -> None:
    # Revert ai_attendance_summary to revision 004 definition
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
