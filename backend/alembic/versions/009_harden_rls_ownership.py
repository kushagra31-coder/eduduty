"""Harden RLS function ownership and support zero-downtime key rotation

Revision ID: 009_harden_rls_ownership
Revises: 008_trusted_identity_context
Create Date: 2026-10-11 20:00:00.000000

"""
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '009_harden_rls_ownership'
down_revision: Union[str, None] = '008_trusted_identity_context'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        # 1. Create dedicated NOLOGIN function owner role with least privileges
        op.execute("""
            DO $r$
            BEGIN
                IF NOT EXISTS (SELECT 1 FROM pg_roles WHERE rolname = 'eduduty_rls_owner') THEN
                    CREATE ROLE eduduty_rls_owner WITH NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS;
                END IF;
            END $r$;
        """)

        # 2. Grant minimum necessary USAGE and SELECT privileges to eduduty_rls_owner
        op.execute("GRANT USAGE ON SCHEMA auth_internal TO eduduty_rls_owner;")
        op.execute("GRANT USAGE ON SCHEMA public TO eduduty_rls_owner;")
        op.execute("GRANT SELECT ON auth_internal.context_signing_key TO eduduty_rls_owner;")
        op.execute("GRANT SELECT ON public.students TO eduduty_rls_owner;")
        op.execute("GRANT SELECT ON public.faculty_timetable TO eduduty_rls_owner;")
        op.execute("GRANT SELECT ON public.timetable_versions TO eduduty_rls_owner;")
        op.execute("GRANT SELECT ON public.classes TO eduduty_rls_owner;")

        # 3. Explicit non-recursive RLS policies for eduduty_rls_owner
        op.execute("DROP POLICY IF EXISTS rls_students_definer_owner ON public.students;")
        op.execute("CREATE POLICY rls_students_definer_owner ON public.students FOR SELECT TO eduduty_rls_owner USING (true);")

        op.execute("DROP POLICY IF EXISTS rls_classes_definer_owner ON public.classes;")
        op.execute("CREATE POLICY rls_classes_definer_owner ON public.classes FOR SELECT TO eduduty_rls_owner USING (true);")

        # 4. Multi-key rotation support for auth_internal.verify_identity_context()
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
                canonical_payload text;
                expected_sig text;
                parsed_uid int;
                parsed_fac int;
                key_rec RECORD;
                sig_matched boolean := false;
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

                -- 3. Construct canonical payload
                canonical_payload := raw_uid || ':' || COALESCE(raw_fac, '') || ':' || raw_role || ':' || raw_ts || ':' || raw_nonce;

                -- 4. Verify signature across all active signing keys (zero-downtime rotation)
                FOR key_rec IN (
                    SELECT secret_key 
                    FROM auth_internal.context_signing_key 
                    WHERE active = true 
                    ORDER BY key_id DESC
                ) LOOP
                    expected_sig := encode(hmac(canonical_payload::bytea, key_rec.secret_key::bytea, 'sha256'), 'hex');
                    IF LOWER(raw_sig) = LOWER(expected_sig) THEN
                        sig_matched := true;
                        EXIT;
                    END IF;
                END LOOP;

                IF NOT sig_matched THEN
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

        # 5. Transfer function ownership to dedicated eduduty_rls_owner role
        op.execute("ALTER FUNCTION auth_internal.verify_identity_context() OWNER TO eduduty_rls_owner;")
        op.execute("ALTER FUNCTION can_current_user_access_class(int) OWNER TO eduduty_rls_owner;")
        op.execute("ALTER FUNCTION can_current_user_access_student(int) OWNER TO eduduty_rls_owner;")
        op.execute("ALTER FUNCTION can_current_user_access_duty_roster() OWNER TO eduduty_rls_owner;")

        # 6. Set tight execution grants
        op.execute("REVOKE ALL ON FUNCTION auth_internal.verify_identity_context() FROM PUBLIC, ai_reader;")
        op.execute("GRANT EXECUTE ON FUNCTION auth_internal.verify_identity_context() TO eduduty_rls_owner, postgres;")

        op.execute("REVOKE ALL ON FUNCTION can_current_user_access_class(int) FROM PUBLIC;")
        op.execute("REVOKE ALL ON FUNCTION can_current_user_access_student(int) FROM PUBLIC;")
        op.execute("REVOKE ALL ON FUNCTION can_current_user_access_duty_roster() FROM PUBLIC;")
        op.execute("GRANT EXECUTE ON FUNCTION can_current_user_access_class(int) TO ai_reader, postgres, eduduty_rls_owner;")
        op.execute("GRANT EXECUTE ON FUNCTION can_current_user_access_student(int) TO ai_reader, postgres, eduduty_rls_owner;")
        op.execute("GRANT EXECUTE ON FUNCTION can_current_user_access_duty_roster() TO ai_reader, postgres, eduduty_rls_owner;")


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        # 1. Reassign function ownership back to postgres
        op.execute("ALTER FUNCTION auth_internal.verify_identity_context() OWNER TO postgres;")
        op.execute("ALTER FUNCTION can_current_user_access_class(int) OWNER TO postgres;")
        op.execute("ALTER FUNCTION can_current_user_access_student(int) OWNER TO postgres;")
        op.execute("ALTER FUNCTION can_current_user_access_duty_roster() OWNER TO postgres;")

        # 2. Restore 008 single-key verify_identity_context()
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

                IF raw_uid IS NULL OR raw_uid = '' OR
                   raw_role IS NULL OR raw_role = '' OR
                   raw_ts IS NULL OR raw_ts = '' OR
                   raw_nonce IS NULL OR raw_nonce = '' OR
                   raw_sig IS NULL OR raw_sig = '' THEN
                    RETURN QUERY SELECT NULL::int, NULL::int, NULL::text, false;
                    RETURN;
                END IF;

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

                SELECT secret_key INTO active_secret
                FROM auth_internal.context_signing_key
                WHERE active = true
                ORDER BY key_id DESC
                LIMIT 1;

                IF active_secret IS NULL OR active_secret = '' THEN
                    RETURN QUERY SELECT NULL::int, NULL::int, NULL::text, false;
                    RETURN;
                END IF;

                canonical_payload := raw_uid || ':' || COALESCE(raw_fac, '') || ':' || raw_role || ':' || raw_ts || ':' || raw_nonce;
                expected_sig := encode(hmac(canonical_payload::bytea, active_secret::bytea, 'sha256'), 'hex');

                IF LOWER(raw_sig) <> LOWER(expected_sig) THEN
                    RETURN QUERY SELECT NULL::int, NULL::int, NULL::text, false;
                    RETURN;
                END IF;

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

        # 3. Drop definer owner policies
        op.execute("DROP POLICY IF EXISTS rls_students_definer_owner ON public.students;")
        op.execute("DROP POLICY IF EXISTS rls_classes_definer_owner ON public.classes;")

        # 4. Revoke privileges and drop eduduty_rls_owner
        op.execute("REVOKE ALL ON SCHEMA auth_internal FROM eduduty_rls_owner;")
        op.execute("REVOKE ALL ON SCHEMA public FROM eduduty_rls_owner;")
        op.execute("REVOKE ALL ON auth_internal.context_signing_key FROM eduduty_rls_owner;")
        op.execute("REVOKE ALL ON public.students FROM eduduty_rls_owner;")
        op.execute("REVOKE ALL ON public.faculty_timetable FROM eduduty_rls_owner;")
        op.execute("REVOKE ALL ON public.timetable_versions FROM eduduty_rls_owner;")
        op.execute("REVOKE ALL ON public.classes FROM eduduty_rls_owner;")
        op.execute("DROP ROLE IF EXISTS eduduty_rls_owner;")
