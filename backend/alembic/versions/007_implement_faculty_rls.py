"""Implement PostgreSQL Row-Level Security for faculty reporting and transaction-scoped context

Revision ID: 007_implement_faculty_rls
Revises: 006_secure_ai_views
Create Date: 2026-10-11 17:50:00.000000

"""
from typing import Sequence, Union

from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '007_implement_faculty_rls'
down_revision: Union[str, None] = '006_secure_ai_views'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        # 1. Helper function: can_current_user_access_class(target_class_id)
        # Narrowly scoped SECURITY DEFINER function with fixed search_path.
        op.execute("""
            CREATE OR REPLACE FUNCTION can_current_user_access_class(target_class_id int)
            RETURNS boolean
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                cur_role text;
                cur_faculty_id int;
                is_assigned boolean;
            BEGIN
                cur_role := LOWER(COALESCE(current_setting('app.current_user_role', true), ''));

                -- Administrators and exam coordinators have institution-wide access
                IF cur_role IN ('super_admin', 'admin', 'exam_coordinator') THEN
                    RETURN true;
                END IF;

                -- Strict fail-closed for non-faculty roles
                IF cur_role <> 'faculty' THEN
                    RETURN false;
                END IF;

                -- Safely parse faculty ID from transaction context
                BEGIN
                    cur_faculty_id := current_setting('app.current_faculty_id', true)::int;
                EXCEPTION WHEN OTHERS THEN
                    RETURN false;
                END;

                IF cur_faculty_id IS NULL OR target_class_id IS NULL THEN
                    RETURN false;
                END IF;

                -- Check active timetable version assignment
                SELECT EXISTS (
                    SELECT 1
                    FROM faculty_timetable ft
                    JOIN timetable_versions tv ON tv.id = ft.timetable_version_id
                    WHERE ft.faculty_id = cur_faculty_id
                      AND ft.class_id = target_class_id
                      AND tv.active = true
                ) INTO is_assigned;

                RETURN COALESCE(is_assigned, false);
            END;
            $$;
        """)

        # 2. Helper function: can_current_user_access_student(target_student_id)
        op.execute("""
            CREATE OR REPLACE FUNCTION can_current_user_access_student(target_student_id int)
            RETURNS boolean
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                cur_role text;
                cur_faculty_id int;
                is_assigned boolean;
            BEGIN
                cur_role := LOWER(COALESCE(current_setting('app.current_user_role', true), ''));

                -- Administrators and exam coordinators have institution-wide access
                IF cur_role IN ('super_admin', 'admin', 'exam_coordinator') THEN
                    RETURN true;
                END IF;

                -- Strict fail-closed for non-faculty roles
                IF cur_role <> 'faculty' THEN
                    RETURN false;
                END IF;

                -- Safely parse faculty ID from transaction context
                BEGIN
                    cur_faculty_id := current_setting('app.current_faculty_id', true)::int;
                EXCEPTION WHEN OTHERS THEN
                    RETURN false;
                END;

                IF cur_faculty_id IS NULL OR target_student_id IS NULL THEN
                    RETURN false;
                END IF;

                -- Authoritative active timetable join
                SELECT EXISTS (
                    SELECT 1
                    FROM students s
                    JOIN faculty_timetable ft ON ft.class_id = s.class_id
                    JOIN timetable_versions tv ON tv.id = ft.timetable_version_id
                    WHERE s.id = target_student_id
                      AND ft.faculty_id = cur_faculty_id
                      AND tv.active = true
                ) INTO is_assigned;

                RETURN COALESCE(is_assigned, false);
            END;
            $$;
        """)

        # 3. Helper function: can_current_user_access_duty_roster()
        op.execute("""
            CREATE OR REPLACE FUNCTION can_current_user_access_duty_roster()
            RETURNS boolean
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = public, pg_temp
            AS $$
            DECLARE
                cur_role text;
            BEGIN
                cur_role := LOWER(COALESCE(current_setting('app.current_user_role', true), ''));

                -- Approved exception: faculty, exam_coordinator, super_admin, admin can view institution-wide duty roster
                IF cur_role IN ('super_admin', 'admin', 'exam_coordinator', 'faculty') THEN
                    RETURN true;
                END IF;

                RETURN false;
            END;
            $$;
        """)

        # Set execution privileges
        op.execute("GRANT EXECUTE ON FUNCTION can_current_user_access_class(int) TO PUBLIC;")
        op.execute("GRANT EXECUTE ON FUNCTION can_current_user_access_student(int) TO PUBLIC;")
        op.execute("GRANT EXECUTE ON FUNCTION can_current_user_access_duty_roster() TO PUBLIC;")

        # 4. Enable Row-Level Security on sensitive base tables
        op.execute("ALTER TABLE students ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE mst_eligibility ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE follow_up_statuses ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE invigilation_duties ENABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE classes ENABLE ROW LEVEL SECURITY;")

        # 5. Create RLS Policies
        op.execute("DROP POLICY IF EXISTS rls_students_faculty_class_scope ON students;")
        op.execute("""
            CREATE POLICY rls_students_faculty_class_scope ON students
            FOR SELECT
            TO ai_reader, public
            USING (can_current_user_access_class(class_id));
        """)

        op.execute("DROP POLICY IF EXISTS rls_mst_eligibility_faculty_class_scope ON mst_eligibility;")
        op.execute("""
            CREATE POLICY rls_mst_eligibility_faculty_class_scope ON mst_eligibility
            FOR SELECT
            TO ai_reader, public
            USING (can_current_user_access_student(student_id));
        """)

        op.execute("DROP POLICY IF EXISTS rls_follow_up_statuses_faculty_class_scope ON follow_up_statuses;")
        op.execute("""
            CREATE POLICY rls_follow_up_statuses_faculty_class_scope ON follow_up_statuses
            FOR SELECT
            TO ai_reader, public
            USING (can_current_user_access_student(student_id));
        """)

        op.execute("DROP POLICY IF EXISTS rls_invigilation_duties_roster_access ON invigilation_duties;")
        op.execute("""
            CREATE POLICY rls_invigilation_duties_roster_access ON invigilation_duties
            FOR SELECT
            TO ai_reader, public
            USING (can_current_user_access_duty_roster());
        """)

        op.execute("DROP POLICY IF EXISTS rls_classes_faculty_class_scope ON classes;")
        op.execute("""
            CREATE POLICY rls_classes_faculty_class_scope ON classes
            FOR SELECT
            TO ai_reader, public
            USING (can_current_user_access_class(id));
        """)


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        # Drop policies
        op.execute("DROP POLICY IF EXISTS rls_students_faculty_class_scope ON students;")
        op.execute("DROP POLICY IF EXISTS rls_mst_eligibility_faculty_class_scope ON mst_eligibility;")
        op.execute("DROP POLICY IF EXISTS rls_follow_up_statuses_faculty_class_scope ON follow_up_statuses;")
        op.execute("DROP POLICY IF EXISTS rls_invigilation_duties_roster_access ON invigilation_duties;")
        op.execute("DROP POLICY IF EXISTS rls_classes_faculty_class_scope ON classes;")

        # Disable RLS
        op.execute("ALTER TABLE students DISABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE mst_eligibility DISABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE follow_up_statuses DISABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE invigilation_duties DISABLE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE classes DISABLE ROW LEVEL SECURITY;")

        # Drop helper functions
        op.execute("DROP FUNCTION IF EXISTS can_current_user_access_class(int);")
        op.execute("DROP FUNCTION IF EXISTS can_current_user_access_student(int);")
        op.execute("DROP FUNCTION IF EXISTS can_current_user_access_duty_roster();")
