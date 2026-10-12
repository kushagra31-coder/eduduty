"""Add unique constraints for mst_eligibility and mst_attempts (student_id, mst_exam_id)

Revision ID: 002_add_unique_constraints
Revises: 001_baseline_schema
Create Date: 2026-10-10 18:00:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '002_add_unique_constraints'
down_revision: Union[str, None] = '001_baseline_schema'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def check_preflight_duplicates(conn) -> None:
    """
    Inspect mst_eligibility and mst_attempts for duplicate (student_id, mst_exam_id) pairs
    prior to creating unique constraints. Stop migration safely if duplicates are present.
    """
    eligibility_dups = conn.execute(sa.text("""
        SELECT student_id, mst_exam_id, COUNT(*) AS row_count
        FROM mst_eligibility
        GROUP BY student_id, mst_exam_id
        HAVING COUNT(*) > 1;
    """)).fetchall()

    attempts_dups = conn.execute(sa.text("""
        SELECT student_id, mst_exam_id, COUNT(*) AS row_count
        FROM mst_attempts
        GROUP BY student_id, mst_exam_id
        HAVING COUNT(*) > 1;
    """)).fetchall()

    errors = []
    if eligibility_dups:
        details = ", ".join([f"(student_id={r[0]}, mst_exam_id={r[1]}, count={r[2]})" for r in eligibility_dups])
        errors.append(f"mst_eligibility contains duplicate (student_id, mst_exam_id) pairs: {details}")

    if attempts_dups:
        details = ", ".join([f"(student_id={r[0]}, mst_exam_id={r[1]}, count={r[2]})" for r in attempts_dups])
        errors.append(f"mst_attempts contains duplicate (student_id, mst_exam_id) pairs: {details}")

    if errors:
        raise RuntimeError(
            "Preflight data integrity check failed before applying migration 002_add_unique_constraints!\n"
            + "\n".join(errors) + "\n"
            "Manual data reconciliation is required before applying this migration. "
            "No records were deleted or modified."
        )


def upgrade() -> None:
    conn = op.get_bind()
    check_preflight_duplicates(conn)

    with op.batch_alter_table('mst_eligibility') as batch_op:
        batch_op.create_unique_constraint(
            'uq_mst_eligibility_student_exam',
            ['student_id', 'mst_exam_id']
        )

    with op.batch_alter_table('mst_attempts') as batch_op:
        batch_op.create_unique_constraint(
            'uq_mst_attempts_student_exam',
            ['student_id', 'mst_exam_id']
        )


def downgrade() -> None:
    with op.batch_alter_table('mst_attempts') as batch_op:
        batch_op.drop_constraint('uq_mst_attempts_student_exam', type_='unique')

    with op.batch_alter_table('mst_eligibility') as batch_op:
        batch_op.drop_constraint('uq_mst_eligibility_student_exam', type_='unique')
