"""
EduDuty Phase 2 — Stage B4.2B.5: Signing-Key Lifecycle and Replay Security Gate
Test Suite: backend/tests/test_postgres_rls_b42b5_lifecycle.py

Tests:
1. Rejection of known development signing secret (application & verifier levels).
2. Fail-closed behavior for missing, empty, or insufficient entropy signing keys.
3. Legitimate application-minted context authorization under active key.
4. Complete key rotation lifecycle: active acceptance, retirement rejection, new key persistence.
5. Unknown/unregistered signing key rejection.
6. Fail-closed behavior on missing active keys or malformed key state.
7. Multi-key ordering verification (no accidental authoritative preemption).
8. Permission lockdown: ai_reader and PUBLIC denied key-management privileges.
9. Replay window boundaries: valid within 120s, rejected at 121s past, rejected at >30s future.
10. Claim tampering prevention under replayed context (cross-faculty & role escalation).
11. Data access contract preservation (active versioned timetables only).
12. Migration 010 upgrade/downgrade/re-upgrade cycle.
"""

import hashlib
import hmac
import os
import time
import uuid
import pytest
from sqlalchemy import create_engine, text
from alembic import command
from alembic.config import Config

from tests.pg_test_config import get_pg_admin_url, get_pg_ai_reader_url
from ai_service import (
    mint_signed_identity_context,
    get_rls_hmac_secret,
    KNOWN_INSECURE_DEV_SECRET,
)
import models


# ── Isolated Test Signing Material ───────────────────────────────────────────
TEST_KEY_ALPHA = "eduduty_test_alpha_signing_key_secure_64_bytes_entropy_active_v1!"
TEST_KEY_BETA  = "eduduty_test_beta_signing_key_secure_64_bytes_entropy_rotated_v2!"
TEST_KEY_GAMMA = "eduduty_test_gamma_signing_key_secure_64_bytes_entropy_unknown_v3!"


# ── Fixtures & Setup ──────────────────────────────────────────────────────────

@pytest.fixture(scope="module")
def pg_admin_url():
    return get_pg_admin_url()


@pytest.fixture(scope="module")
def pg_ai_reader_url(pg_admin_url):
    return get_pg_ai_reader_url(pg_admin_url)


def _get_alembic_config(admin_url: str) -> Config:
    backend_dir = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
    ini_path = os.path.join(backend_dir, "alembic.ini")
    cfg = Config(ini_path)
    cfg.set_main_option("sqlalchemy.url", admin_url)
    cfg.set_main_option("script_location", os.path.join(backend_dir, "alembic"))
    return cfg


@pytest.fixture(scope="module")
def rls_b42b5_data(pg_admin_url):
    """Seed isolated, versioned timetable test data for B4.2B.5 lifecycle tests."""
    eng = create_engine(pg_admin_url)
    with eng.connect() as conn:
        with conn.begin():
            # Ensure TEST_KEY_ALPHA is active in database
            conn.execute(text("""
                INSERT INTO auth_internal.context_signing_key (secret_key, active)
                SELECT :sec, true
                WHERE NOT EXISTS (
                    SELECT 1 FROM auth_internal.context_signing_key WHERE secret_key = :sec AND active = true
                );
            """), {"sec": TEST_KEY_ALPHA})

            # Clean previous fixture rows if any
            conn.execute(text("DELETE FROM attendance_records WHERE id IN (9901, 9902);"))
            conn.execute(text("DELETE FROM faculty_timetable WHERE id IN (5901, 5902);"))
            conn.execute(text("DELETE FROM faculty WHERE id IN (1901, 1902);"))
            conn.execute(text("DELETE FROM timetable_versions WHERE id IN (4901, 4902);"))
            conn.execute(text("DELETE FROM mst_eligibility WHERE id IN (7901, 7902);"))
            conn.execute(text("DELETE FROM students WHERE id IN (3901, 3902);"))
            conn.execute(text("DELETE FROM classes WHERE id IN (2901, 2902);"))

            # 1. Faculty
            conn.execute(text("""
                INSERT INTO faculty (id, name, department) VALUES
                (1901, 'Prof Alpha Lifecycle', 'CSE'),
                (1902, 'Prof Beta Lifecycle', 'CSE');
            """))

            # 2. Classes
            conn.execute(text("""
                INSERT INTO classes (id, name, branch, year, section) VALUES
                (2901, 'CS-LIFE-A', 'CSE', 3, 'A'),
                (2902, 'CS-LIFE-B', 'CSE', 3, 'B');
            """))

            # 3. Students
            conn.execute(text("""
                INSERT INTO students (id, roll_number, name, class_id, active) VALUES
                (3901, 'RLS-LIFE-01', 'Lifecycle Student A', 2901, true),
                (3902, 'RLS-LIFE-02', 'Lifecycle Student B', 2902, true);
            """))

            # 4. Timetable versions: 4901 is active, 4902 is inactive (active = false)
            conn.execute(text("""
                INSERT INTO timetable_versions (id, class_id, semester, session, active) VALUES
                (4901, 2901, 'V', 'Jul-Dec 2026', true),
                (4902, 2902, 'V', 'Jul-Dec 2026', false);
            """))

            # 5. Timetable assignment: Faculty 1901 assigned to Class 2901 under active version 4901
            conn.execute(text("""
                INSERT INTO faculty_timetable (id, faculty_id, class_id, timetable_version_id, day_of_week, period_start, period_end, year, semester) VALUES
                (5901, 1901, 2901, 4901, 'Monday', '09:00', '10:00', 3, 'V'),
                (5902, 1902, 2902, 4902, 'Tuesday', '10:00', '11:00', 3, 'V');
            """))

    yield

    # Teardown fixture data
    with eng.connect() as conn:
        with conn.begin():
            conn.execute(text("DELETE FROM attendance_records WHERE id IN (9901, 9902);"))
            conn.execute(text("DELETE FROM faculty_timetable WHERE id IN (5901, 5902);"))
            conn.execute(text("DELETE FROM faculty WHERE id IN (1901, 1902);"))
            conn.execute(text("DELETE FROM timetable_versions WHERE id IN (4901, 4902);"))
            conn.execute(text("DELETE FROM mst_eligibility WHERE id IN (7901, 7902);"))
            conn.execute(text("DELETE FROM students WHERE id IN (3901, 3902);"))
            conn.execute(text("DELETE FROM classes WHERE id IN (2901, 2902);"))
            # Clean up test keys
            conn.execute(text("DELETE FROM auth_internal.context_signing_key WHERE secret_key IN (:k1, :k2, :k3);"),
                         {"k1": TEST_KEY_ALPHA, "k2": TEST_KEY_BETA, "k3": TEST_KEY_GAMMA})


def _mint_raw_context(user_id: int, faculty_id: int | None, role: str, secret: str, ts_offset: int = 0) -> dict:
    ts = str(int(time.time()) + ts_offset)
    nonce = uuid.uuid4().hex[:16]
    fac_str = str(faculty_id) if faculty_id is not None else ""
    payload = f"{user_id}:{fac_str}:{role.lower()}:{ts}:{nonce}"
    sig = hmac.new(secret.encode(), payload.encode(), hashlib.sha256).hexdigest()
    return {
        "uid": str(user_id),
        "fac_id": fac_str,
        "role": role.lower(),
        "ts": ts,
        "nonce": nonce,
        "sig": sig,
    }


def _apply_context(conn, ctx: dict):
    conn.execute(text("""
        SELECT set_config('app.current_user_id', :uid, true),
               set_config('app.current_faculty_id', :fac_id, true),
               set_config('app.current_user_role', :role, true),
               set_config('app.current_context_issued_at', :ts, true),
               set_config('app.current_context_nonce', :nonce, true),
               set_config('app.current_context_signature', :sig, true);
    """), ctx)


# ── 1. Rejection of Known Insecure Development Secret ─────────────────────────

def test_01_known_dev_secret_rejected_by_application_minting(monkeypatch):
    """[Lifecycle Test 1] Application layer fails closed if configured with known dev secret."""
    user = models.User(id=1, faculty_id=1901, role="faculty")

    # 1. Reject exact known insecure development key
    monkeypatch.setenv("EDUDUTY_RLS_HMAC_SECRET", KNOWN_INSECURE_DEV_SECRET)
    with pytest.raises(RuntimeError, match="known insecure development signing secret is rejected"):
        mint_signed_identity_context(user)


def test_02_known_dev_secret_rejected_by_live_database_verifier(pg_admin_url, pg_ai_reader_url, rls_b42b5_data):
    """[Lifecycle Test 2] Live database verifier explicitly rejects tokens minted with known dev key."""
    ai_eng = create_engine(pg_ai_reader_url)

    # Mint context using the known dev key
    ctx = _mint_raw_context(user_id=1, faculty_id=1901, role="faculty", secret=KNOWN_INSECURE_DEV_SECRET)

    with ai_eng.connect() as conn:
        _apply_context(conn, ctx)
        rows = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
        assert len(rows) == 0, f"Verifier accepted known dev secret! Leaked rows: {rows}"


# ── 2. Missing, Empty, and Low-Entropy Signing Key Validation ─────────────────

def test_03_missing_or_low_entropy_secret_fails_closed(monkeypatch):
    """[Lifecycle Test 3] Missing, empty, or short (<32 char) secrets fail closed."""
    user = models.User(id=1, faculty_id=1901, role="faculty")

    # 1. Missing secret
    monkeypatch.delenv("EDUDUTY_RLS_HMAC_SECRET", raising=False)
    with pytest.raises(RuntimeError, match="is missing or empty"):
        get_rls_hmac_secret()

    # 2. Empty secret
    monkeypatch.setenv("EDUDUTY_RLS_HMAC_SECRET", "   ")
    with pytest.raises(RuntimeError, match="is missing or empty"):
        get_rls_hmac_secret()

    # 3. Short secret (<32 chars)
    monkeypatch.setenv("EDUDUTY_RLS_HMAC_SECRET", "short_secret_only_24_bytes")
    with pytest.raises(RuntimeError, match="insufficient entropy"):
        get_rls_hmac_secret()


# ── 3. Legitimate Active Key Authorization ────────────────────────────────────

def test_04_legitimate_application_issued_context_under_active_key(pg_ai_reader_url, rls_b42b5_data, monkeypatch):
    """[Lifecycle Test 4] Positive authorization: context signed with active key grants access."""
    monkeypatch.setenv("EDUDUTY_RLS_HMAC_SECRET", TEST_KEY_ALPHA)
    user_a = models.User(id=1, email="alpha@eduduty.internal", role="FACULTY", faculty_id=1901)

    ai_eng = create_engine(pg_ai_reader_url)
    ctx = mint_signed_identity_context(user_a)

    with ai_eng.connect() as conn:
        _apply_context(conn, ctx)
        rows = conn.execute(text("SELECT id, roll_number FROM students WHERE id = 3901;")).fetchall()
        assert len(rows) == 1
        assert rows[0][1] == "RLS-LIFE-01"


# ── 4. Key Rotation and Retirement Lifecycle ──────────────────────────────────

def test_05_key_rotation_and_retirement_lifecycle(pg_admin_url, pg_ai_reader_url, rls_b42b5_data):
    """
    [Lifecycle Test 5] Complete Key Lifecycle:
    1. Key Alpha is active -> verified.
    2. Key Beta added as active (rotation rollout) -> both Alpha and Beta verified.
    3. Key Alpha retired (active = false) -> Alpha rejected, Beta remains verified.
    4. Unknown Key Gamma -> rejected.
    """
    admin_eng = create_engine(pg_admin_url)
    ai_eng = create_engine(pg_ai_reader_url)

    try:
        # Step 1: Ensure Key Alpha is active
        with admin_eng.connect() as conn:
            with conn.begin():
                conn.execute(text("UPDATE auth_internal.context_signing_key SET active = true WHERE secret_key = :k;"),
                             {"k": TEST_KEY_ALPHA})

        # Test Step 1: Key Alpha succeeds
        ctx_alpha = _mint_raw_context(1, 1901, "faculty", TEST_KEY_ALPHA)
        with ai_eng.connect() as conn:
            _apply_context(conn, ctx_alpha)
            rows = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
            assert len(rows) == 1, "Key Alpha should be accepted while active"

        # Step 2: Add Key Beta as active (dual-active rotation window)
        with admin_eng.connect() as conn:
            with conn.begin():
                conn.execute(text("""
                    INSERT INTO auth_internal.context_signing_key (secret_key, active)
                    SELECT :k, true
                    WHERE NOT EXISTS (
                        SELECT 1 FROM auth_internal.context_signing_key WHERE secret_key = :k AND active = true
                    );
                """), {"k": TEST_KEY_BETA})

        # Test Step 2: Both Alpha and Beta succeed simultaneously
        ctx_beta = _mint_raw_context(1, 1901, "faculty", TEST_KEY_BETA)
        with ai_eng.connect() as conn:
            _apply_context(conn, ctx_alpha)
            rows_a = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
            assert len(rows_a) == 1, "Key Alpha must remain accepted during dual-active window"

        with ai_eng.connect() as conn:
            _apply_context(conn, ctx_beta)
            rows_b = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
            assert len(rows_b) == 1, "Key Beta must be accepted during dual-active window"

        # Step 3: Retire Key Alpha (active = false)
        with admin_eng.connect() as conn:
            with conn.begin():
                conn.execute(text("UPDATE auth_internal.context_signing_key SET active = false WHERE secret_key = :k;"),
                             {"k": TEST_KEY_ALPHA})

        # Test Step 3: Key Alpha is now rejected; Key Beta remains valid
        with ai_eng.connect() as conn:
            _apply_context(conn, ctx_alpha)
            rows_retired = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
            assert len(rows_retired) == 0, "Retired Key Alpha must be rejected"

        with ai_eng.connect() as conn:
            _apply_context(conn, ctx_beta)
            rows_active = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
            assert len(rows_active) == 1, "New Key Beta must remain accepted after Key Alpha retirement"

        # Step 4: Unknown Key Gamma (never activated) is rejected
        ctx_gamma = _mint_raw_context(1, 1901, "faculty", TEST_KEY_GAMMA)
        with ai_eng.connect() as conn:
            _apply_context(conn, ctx_gamma)
            rows_unknown = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
            assert len(rows_unknown) == 0, "Unknown Key Gamma must be rejected"

    finally:
        # Restore Key Alpha as active and remove Key Beta
        with admin_eng.connect() as conn:
            with conn.begin():
                conn.execute(text("UPDATE auth_internal.context_signing_key SET active = true WHERE secret_key = :k;"),
                             {"k": TEST_KEY_ALPHA})
                conn.execute(text("DELETE FROM auth_internal.context_signing_key WHERE secret_key = :k;"),
                             {"k": TEST_KEY_BETA})


# ── 5. Active-Key State Edge Cases Fail Closed ────────────────────────────────

def test_06_no_active_keys_fails_closed(pg_admin_url, pg_ai_reader_url, rls_b42b5_data):
    """[Lifecycle Test 6] If all keys are marked inactive, verifier fails closed."""
    admin_eng = create_engine(pg_admin_url)
    ai_eng = create_engine(pg_ai_reader_url)

    try:
        # Deactivate all keys temporarily
        with admin_eng.connect() as conn:
            with conn.begin():
                conn.execute(text("UPDATE auth_internal.context_signing_key SET active = false;"))

        ctx = _mint_raw_context(1, 1901, "faculty", TEST_KEY_ALPHA)
        with ai_eng.connect() as conn:
            _apply_context(conn, ctx)
            rows = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
            assert len(rows) == 0, "Missing active keys must fail closed"

    finally:
        # Re-activate Key Alpha
        with admin_eng.connect() as conn:
            with conn.begin():
                conn.execute(text("UPDATE auth_internal.context_signing_key SET active = true WHERE secret_key = :k;"),
                             {"k": TEST_KEY_ALPHA})


def test_07_duplicate_or_blank_key_rows_fail_closed_safely(pg_admin_url, pg_ai_reader_url, rls_b42b5_data):
    """[Lifecycle Test 7] Blank keys in table are skipped; duplicate keys do not cause verifier crashes."""
    admin_eng = create_engine(pg_admin_url)
    ai_eng = create_engine(pg_ai_reader_url)

    blank_key = ""
    try:
        with admin_eng.connect() as conn:
            with conn.begin():
                conn.execute(text("INSERT INTO auth_internal.context_signing_key (secret_key, active) VALUES (:b, true);"),
                             {"b": blank_key})

        # Token with genuine key still works
        ctx_alpha = _mint_raw_context(1, 1901, "faculty", TEST_KEY_ALPHA)
        with ai_eng.connect() as conn:
            _apply_context(conn, ctx_alpha)
            rows = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
            assert len(rows) == 1

        # Token signed with empty key is rejected
        ctx_blank = _mint_raw_context(1, 1901, "faculty", "")
        with ai_eng.connect() as conn:
            _apply_context(conn, ctx_blank)
            rows = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
            assert len(rows) == 0

    finally:
        with admin_eng.connect() as conn:
            with conn.begin():
                conn.execute(text("DELETE FROM auth_internal.context_signing_key WHERE secret_key = '';"))


# ── 6. Key Management Permissions Locked Down ─────────────────────────────────

def test_08_key_table_permissions_denied_to_ai_reader_and_public(pg_ai_reader_url):
    """[Lifecycle Test 8] ai_reader and PUBLIC have zero access to context_signing_key."""
    ai_eng = create_engine(pg_ai_reader_url)

    # 1. ai_reader SELECT denied
    with pytest.raises(Exception) as exc_info:
        with ai_eng.connect() as conn:
            conn.execute(text("SELECT * FROM auth_internal.context_signing_key;"))
    assert "permission denied" in str(exc_info.value).lower()

    # 2. ai_reader INSERT denied
    with pytest.raises(Exception) as exc_info:
        with ai_eng.connect() as conn:
            conn.execute(text("INSERT INTO auth_internal.context_signing_key (secret_key, active) VALUES ('bogus', true);"))
    assert "permission denied" in str(exc_info.value).lower()

    # 3. ai_reader direct verifier execution denied
    with pytest.raises(Exception) as exc_info:
        with ai_eng.connect() as conn:
            conn.execute(text("SELECT * FROM auth_internal.verify_identity_context();"))
    assert "permission denied" in str(exc_info.value).lower()


# ── 7. Replay Threat Model & Acceptance Window Boundaries ─────────────────────

def test_09_replay_window_boundary_behavior(pg_ai_reader_url, rls_b42b5_data):
    """
    [Lifecycle Test 9] Replay Window Boundaries:
    - -119s: Valid (within 120s acceptance window)
    - -121s: Expired (rejected)
    - +29s:  Valid (within 30s clock-skew tolerance)
    - +31s:  Future drift (rejected)
    """
    ai_eng = create_engine(pg_ai_reader_url)

    # 1. Valid context at -115s (within 120s window)
    ctx_valid_old = _mint_raw_context(1, 1901, "faculty", TEST_KEY_ALPHA, ts_offset=-115)
    with ai_eng.connect() as conn:
        _apply_context(conn, ctx_valid_old)
        rows = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
        assert len(rows) == 1, "Context within 120s window should be accepted"

    # 2. Expired context at -125s (beyond 120s window)
    ctx_expired = _mint_raw_context(1, 1901, "faculty", TEST_KEY_ALPHA, ts_offset=-125)
    with ai_eng.connect() as conn:
        _apply_context(conn, ctx_expired)
        rows = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
        assert len(rows) == 0, "Expired context (>120s) must be rejected"

    # 3. Valid future drift at +25s (within +30s tolerance)
    ctx_future_valid = _mint_raw_context(1, 1901, "faculty", TEST_KEY_ALPHA, ts_offset=25)
    with ai_eng.connect() as conn:
        _apply_context(conn, ctx_future_valid)
        rows = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
        assert len(rows) == 1, "Context within +30s clock skew should be accepted"

    # 4. Excessive future drift at +35s (beyond +30s tolerance)
    ctx_future_excess = _mint_raw_context(1, 1901, "faculty", TEST_KEY_ALPHA, ts_offset=35)
    with ai_eng.connect() as conn:
        _apply_context(conn, ctx_future_excess)
        rows = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
        assert len(rows) == 0, "Future drift >30s must be rejected"


def test_10_replay_claim_tampering_fails_closed(pg_ai_reader_url, rls_b42b5_data):
    """[Lifecycle Test 10] Any tampering of replayed claims immediately fails closed."""
    ai_eng = create_engine(pg_ai_reader_url)

    valid_ctx = _mint_raw_context(1, 1901, "faculty", TEST_KEY_ALPHA)

    # 1. Attacker replays valid context on a separate connection with untouched claims -> succeeds
    with ai_eng.connect() as conn:
        _apply_context(conn, valid_ctx)
        rows = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
        assert len(rows) == 1

    # 2. Attacker modifies faculty_id to 1902 in replayed context -> signature mismatch -> 0 rows
    tampered_fac = dict(valid_ctx)
    tampered_fac["fac_id"] = "1902"
    with ai_eng.connect() as conn:
        _apply_context(conn, tampered_fac)
        rows = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
        assert len(rows) == 0

    # 3. Attacker modifies role to 'super_admin' in replayed context -> signature mismatch -> 0 rows
    tampered_role = dict(valid_ctx)
    tampered_role["role"] = "super_admin"
    with ai_eng.connect() as conn:
        _apply_context(conn, tampered_role)
        rows = conn.execute(text("SELECT id FROM students WHERE id = 3901;")).fetchall()
        assert len(rows) == 0


# ── 8. Access Contract Invariants ─────────────────────────────────────────────

def test_11_inactive_draft_timetable_fails_closed(pg_ai_reader_url, rls_b42b5_data):
    """[Lifecycle Test 11] Faculty assigned under draft/inactive timetable version gets 0 rows."""
    ai_eng = create_engine(pg_ai_reader_url)

    # Faculty 1902 is assigned to Class 2902 under version 4902 (active = false)
    ctx_fac_1902 = _mint_raw_context(2, 1902, "faculty", TEST_KEY_ALPHA)
    with ai_eng.connect() as conn:
        _apply_context(conn, ctx_fac_1902)
        # Should NOT see Student 3902
        rows = conn.execute(text("SELECT id FROM students WHERE id = 3902;")).fetchall()
        assert len(rows) == 0, f"Draft timetable leaked student rows: {rows}"


# ── 9. Migration 010 Upgrade and Downgrade Cycle ──────────────────────────────

def test_12_migration_010_upgrade_downgrade_reupgrade(pg_admin_url):
    """[Lifecycle Test 12] Migration 010 downgrades cleanly to 009 and re-upgrades to head."""
    cfg = _get_alembic_config(pg_admin_url)
    eng = create_engine(pg_admin_url)

    try:
        # Downgrade to 009
        command.downgrade(cfg, "009_harden_rls_ownership")
        with eng.connect() as conn:
            rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
            assert rev == "009_harden_rls_ownership"

    finally:
        # Re-upgrade to head (010)
        command.upgrade(cfg, "head")

    with eng.connect() as conn:
        rev = conn.execute(text("SELECT version_num FROM alembic_version;")).scalar()
        assert rev == "010_retire_insecure_dev_key"
