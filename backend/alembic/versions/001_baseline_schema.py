"""Baseline initial schema migration reflecting current models.py

Revision ID: 001_baseline_schema
Revises: 
Create Date: 2026-10-10 17:35:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '001_baseline_schema'
down_revision: Union[str, None] = None
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    # 1. classes
    op.create_table(
        'classes',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=20), nullable=False),
        sa.Column('branch', sa.String(length=50), nullable=False),
        sa.Column('year', sa.SmallInteger(), nullable=False),
        sa.Column('section', sa.String(length=10), nullable=True),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('name')
    )
    op.create_index(op.f('ix_classes_id'), 'classes', ['id'], unique=False)

    # 2. faculty
    op.create_table(
        'faculty',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('department', sa.String(length=50), nullable=True),
        sa.Column('exempt_from_duty', sa.Boolean(), nullable=True),
        sa.Column('exempt_reason', sa.String(length=200), nullable=True),
        sa.Column('max_duties_per_day', sa.SmallInteger(), nullable=True),
        sa.Column('abbreviation', sa.String(length=10), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_faculty_id'), 'faculty', ['id'], unique=False)

    # 3. subjects
    op.create_table(
        'subjects',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('code', sa.String(length=20), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_subjects_id'), 'subjects', ['id'], unique=False)

    # 4. system_rules
    op.create_table(
        'system_rules',
        sa.Column('key', sa.String(length=50), nullable=False),
        sa.Column('value', sa.String(length=200), nullable=False),
        sa.Column('description', sa.String(length=300), nullable=True),
        sa.PrimaryKeyConstraint('key')
    )

    # 5. rooms
    op.create_table(
        'rooms',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('room_number', sa.String(length=20), nullable=False),
        sa.Column('capacity', sa.Integer(), nullable=True),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_rooms_id'), 'rooms', ['id'], unique=False)

    # 6. students
    op.create_table(
        'students',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('roll_number', sa.String(length=20), nullable=False),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('class_id', sa.Integer(), nullable=False),
        sa.Column('batch_number', sa.Integer(), nullable=True),
        sa.Column('pair_seat', sa.String(length=1), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=True),
        sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('roll_number')
    )
    op.create_index(op.f('ix_students_id'), 'students', ['id'], unique=False)

    # 7. mst_exams
    op.create_table(
        'mst_exams',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('label', sa.String(length=20), nullable=False),
        sa.Column('exam_date', sa.Date(), nullable=True),
        sa.Column('time_slot', sa.String(length=20), nullable=True),
        sa.Column('class_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_mst_exams_id'), 'mst_exams', ['id'], unique=False)

    # 8. timetable_versions
    op.create_table(
        'timetable_versions',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('class_id', sa.Integer(), nullable=False),
        sa.Column('semester', sa.String(length=20), nullable=False),
        sa.Column('session', sa.String(length=30), nullable=False),
        sa.Column('doc_no', sa.String(length=30), nullable=True),
        sa.Column('active', sa.Boolean(), nullable=False),
        sa.Column('created_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_timetable_versions_id'), 'timetable_versions', ['id'], unique=False)

    # 9. users
    op.create_table(
        'users',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('supabase_uid', sa.String(length=100), nullable=True),
        sa.Column('name', sa.String(length=100), nullable=False),
        sa.Column('role', sa.String(length=30), nullable=False),
        sa.Column('email', sa.String(length=150), nullable=True),
        sa.Column('faculty_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['faculty_id'], ['faculty.id'], ),
        sa.PrimaryKeyConstraint('id'),
        sa.UniqueConstraint('email')
    )
    op.create_index(op.f('ix_users_id'), 'users', ['id'], unique=False)
    op.create_index(op.f('ix_users_supabase_uid'), 'users', ['supabase_uid'], unique=True)

    # 10. attendance_records
    op.create_table(
        'attendance_records',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('faculty_id', sa.Integer(), nullable=True),
        sa.Column('subject_id', sa.Integer(), nullable=True),
        sa.Column('semester', sa.String(length=20), nullable=True),
        sa.Column('classes_conducted', sa.Integer(), nullable=False),
        sa.Column('classes_attended', sa.Integer(), nullable=False),
        sa.Column('attendance_pct', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('upload_date', sa.DateTime(), nullable=False),
        sa.Column('source_file', sa.String(length=255), nullable=True),
        sa.Column('approved', sa.Boolean(), nullable=False),
        sa.ForeignKeyConstraint(['faculty_id'], ['faculty.id'], ),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ),
        sa.ForeignKeyConstraint(['subject_id'], ['subjects.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_attendance_records_id'), 'attendance_records', ['id'], unique=False)

    # 11. mst_eligibility
    op.create_table(
        'mst_eligibility',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('mst_exam_id', sa.Integer(), nullable=False),
        sa.Column('overall_pct', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('lowest_subject_pct', sa.Numeric(precision=5, scale=2), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('override', sa.Boolean(), nullable=False),
        sa.Column('override_reason', sa.String(length=300), nullable=True),
        sa.Column('override_by', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['mst_exam_id'], ['mst_exams.id'], ),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_mst_eligibility_id'), 'mst_eligibility', ['id'], unique=False)

    # 12. mst_attempts
    op.create_table(
        'mst_attempts',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('mst_exam_id', sa.Integer(), nullable=False),
        sa.Column('room_id', sa.Integer(), nullable=True),
        sa.Column('seat_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=30), nullable=False),
        sa.Column('marked_by', sa.Integer(), nullable=True),
        sa.Column('marked_at', sa.DateTime(), nullable=True),
        sa.Column('remarks', sa.String(length=300), nullable=True),
        sa.ForeignKeyConstraint(['marked_by'], ['faculty.id'], ),
        sa.ForeignKeyConstraint(['mst_exam_id'], ['mst_exams.id'], ),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_mst_attempts_id'), 'mst_attempts', ['id'], unique=False)

    # 13. seats
    op.create_table(
        'seats',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('room_id', sa.Integer(), nullable=False),
        sa.Column('mst_exam_id', sa.Integer(), nullable=False),
        sa.Column('seat_number', sa.String(length=10), nullable=True),
        sa.Column('left_student', sa.Integer(), nullable=True),
        sa.Column('right_student', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['left_student'], ['students.id'], ),
        sa.ForeignKeyConstraint(['mst_exam_id'], ['mst_exams.id'], ),
        sa.ForeignKeyConstraint(['right_student'], ['students.id'], ),
        sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_seats_id'), 'seats', ['id'], unique=False)

    # 14. faculty_timetable
    op.create_table(
        'faculty_timetable',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('faculty_id', sa.Integer(), nullable=False),
        sa.Column('day_of_week', sa.String(length=10), nullable=False),
        sa.Column('period_start', sa.String(length=10), nullable=False),
        sa.Column('period_end', sa.String(length=10), nullable=False),
        sa.Column('subject_code', sa.String(length=20), nullable=True),
        sa.Column('subject_name', sa.String(length=100), nullable=True),
        sa.Column('room', sa.String(length=20), nullable=True),
        sa.Column('batch', sa.String(length=10), nullable=True),
        sa.Column('class_id', sa.Integer(), nullable=False),
        sa.Column('year', sa.Integer(), nullable=False),
        sa.Column('semester', sa.String(length=20), nullable=True),
        sa.Column('timetable_version_id', sa.Integer(), nullable=True),
        sa.ForeignKeyConstraint(['class_id'], ['classes.id'], ),
        sa.ForeignKeyConstraint(['faculty_id'], ['faculty.id'], ),
        sa.ForeignKeyConstraint(['timetable_version_id'], ['timetable_versions.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_faculty_timetable_id'), 'faculty_timetable', ['id'], unique=False)

    # 15. invigilation_duties
    op.create_table(
        'invigilation_duties',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('mst_exam_id', sa.Integer(), nullable=False),
        sa.Column('room_id', sa.Integer(), nullable=False),
        sa.Column('faculty_id', sa.Integer(), nullable=True),
        sa.Column('status', sa.String(length=20), nullable=False),
        sa.Column('assigned_at', sa.DateTime(), nullable=True),
        sa.ForeignKeyConstraint(['faculty_id'], ['faculty.id'], ),
        sa.ForeignKeyConstraint(['mst_exam_id'], ['mst_exams.id'], ),
        sa.ForeignKeyConstraint(['room_id'], ['rooms.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_invigilation_duties_id'), 'invigilation_duties', ['id'], unique=False)

    # 16. duty_replacements
    op.create_table(
        'duty_replacements',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('duty_id', sa.Integer(), nullable=False),
        sa.Column('original_faculty', sa.Integer(), nullable=True),
        sa.Column('replacement_faculty', sa.Integer(), nullable=True),
        sa.Column('reason', sa.String(length=300), nullable=False),
        sa.Column('changed_by', sa.Integer(), nullable=True),
        sa.Column('changed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['duty_id'], ['invigilation_duties.id'], ),
        sa.ForeignKeyConstraint(['original_faculty'], ['faculty.id'], ),
        sa.ForeignKeyConstraint(['replacement_faculty'], ['faculty.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_duty_replacements_id'), 'duty_replacements', ['id'], unique=False)

    # 17. audit_logs
    op.create_table(
        'audit_logs',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('table_name', sa.String(length=50), nullable=False),
        sa.Column('record_id', sa.Integer(), nullable=False),
        sa.Column('field_changed', sa.String(length=50), nullable=True),
        sa.Column('old_value', sa.String(length=300), nullable=True),
        sa.Column('new_value', sa.String(length=300), nullable=True),
        sa.Column('changed_by', sa.Integer(), nullable=True),
        sa.Column('reason', sa.String(length=300), nullable=True),
        sa.Column('changed_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['changed_by'], ['users.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_audit_logs_id'), 'audit_logs', ['id'], unique=False)

    # 18. follow_up_statuses
    op.create_table(
        'follow_up_statuses',
        sa.Column('id', sa.Integer(), nullable=False),
        sa.Column('student_id', sa.Integer(), nullable=False),
        sa.Column('rule_version', sa.String(length=30), nullable=False),
        sa.Column('mst_1_exam_id', sa.Integer(), nullable=True),
        sa.Column('mst_2_exam_id', sa.Integer(), nullable=True),
        sa.Column('mst_1_appeared', sa.Boolean(), nullable=True),
        sa.Column('mst_2_appeared', sa.Boolean(), nullable=True),
        sa.Column('calculated_status', sa.String(length=20), nullable=False),
        sa.Column('final_status', sa.String(length=20), nullable=False),
        sa.Column('override', sa.Boolean(), nullable=False),
        sa.Column('override_reason', sa.String(length=300), nullable=True),
        sa.Column('override_by', sa.Integer(), nullable=True),
        sa.Column('overridden_at', sa.DateTime(), nullable=True),
        sa.Column('calculated_at', sa.DateTime(), nullable=False),
        sa.Column('updated_at', sa.DateTime(), nullable=False),
        sa.ForeignKeyConstraint(['mst_1_exam_id'], ['mst_exams.id'], ),
        sa.ForeignKeyConstraint(['mst_2_exam_id'], ['mst_exams.id'], ),
        sa.ForeignKeyConstraint(['student_id'], ['students.id'], ),
        sa.PrimaryKeyConstraint('id')
    )
    op.create_index(op.f('ix_follow_up_statuses_id'), 'follow_up_statuses', ['id'], unique=False)
    op.create_index(op.f('ix_follow_up_statuses_student_id'), 'follow_up_statuses', ['student_id'], unique=True)


def downgrade() -> None:
    op.drop_index(op.f('ix_follow_up_statuses_student_id'), table_name='follow_up_statuses')
    op.drop_index(op.f('ix_follow_up_statuses_id'), table_name='follow_up_statuses')
    op.drop_table('follow_up_statuses')

    op.drop_index(op.f('ix_audit_logs_id'), table_name='audit_logs')
    op.drop_table('audit_logs')

    op.drop_index(op.f('ix_duty_replacements_id'), table_name='duty_replacements')
    op.drop_table('duty_replacements')

    op.drop_index(op.f('ix_invigilation_duties_id'), table_name='invigilation_duties')
    op.drop_table('invigilation_duties')

    op.drop_index(op.f('ix_faculty_timetable_id'), table_name='faculty_timetable')
    op.drop_table('faculty_timetable')

    op.drop_index(op.f('ix_seats_id'), table_name='seats')
    op.drop_table('seats')

    op.drop_index(op.f('ix_mst_attempts_id'), table_name='mst_attempts')
    op.drop_table('mst_attempts')

    op.drop_index(op.f('ix_mst_eligibility_id'), table_name='mst_eligibility')
    op.drop_table('mst_eligibility')

    op.drop_index(op.f('ix_attendance_records_id'), table_name='attendance_records')
    op.drop_table('attendance_records')

    op.drop_index(op.f('ix_users_supabase_uid'), table_name='users')
    op.drop_index(op.f('ix_users_id'), table_name='users')
    op.drop_table('users')

    op.drop_index(op.f('ix_timetable_versions_id'), table_name='timetable_versions')
    op.drop_table('timetable_versions')

    op.drop_index(op.f('ix_mst_exams_id'), table_name='mst_exams')
    op.drop_table('mst_exams')

    op.drop_index(op.f('ix_students_id'), table_name='students')
    op.drop_table('students')

    op.drop_index(op.f('ix_rooms_id'), table_name='rooms')
    op.drop_table('rooms')

    op.drop_table('system_rules')

    op.drop_index(op.f('ix_subjects_id'), table_name='subjects')
    op.drop_table('subjects')

    op.drop_index(op.f('ix_faculty_id'), table_name='faculty')
    op.drop_table('faculty')

    op.drop_index(op.f('ix_classes_id'), table_name='classes')
    op.drop_table('classes')
