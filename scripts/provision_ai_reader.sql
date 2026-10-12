-- ============================================================================
-- EduDuty Phase 2: Least-Privileged AI Reader Role Provisioning
-- File: scripts/provision_ai_reader.sql
-- ============================================================================
--
-- PURPOSE:
-- Provision or reconcile the unprivileged 'ai_reader' role for AI reporting
-- operations under PostgreSQL 15+ security_invoker view semantics.
--
-- SECURITY ARCHITECTURE:
-- 1. Role Attributes:
--    - NOSUPERUSER: Cannot perform administrative operations
--    - NOBYPASSRLS: Strictly subject to Row-Level Security policies (Stage B4.2B)
--    - NOCREATEDB / NOCREATEROLE: Cannot create databases or roles
--    - NOINHERIT: Does not inherit permissions from other roles
--    - No table, view, sequence, or schema ownership
--
-- 2. Invoker View Privilege Reconciliation:
--    - Views created WITH (security_invoker = true) evaluate underlying table
--      permissions as the invoking user ('ai_reader').
--    - Therefore, 'ai_reader' requires SELECT on the specific base columns
--      referenced by the five approved reporting views.
--    - Table-level SELECT is revoked on all base tables to block SELECT *.
--
-- 3. Stale Privilege Removal & Role Isolation:
--    - Strips any accidental role memberships in administrative or application groups.
--    - Revokes all existing table, sequence, routine, and schema privileges before re-granting.
--    - Revokes default privileges on future objects created in schema public.
--
-- 4. IMPORTANT SECURITY NOTICE ON ROW-LEVEL SECURITY (RLS):
--    - Column-level grants restrict WHICH COLUMNS can be projected, but NOT
--      WHICH ROWS are returned.
--    - Direct queries such as `SELECT id, name, roll_number FROM students;`
--      will succeed under 'ai_reader' until Row-Level Security (RLS) is enabled
--      on base tables in Stage B4.2B.
--    - RLS with session context injection (SET LOCAL app.current_faculty_id)
--      is mandatory before 'ai_reader' can be exposed to untrusted query paths.
--
-- OPERATOR EXECUTION INSTRUCTIONS:
-- 1. Connect as database superuser/administrator:
--    psql -h <HOST> -p <PORT> -U postgres -d <DATABASE_NAME> -f scripts/provision_ai_reader.sql
--
-- 2. Set or rotate credentials through a secure operator-controlled command:
--    ALTER ROLE ai_reader WITH LOGIN PASSWORD '<STRONG_SECRET_TOKEN>';
--    (Do NOT commit passwords to source control or logs)
--
-- ============================================================================

\set ON_ERROR_STOP on

BEGIN;

-- 1. Safe idempotent role creation or attribute reconciliation
DO $$
BEGIN
    IF NOT EXISTS (SELECT FROM pg_roles WHERE rolname = 'ai_reader') THEN
        CREATE ROLE ai_reader WITH
            NOSUPERUSER
            NOBYPASSRLS
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT;
        RAISE NOTICE 'Role ai_reader created with least-privilege negative attributes.';
    ELSE
        ALTER ROLE ai_reader WITH
            NOSUPERUSER
            NOBYPASSRLS
            NOCREATEDB
            NOCREATEROLE
            NOINHERIT;
        RAISE NOTICE 'Role ai_reader attributes reconciled.';
    END IF;
END
$$;

-- 2. Strip any accidental role memberships
DO $$
DECLARE
    r RECORD;
BEGIN
    FOR r IN
        SELECT roleid::regrole::text AS rolename
        FROM pg_auth_members
        WHERE member = 'ai_reader'::regrole
    LOOP
        EXECUTE format('REVOKE %I FROM ai_reader;', r.rolename);
        RAISE NOTICE 'Revoked membership of role % from ai_reader.', r.rolename;
    END LOOP;
END
$$;

-- 3. Database connection and schema usage
DO $$
BEGIN
    EXECUTE format('GRANT CONNECT ON DATABASE %I TO ai_reader;', current_database());
END
$$;

REVOKE ALL ON SCHEMA public FROM ai_reader;
GRANT USAGE ON SCHEMA public TO ai_reader;

-- 4. Revoke schema creation and any existing broad table/sequence/routine privileges
REVOKE CREATE ON SCHEMA public FROM ai_reader;
REVOKE ALL PRIVILEGES ON ALL TABLES IN SCHEMA public FROM ai_reader;
REVOKE ALL PRIVILEGES ON ALL SEQUENCES IN SCHEMA public FROM ai_reader;
REVOKE ALL PRIVILEGES ON ALL ROUTINES IN SCHEMA public FROM ai_reader;

-- 5. Revoke default privileges on future objects in schema public
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON TABLES FROM ai_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON SEQUENCES FROM ai_reader;
ALTER DEFAULT PRIVILEGES IN SCHEMA public REVOKE ALL ON ROUTINES FROM ai_reader;

-- 6. Grant table-level SELECT exclusively on the 5 approved AI views
GRANT SELECT ON ai_duty_roster TO ai_reader;
GRANT SELECT ON ai_attendance_summary TO ai_reader;
GRANT SELECT ON ai_eligibility_summary TO ai_reader;
GRANT SELECT ON ai_vt_candidates TO ai_reader;
GRANT SELECT ON v_vt_follow_up_status TO ai_reader;

-- 7. Grant narrow column-level SELECT on base tables (required for security_invoker = true views)
GRANT SELECT (id, name) ON classes TO ai_reader;
GRANT SELECT (id, label, exam_date) ON mst_exams TO ai_reader;
GRANT SELECT (id, class_id, roll_number, name) ON students TO ai_reader;
GRANT SELECT (id, student_id, mst_exam_id, overall_pct, lowest_subject_pct, status) ON mst_eligibility TO ai_reader;
GRANT SELECT (student_id, mst_1_appeared, mst_2_appeared, mst_1_exam_id, mst_2_exam_id, calculated_status, final_status, override, override_reason, rule_version, updated_at) ON follow_up_statuses TO ai_reader;
GRANT SELECT (mst_exam_id, room_id, faculty_id, status) ON invigilation_duties TO ai_reader;
GRANT SELECT (id, room_number) ON rooms TO ai_reader;
GRANT SELECT (id, name) ON faculty TO ai_reader;

-- 8. Verify ai_reader does not own any objects in public schema
DO $$
DECLARE
    owned_count INT;
BEGIN
    SELECT COUNT(*) INTO owned_count
    FROM pg_class c
    JOIN pg_roles r ON r.oid = c.relowner
    WHERE r.rolname = 'ai_reader';

    IF owned_count > 0 THEN
        RAISE EXCEPTION 'SECURITY DEFECT: ai_reader owns % database objects!', owned_count;
    END IF;
END
$$;

COMMIT;
