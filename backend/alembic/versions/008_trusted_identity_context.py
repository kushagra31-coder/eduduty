"""Implement trusted HMAC-signed identity context and hardened RLS

Revision ID: 008_trusted_identity_context
Revises: 007_implement_faculty_rls
Create Date: 2026-10-11 19:00:00.000000

"""
import os
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '008_trusted_identity_context'
down_revision: Union[str, None] = '007_implement_faculty_rls'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

# Default development/test signing secret
DEFAULT_DEV_SECRET = "eduduty_insecure_default_hmac_secret_for_dev_only_32b"


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        # 1. Ensure pgcrypto extension is available for HMAC-SHA256
        op.execute("CREATE EXTENSION IF NOT EXISTS pgcrypto;")

        # 2. Dedicated internal schema for authentication secrets
        op.execute("CREATE SCHEMA IF NOT EXISTS auth_internal;")
        op.execute("REVOKE ALL ON SCHEMA auth_internal FROM PUBLIC, ai_reader;")
        op.execute("GRANT USAGE ON SCHEMA auth_internal TO postgres;")

        # 3. Context signing key table (strictly isolated from ai_reader)
        op.execute("""
            CREATE TABLE IF NOT EXISTS auth_internal.context_signing_key (
                key_id serial primary key,
                secret_key text not null,
                active boolean not null default true,
                created_at timestamp not null default now()
            );
        """)
        op.execute("REVOKE ALL ON auth_internal.context_signing_key FROM PUBLIC, ai_reader;")
        op.execute("GRANT ALL ON auth_internal.context_signing_key TO postgres;")

        # Seed initial signing key (from environment if present, else secure test default)
        env_secret = os.environ.get("EDUDUTY_RLS_HMAC_SECRET", "").strip() or DEFAULT_DEV_SECRET
        # Use parameterized format or safe literal
        op.execute(sa.text("""
            INSERT INTO auth_internal.context_signing_key (secret_key, active)
            SELECT :sec, true
            WHERE NOT EXISTS (SELECT 1 FROM auth_internal.context_signing_key WHERE active = true);
        """).bindparams(sec=env_secret))

        # 4. Helper function: auth_internal.verify_identity_context()
        # Evaluates signature, replay window, and claims.
        op.execute("""
            CREATE OR REPLACE FUNCTION auth_internal.verify_identity_context()
            RETURNS TABLE(v_user_id int, v_faculty_id int, v_role text, is_valid boolean)
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$
            DECLARE
                raw_uid text;
                raw_fac text;
                raw_role text;
                raw_ts text;
                raw_nonce text;
                raw_sig text;
                now_ts bigint;
                ctx_ts bigint;
                active_secret text;
                canonical_payload text;
                expected_sig text;
                parsed_uid int;
                parsed_fac int;
            BEGIN
                raw_uid := current_setting('app.current_user_id', true);
                raw_fac := current_setting('app.current_faculty_id', true);
                raw_role := LOWER(TRIM(COALESCE(current_setting('app.current_user_role', true), '')));
                raw_ts := current_setting('app.current_context_issued_at', true);
                raw_nonce := current_setting('app.current_context_nonce', true);
                raw_sig := current_setting('app.current_context_signature', true);

                -- 1. All mandatory fields must be non-null and non-empty
                IF raw_uid IS NULL OR raw_uid = '' OR
                   raw_role IS NULL OR raw_role = '' OR
                   raw_ts IS NULL OR raw_ts = '' OR
                   raw_nonce IS NULL OR raw_nonce = '' OR
                   raw_sig IS NULL OR raw_sig = '' THEN
                    RETURN QUERY SELECT NULL::int, NULL::int, NULL::text, false;
                    RETURN;
                END IF;

                -- 2. Validate timestamp format and enforce replay window (+30s to -120s)
                BEGIN
                    ctx_ts := raw_ts::bigint;
                EXCEPTION WHEN OTHERS THEN
                    RETURN QUERY SELECT NULL::int, NULL::int, NULL::text, false;
                    RETURN;
                END;

                now_ts := EXTRACT(EPOCH FROM clock_timestamp())::bigint;
                IF ctx_ts > now_ts + 30 OR ctx_ts < now_ts - 120 THEN
                    RETURN QUERY SELECT NULL::int, NULL::int, NULL::text, false;
                    RETURN;
                END IF;

                -- 3. Retrieve active signing secret
                SELECT secret_key INTO active_secret
                FROM auth_internal.context_signing_key
                WHERE active = true
                ORDER BY key_id DESC
                LIMIT 1;

                IF active_secret IS NULL OR active_secret = '' THEN
                    RETURN QUERY SELECT NULL::int, NULL::int, NULL::text, false;
                    RETURN;
                END IF;

                -- 4. Recompute canonical HMAC-SHA256 signature
                canonical_payload := raw_uid || ':' || COALESCE(raw_fac, '') || ':' || raw_role || ':' || raw_ts || ':' || raw_nonce;
                expected_sig := encode(hmac(canonical_payload::bytea, active_secret::bytea, 'sha256'), 'hex');

                IF LOWER(raw_sig) <> LOWER(expected_sig) THEN
                    RETURN QUERY SELECT NULL::int, NULL::int, NULL::text, false;
                    RETURN;
                END IF;

                -- 5. Parse integer identifiers safely
                BEGIN
                    parsed_uid := raw_uid::int;
                EXCEPTION WHEN OTHERS THEN
                    RETURN QUERY SELECT NULL::int, NULL::int, NULL::text, false;
                    RETURN;
                END;

                IF raw_fac IS NOT NULL AND raw_fac <> '' THEN
                    BEGIN
                        parsed_fac := raw_fac::int;
                    EXCEPTION WHEN OTHERS THEN
                        RETURN QUERY SELECT NULL::int, NULL::int, NULL::text, false;
                        RETURN;
                    END;
                ELSE
                    parsed_fac := NULL;
                END IF;

                RETURN QUERY SELECT parsed_uid, parsed_fac, raw_role, true;
            END;
            $$;
        """)
        op.execute("REVOKE ALL ON FUNCTION auth_internal.verify_identity_context() FROM PUBLIC, ai_reader;")
        op.execute("GRANT EXECUTE ON FUNCTION auth_internal.verify_identity_context() TO postgres;")

        # 5. Harden and replace can_current_user_access_class(target_class_id)
        op.execute("""
            CREATE OR REPLACE FUNCTION can_current_user_access_class(target_class_id int)
            RETURNS boolean
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$
            DECLARE
                ctx_record RECORD;
                is_assigned boolean;
            BEGIN
                -- Cryptographic signature & context verification
                SELECT * INTO ctx_record FROM auth_internal.verify_identity_context();

                IF NOT COALESCE(ctx_record.is_valid, false) THEN
                    RETURN false;
                END IF;

                -- Administrators and exam coordinators have institution-wide access
                IF ctx_record.v_role IN ('super_admin', 'admin', 'exam_coordinator') THEN
                    RETURN true;
                END IF;

                -- Non-faculty roles are denied
                IF ctx_record.v_role <> 'faculty' OR ctx_record.v_faculty_id IS NULL OR target_class_id IS NULL THEN
                    RETURN false;
                END IF;

                -- Schema-qualified active timetable verification
                SELECT EXISTS (
                    SELECT 1
                    FROM public.faculty_timetable ft
                    JOIN public.timetable_versions tv ON tv.id = ft.timetable_version_id
                    WHERE ft.faculty_id = ctx_record.v_faculty_id
                      AND ft.class_id = target_class_id
                      AND tv.active = true
                ) INTO is_assigned;

                RETURN COALESCE(is_assigned, false);
            END;
            $$;
        """)

        # 6. Harden and replace can_current_user_access_student(target_student_id)
        op.execute("""
            CREATE OR REPLACE FUNCTION can_current_user_access_student(target_student_id int)
            RETURNS boolean
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$
            DECLARE
                ctx_record RECORD;
                is_assigned boolean;
            BEGIN
                -- Cryptographic signature & context verification
                SELECT * INTO ctx_record FROM auth_internal.verify_identity_context();

                IF NOT COALESCE(ctx_record.is_valid, false) THEN
                    RETURN false;
                END IF;

                IF ctx_record.v_role IN ('super_admin', 'admin', 'exam_coordinator') THEN
                    RETURN true;
                END IF;

                IF ctx_record.v_role <> 'faculty' OR ctx_record.v_faculty_id IS NULL OR target_student_id IS NULL THEN
                    RETURN false;
                END IF;

                SELECT EXISTS (
                    SELECT 1
                    FROM public.students s
                    JOIN public.faculty_timetable ft ON ft.class_id = s.class_id
                    JOIN public.timetable_versions tv ON tv.id = ft.timetable_version_id
                    WHERE s.id = target_student_id
                      AND ft.faculty_id = ctx_record.v_faculty_id
                      AND tv.active = true
                ) INTO is_assigned;

                RETURN COALESCE(is_assigned, false);
            END;
            $$;
        """)

        # 7. Harden and replace can_current_user_access_duty_roster()
        op.execute("""
            CREATE OR REPLACE FUNCTION can_current_user_access_duty_roster()
            RETURNS boolean
            LANGUAGE plpgsql
            SECURITY DEFINER
            SET search_path = pg_catalog, public
            AS $$
            DECLARE
                ctx_record RECORD;
            BEGIN
                SELECT * INTO ctx_record FROM auth_internal.verify_identity_context();

                IF NOT COALESCE(ctx_record.is_valid, false) THEN
                    RETURN false;
                END IF;

                IF ctx_record.v_role IN ('super_admin', 'admin', 'exam_coordinator', 'faculty') THEN
                    RETURN true;
                END IF;

                RETURN false;
            END;
            $$;
        """)

        # Revoke EXECUTE from PUBLIC; grant only to ai_reader and postgres
        op.execute("REVOKE ALL ON FUNCTION can_current_user_access_class(int) FROM PUBLIC;")
        op.execute("REVOKE ALL ON FUNCTION can_current_user_access_student(int) FROM PUBLIC;")
        op.execute("REVOKE ALL ON FUNCTION can_current_user_access_duty_roster() FROM PUBLIC;")
        op.execute("GRANT EXECUTE ON FUNCTION can_current_user_access_class(int) TO ai_reader, postgres;")
        op.execute("GRANT EXECUTE ON FUNCTION can_current_user_access_student(int) TO ai_reader, postgres;")
        op.execute("GRANT EXECUTE ON FUNCTION can_current_user_access_duty_roster() TO ai_reader, postgres;")

        # 8. Strengthen RLS: FORCE ROW LEVEL SECURITY on all 5 sensitive tables
        op.execute("ALTER TABLE students FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE mst_eligibility FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE follow_up_statuses FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE invigilation_duties FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE classes FORCE ROW LEVEL SECURITY;")

        # 9. Establish explicit policies for table owner / writer role so administration is never blocked
        op.execute("DROP POLICY IF EXISTS rls_students_admin_owner ON students;")
        op.execute("CREATE POLICY rls_students_admin_owner ON students FOR ALL TO postgres USING (true) WITH CHECK (true);")

        op.execute("DROP POLICY IF EXISTS rls_mst_eligibility_admin_owner ON mst_eligibility;")
        op.execute("CREATE POLICY rls_mst_eligibility_admin_owner ON mst_eligibility FOR ALL TO postgres USING (true) WITH CHECK (true);")

        op.execute("DROP POLICY IF EXISTS rls_follow_up_statuses_admin_owner ON follow_up_statuses;")
        op.execute("CREATE POLICY rls_follow_up_statuses_admin_owner ON follow_up_statuses FOR ALL TO postgres USING (true) WITH CHECK (true);")

        op.execute("DROP POLICY IF EXISTS rls_invigilation_duties_admin_owner ON invigilation_duties;")
        op.execute("CREATE POLICY rls_invigilation_duties_admin_owner ON invigilation_duties FOR ALL TO postgres USING (true) WITH CHECK (true);")

        op.execute("DROP POLICY IF EXISTS rls_classes_admin_owner ON classes;")
        op.execute("CREATE POLICY rls_classes_admin_owner ON classes FOR ALL TO postgres USING (true) WITH CHECK (true);")


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        # 1. Drop admin/owner policies
        op.execute("DROP POLICY IF EXISTS rls_students_admin_owner ON students;")
        op.execute("DROP POLICY IF EXISTS rls_mst_eligibility_admin_owner ON mst_eligibility;")
        op.execute("DROP POLICY IF EXISTS rls_follow_up_statuses_admin_owner ON follow_up_statuses;")
        op.execute("DROP POLICY IF EXISTS rls_invigilation_duties_admin_owner ON invigilation_duties;")
        op.execute("DROP POLICY IF EXISTS rls_classes_admin_owner ON classes;")

        # 2. NO FORCE ROW LEVEL SECURITY
        op.execute("ALTER TABLE students NO FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE mst_eligibility NO FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE follow_up_statuses NO FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE invigilation_duties NO FORCE ROW LEVEL SECURITY;")
        op.execute("ALTER TABLE classes NO FORCE ROW LEVEL SECURITY;")

        # 3. Restore revision 007 unhardened helper functions
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
                IF cur_role IN ('super_admin', 'admin', 'exam_coordinator') THEN
                    RETURN true;
                END IF;
                IF cur_role <> 'faculty' THEN
                    RETURN false;
                END IF;
                BEGIN
                    cur_faculty_id := current_setting('app.current_faculty_id', true)::int;
                EXCEPTION WHEN OTHERS THEN
                    RETURN false;
                END;
                IF cur_faculty_id IS NULL OR target_class_id IS NULL THEN
                    RETURN false;
                END IF;
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
                IF cur_role IN ('super_admin', 'admin', 'exam_coordinator') THEN
                    RETURN true;
                END IF;
                IF cur_role <> 'faculty' THEN
                    RETURN false;
                END IF;
                BEGIN
                    cur_faculty_id := current_setting('app.current_faculty_id', true)::int;
                EXCEPTION WHEN OTHERS THEN
                    RETURN false;
                END;
                IF cur_faculty_id IS NULL OR target_student_id IS NULL THEN
                    RETURN false;
                END IF;
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
                IF cur_role IN ('super_admin', 'admin', 'exam_coordinator', 'faculty') THEN
                    RETURN true;
                END IF;
                RETURN false;
            END;
            $$;
        """)

        op.execute("GRANT EXECUTE ON FUNCTION can_current_user_access_class(int) TO PUBLIC;")
        op.execute("GRANT EXECUTE ON FUNCTION can_current_user_access_student(int) TO PUBLIC;")
        op.execute("GRANT EXECUTE ON FUNCTION can_current_user_access_duty_roster() TO PUBLIC;")

        # 4. Drop auth_internal schema and verification objects
        op.execute("DROP FUNCTION IF EXISTS auth_internal.verify_identity_context();")
        op.execute("DROP TABLE IF EXISTS auth_internal.context_signing_key;")
        op.execute("DROP SCHEMA IF EXISTS auth_internal CASCADE;")
