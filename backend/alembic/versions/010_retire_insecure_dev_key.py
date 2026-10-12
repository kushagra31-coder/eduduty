"""Retire insecure development signing key and enforce secure key lifecycle

Revision ID: 010_retire_insecure_dev_key
Revises: 009_harden_rls_ownership
Create Date: 2026-10-11 20:30:00.000000

"""
import os
from typing import Sequence, Union
from alembic import op
import sqlalchemy as sa


# revision identifiers, used by Alembic.
revision: str = '010_retire_insecure_dev_key'
down_revision: Union[str, None] = '009_harden_rls_ownership'
branch_labels: Union[str, Sequence[str], None] = None
depends_on: Union[str, Sequence[str], None] = None

KNOWN_INSECURE_DEV_SECRET = "eduduty_insecure_default_hmac_secret_for_dev_only_32b"


def upgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        # 1. Deactivate known insecure development signing secret
        op.execute(sa.text("""
            UPDATE auth_internal.context_signing_key
            SET active = false
            WHERE secret_key = :dev_sec;
        """).bindparams(dev_sec=KNOWN_INSECURE_DEV_SECRET))

        # 2. If a secure high-entropy key is provided in environment, seed it if no active key exists
        env_secret = os.environ.get("EDUDUTY_RLS_HMAC_SECRET", "").strip()
        if env_secret and env_secret != KNOWN_INSECURE_DEV_SECRET and len(env_secret) >= 32:
            op.execute(sa.text("""
                INSERT INTO auth_internal.context_signing_key (secret_key, active)
                SELECT :sec, true
                WHERE NOT EXISTS (
                    SELECT 1 FROM auth_internal.context_signing_key
                    WHERE secret_key = :sec AND active = true
                );
            """).bindparams(sec=env_secret))

        # 3. Update auth_internal.verify_identity_context() with explicit dev secret rejection
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
                ctx_ts bigint;
                now_ts bigint;
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

                -- 4. Verify signature across active signing keys, rejecting known dev secret
                FOR key_rec IN (
                    SELECT secret_key 
                    FROM auth_internal.context_signing_key 
                    WHERE active = true 
                    ORDER BY key_id DESC
                ) LOOP
                    -- Reject null, empty, short (<32 chars), or known insecure development keys
                    IF key_rec.secret_key IS NULL OR
                       TRIM(key_rec.secret_key) = '' OR
                       length(key_rec.secret_key) < 32 OR
                       key_rec.secret_key = 'eduduty_insecure_default_hmac_secret_for_dev_only_32b' THEN
                        CONTINUE;
                    END IF;

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

        # Ensure ownership and execute privileges remain locked down
        op.execute("ALTER FUNCTION auth_internal.verify_identity_context() OWNER TO eduduty_rls_owner;")
        op.execute("REVOKE EXECUTE ON FUNCTION auth_internal.verify_identity_context() FROM PUBLIC, ai_reader;")
        op.execute("GRANT EXECUTE ON FUNCTION auth_internal.verify_identity_context() TO eduduty_rls_owner, postgres;")


def downgrade() -> None:
    bind = op.get_bind()
    is_pg = bind.dialect.name == "postgresql"

    if is_pg:
        # Revert verify_identity_context() to migration 009 definition
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
                ctx_ts bigint;
                now_ts bigint;
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

                canonical_payload := raw_uid || ':' || COALESCE(raw_fac, '') || ':' || raw_role || ':' || raw_ts || ':' || raw_nonce;

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

        op.execute("ALTER FUNCTION auth_internal.verify_identity_context() OWNER TO eduduty_rls_owner;")
        op.execute("REVOKE EXECUTE ON FUNCTION auth_internal.verify_identity_context() FROM PUBLIC, ai_reader;")
        op.execute("GRANT EXECUTE ON FUNCTION auth_internal.verify_identity_context() TO eduduty_rls_owner, postgres;")
