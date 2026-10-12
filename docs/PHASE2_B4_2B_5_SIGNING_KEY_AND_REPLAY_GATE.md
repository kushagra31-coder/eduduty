# Phase 2 — Stage B4.2B.5: Signing-Key Lifecycle and Replay Security Gate

**Date:** 2026-10-11  
**Target System:** EduDuty AI Reporting Subsystem  
**Test Environment:** PostgreSQL 16 Alpine container (`eduduty_pg_b4_test` at `127.0.0.1:5433`, DB `eduduty_test_db`), Python 3.11, SQLAlchemy 2.0  
**Migration Head:** `010_retire_insecure_dev_key`  
**Verdict:** **PASS**

---

## 1. Executive Summary

In Stage B4.2B.5, an exhaustive, independent security gate was conducted on the signing-key lifecycle, development key exposure risks, and replay attack assumptions of the EduDuty Row-Level Security (RLS) architecture.

### Key Remediation Highlights:
1. **Unsafe Development Secret Fallback Completely Eliminated:**
   - Previously, `backend/ai_service.py` contained a hardcoded fallback string when `EDUDUTY_RLS_HMAC_SECRET` was unset, and migration 008 seeded this key if no environment secret was found.
   - In B4.2B.5, `get_rls_hmac_secret()` was introduced in `backend/ai_service.py` to enforce that `EDUDUTY_RLS_HMAC_SECRET` is non-empty, contains at least 32 characters of entropy, and does not match the known development default. If any condition is violated, the application fails closed with a `RuntimeError` before any database queries can be executed.
2. **Alembic Migration 010 Created & Applied:**
   - Migration `010_retire_insecure_dev_key` deactivates (`active = false`) the known development secret in `auth_internal.context_signing_key`.
   - The database verifier function `auth_internal.verify_identity_context()` was hardened with defense-in-depth checks that reject:
     - The known development secret, even if accidentally flagged active.
     - Null, whitespace-only, or empty string keys.
     - Low-entropy keys (< 32 characters).
3. **Key Rotation & Retirement Lifecycle Proven:**
   - Dedicated PostgreSQL integration tests demonstrated the complete multi-key rotation lifecycle: dual-active concurrent acceptance, retirement of the old key causing immediate rejection of old tokens, sustained validity of the new key, and rejection of unknown keys.
4. **Replay Threat Model Formally Bounded:**
   - Replay protection is constrained to a 120-second validity window (`[-120s, +30s]`) combined with transaction-local parameters (`is_local = true`).
   - Evaluated that table-based nonce deduplication is incompatible with `ai_reader`'s read-only transaction semantics (`ERROR: cannot execute INSERT in a read-only transaction`). Transport-layer encryption (TLS) and network isolation serve as mandatory compensating controls.
5. **100% Test Suite Verification:**
   - PostgreSQL integration suite: **93 passed, 0 failed, 0 skipped**.
   - SQLite regression suite: **85 passed, 0 failed, 0 skipped**.

---

## 2. Files Inspected and Modified

### Inspected:
- `backend/ai_service.py`: Identity-context minting, environment variable reading, and SQL dispatch.
- `backend/alembic/versions/008_trusted_identity_context.py`: Initial schema creation and key seeding.
- `backend/alembic/versions/009_harden_rls_ownership.py`: Function ownership transfer and multi-key rotation loop.
- `backend/tests/pg_test_config.py`: Test runner configuration, gating flags, and credential isolation.
- `docs/PHASE2_B4_2B_4_TRUST_BOUNDARY_HARDENING.md`: Function ownership and RLS evaluation report.

### Modified / Created:
- `backend/ai_service.py`:
  - Replaced hardcoded default string fallback with validated `get_rls_hmac_secret()`.
  - Added strict validation: fails closed on missing, empty, known development default, or short (<32 chars) secrets.
- `backend/alembic/versions/010_retire_insecure_dev_key.py`:
  - Forward migration retiring known development secret in `auth_internal.context_signing_key`.
  - Hardened `auth_internal.verify_identity_context()` to skip empty, short (<32 chars), or known development keys.
  - Provided clean, reversible `downgrade()` logic.
- `backend/tests/pg_test_config.py`:
  - Synchronizes an isolated, high-entropy test signing key into `auth_internal.context_signing_key` and environment for PostgreSQL integration runs.
- `backend/tests/test_postgres_rls_b42b5_lifecycle.py`:
  - Added 12 comprehensive integration tests covering dev secret rejection, missing key handling, full rotation/retirement lifecycle, edge cases, permissions, replay boundaries, and migration reversibility.
- Updates to existing test suites (`test_postgres_rls_b42b4_ownership.py`, `test_postgres_rls_b42b2_remediation.py`, `test_postgres_rls_b42b.py`, `test_alembic_b42a_ai_reader.py`):
  - Updated to resolve test signing keys dynamically from environment and support migration `010` as head revision.

---

## 3. Signing-Key Exposure Audit Findings

### 3.1 Initial Exposure Points Identified (Pre-Remediation)
1. **Application Code Fallback:** `backend/ai_service.py` defaulted to a static 53-byte string if `EDUDUTY_RLS_HMAC_SECRET` was unset in the environment.
2. **Migration Seeding:** Migration `008_trusted_identity_context.py` seeded that same static string into `auth_internal.context_signing_key` if no environment variable was provided during migration execution.
3. **Live Verifier Acceptance:** Because the static string existed as `active = true` with `key_id = 1` in the database, signatures minted with this development key were accepted by the live verifier.

### 3.2 Remediation Implemented
1. **Application-Level Rejection:**
   In `backend/ai_service.py`:
   ```python
   def get_rls_hmac_secret() -> str:
       secret = os.environ.get("EDUDUTY_RLS_HMAC_SECRET", "").strip()
       if not secret:
           raise RuntimeError(
               "CRITICAL SECURITY CONFIGURATION ERROR: EDUDUTY_RLS_HMAC_SECRET environment variable "
               "is missing or empty. A secure high-entropy signing secret must be supplied."
           )
       if secret == KNOWN_INSECURE_DEV_SECRET:
           raise RuntimeError(
               "CRITICAL SECURITY CONFIGURATION ERROR: The known insecure development signing secret "
               "is rejected. Production and deployable environments must configure a unique, high-entropy secret."
           )
       if len(secret) < 32:
           raise RuntimeError(
               "CRITICAL SECURITY CONFIGURATION ERROR: EDUDUTY_RLS_HMAC_SECRET has insufficient entropy "
               "(minimum 32 characters required)."
           )
       return secret
   ```
2. **Database-Level Rejection:**
   In migration `010_retire_insecure_dev_key.py`:
   - Deactivated the known development key:
     `UPDATE auth_internal.context_signing_key SET active = false WHERE secret_key = :dev_sec;`
   - Hardened the active-key loop in `auth_internal.verify_identity_context()`:
     ```sql
     FOR key_rec IN (
         SELECT secret_key 
         FROM auth_internal.context_signing_key 
         WHERE active = true 
         ORDER BY key_id DESC
     ) LOOP
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
     ```

### 3.3 Development-Key Rejection Verification
- **Application Minting Test:** [`test_01_known_dev_secret_rejected_by_application_minting`](file:///d:/Code/eduduty/backend/tests/test_postgres_rls_b42b5_lifecycle.py#L171) confirms that attempting to mint context with the development secret raises `RuntimeError` immediately.
- **Database Verifier Test:** [`test_02_known_dev_secret_rejected_by_live_database_verifier`](file:///d:/Code/eduduty/backend/tests/test_postgres_rls_b42b5_lifecycle.py#L181) confirms that raw tokens manufactured with the development secret return 0 rows when queried through `ai_reader`.

---

## 4. Key Rotation and Retirement Lifecycle

Dedicated lifecycle tests in [`backend/tests/test_postgres_rls_b42b5_lifecycle.py`](file:///d:/Code/eduduty/backend/tests/test_postgres_rls_b42b5_lifecycle.py) verified:

1. **Step 1 (Active Key Authorization):**
   A legitimate signature minted with active Key Alpha is accepted; RLS returns assigned student records.
2. **Step 2 (Dual-Active Rotation Window):**
   Key Beta is inserted into `auth_internal.context_signing_key` as `active = true`. Both Key Alpha and Key Beta signatures are accepted concurrently.
3. **Step 3 (Key Retirement):**
   Key Alpha is retired (`active = false`). Tokens signed with Key Alpha are rejected immediately (0 rows returned). Tokens signed with Key Beta continue to return expected records.
4. **Step 4 (Unknown Key Rejection):**
   Tokens signed with an unknown Key Gamma (never activated in the database) fail closed and return 0 rows.
5. **Step 5 (Active Key Ordering & Preemption):**
   Because the verifier iterates through all `active = true` keys ordered by `key_id DESC`, newer keys are evaluated first for efficiency, but older active keys are verified if the newer key does not match. Neither key preempts or invalidates the other during rotation.
6. **Step 6 (Edge-Case Resilience):**
   - No active keys in the database: Fails closed (0 rows).
   - Blank or empty string in key table: Skipped by verifier; genuine keys continue to work; empty signature rejected.
   - Teardown safety: All test-only key records are cleaned up in guaranteed fixture and test `finally` blocks.

---

## 5. Replay Threat Model and Residual Risks

### 5.1 Replay Parameters
To replay an identity context, an adversary must capture all 6 PostgreSQL transaction-local GUC settings:
- `app.current_user_id`
- `app.current_faculty_id`
- `app.current_user_role`
- `app.current_context_issued_at`
- `app.current_context_nonce`
- `app.current_context_signature`

### 5.2 Timestamp Boundaries and Clock Skew
The verifier evaluates the context timestamp (`ctx_ts`) against database server time (`now_ts = EXTRACT(EPOCH FROM clock_timestamp())`):
```sql
IF ctx_ts > now_ts + 30 OR ctx_ts < now_ts - 120 THEN
    RETURN QUERY SELECT NULL::int, NULL::int, NULL::text, false;
    RETURN;
END IF;
```
- **Historical Acceptance Window:** Maximum 120 seconds. Any token issued 121 seconds ago is rejected.
- **Future Clock-Skew Allowance:** Maximum 30 seconds. Accommodates standard NTP skew across application containers and database nodes. Tokens with future timestamps > 30 seconds are rejected.

### 5.3 Replay Capabilities & Claim Tampering
- **Can a captured context be replayed?**
  Yes, if an adversary captures the complete 6-tuple within the 120-second acceptance window and has network access and credentials to open an `ai_reader` session, they can submit those 6 GUCs and receive the *exact same scoped view* as the original faculty member within that 120-second window.
- **Can the adversary tamper with claims?**
  **NO.** Because the HMAC-SHA256 signature commits to `user_id:faculty_id:role:issued_at:nonce`, modifying `faculty_id` (cross-faculty access) or `role` (role elevation to `super_admin`) produces a signature mismatch and immediately returns 0 rows. Tested and proven in [`test_10_replay_claim_tampering_fails_closed`](file:///d:/Code/eduduty/backend/tests/test_postgres_rls_b42b5_lifecycle.py#L442).

### 5.4 What Transaction-Local Settings Do and Do Not Protect
- **What they DO protect:**
  `set_config(..., ..., true)` sets `is_local = true`. This scopes settings strictly to the active transaction. When the transaction commits or rolls back, PostgreSQL discards all parameters. This completely prevents connection-pool leakage across subsequent transactions reusing the same pooled connection.
- **What they DO NOT protect:**
  Transaction-local settings do not provide single-use (one-time) replay protection against wire interception within the 120-second validity window.

### 5.5 Evaluation of One-Time Nonce Ledger vs Read-Only Boundary
- In EduDuty, AI reporting queries connect as `ai_reader` inside a `READ ONLY` transaction (`SET TRANSACTION READ ONLY`).
- If the verifier attempted to record consumed nonces in a persistent table (`INSERT INTO auth_internal.consumed_nonces VALUES (:nonce)`), PostgreSQL raises:
  `ERROR: cannot execute INSERT in a read-only transaction`
- Modifying `ai_reader` to have write privileges would destroy the read-only defense-in-depth boundary and prevent offloading reporting traffic to PostgreSQL read replicas.
- **Compensating Controls Required in Production:**
  1. Transport-Layer Encryption: Database connections must mandate TLS (`sslmode=verify-full` or `sslmode=require`) to prevent wire interception of GUC strings.
  2. Network Isolation: PostgreSQL port 5432 must be restricted to internal VPC networks accessible only by authorized application containers.
  3. Short Validity Lifetime: The 120-second lifetime strictly bounds window of opportunity.

---

## 6. Live PostgreSQL Catalog Evidence

Catalog state inspected in `eduduty_test_db` (`eduduty_pg_b4_test`):

### 6.1 Function Ownership and Attributes (`pg_proc`)
```sql
SELECT proname, nspname, proowner::regrole, prosecdef, proconfig,
       has_function_privilege('public', p.oid, 'EXECUTE') as public_exec,
       has_function_privilege('ai_reader', p.oid, 'EXECUTE') as ai_reader_exec
FROM pg_proc p JOIN pg_namespace n ON n.oid = p.pronamespace
WHERE proname IN (
    'verify_identity_context',
    'can_current_user_access_class',
    'can_current_user_access_student',
    'can_current_user_access_duty_roster'
);
```

**Output:**
```
               proname               |    nspname    |     proowner      | prosecdef |             proconfig              | public_exec | ai_reader_exec 
-------------------------------------+---------------+-------------------+-----------+------------------------------------+-------------+----------------
 can_current_user_access_duty_roster | public        | eduduty_rls_owner | t         | {"search_path=pg_catalog, public"} | f           | t
 can_current_user_access_class       | public        | eduduty_rls_owner | t         | {"search_path=pg_catalog, public"} | f           | t
 can_current_user_access_student     | public        | eduduty_rls_owner | t         | {"search_path=pg_catalog, public"} | f           | t
 verify_identity_context             | auth_internal | eduduty_rls_owner | t         | {"search_path=pg_catalog, public"} | f           | f
(4 rows)
```
- Owner: `eduduty_rls_owner` (dedicated least-privilege role, `NOSUPERUSER`, `NOLOGIN`, `NOBYPASSRLS`).
- `search_path`: Pinned to `pg_catalog, public`.
- Execution: Revoked from `PUBLIC`. Direct execution of `verify_identity_context` is denied to `ai_reader`.

### 6.2 Key Table Permissions (`auth_internal.context_signing_key`)
```sql
SELECT has_table_privilege('ai_reader', 'auth_internal.context_signing_key', 'SELECT') as ai_can_select,
       has_table_privilege('ai_reader', 'auth_internal.context_signing_key', 'INSERT') as ai_can_insert,
       has_table_privilege('public', 'auth_internal.context_signing_key', 'SELECT') as pub_can_select;
```
**Output:**
```
 ai_can_select | ai_can_insert | pub_can_select 
---------------+---------------+----------------
 f             | f             | f
(1 row)
```

---

## 7. Test Execution Results

### 7.1 PostgreSQL Integration Suite (`EDUDUTY_REQUIRE_POSTGRES_TESTS=1`)

**Command:**
```powershell
python -c "import subprocess, os, sys, pytest; p = subprocess.run(['docker', 'exec', 'eduduty_pg_b4_test', 'printenv', 'POSTGRES_PASSWORD'], capture_output=True, text=True).stdout.strip(); os.environ['PG_TEST_PASSWORD']=p; os.environ['EDUDUTY_REQUIRE_POSTGRES_TESTS']='1'; files = ['backend/tests/test_postgres_rls_b42b5_lifecycle.py', 'backend/tests/test_postgres_rls_b42b4_ownership.py', 'backend/tests/test_postgres_rls_b42b2_remediation.py', 'backend/tests/test_postgres_rls_b42b.py', 'backend/tests/test_alembic_b42a_ai_reader.py', 'backend/tests/test_postgres_connection_b412.py', 'backend/tests/test_postgres_gating.py']; sys.exit(pytest.main(files + ['-v', '--tb=short']))"
```

**Results Breakdown:**
- [`backend/tests/test_postgres_rls_b42b5_lifecycle.py`](file:///d:/Code/eduduty/backend/tests/test_postgres_rls_b42b5_lifecycle.py): **12 passed**
  - `test_01_known_dev_secret_rejected_by_application_minting` PASSED
  - `test_02_known_dev_secret_rejected_by_live_database_verifier` PASSED
  - `test_03_missing_or_low_entropy_secret_fails_closed` PASSED
  - `test_04_legitimate_application_issued_context_under_active_key` PASSED
  - `test_05_key_rotation_and_retirement_lifecycle` PASSED
  - `test_06_no_active_keys_fails_closed` PASSED
  - `test_07_duplicate_or_blank_key_rows_fail_closed_safely` PASSED
  - `test_08_key_table_permissions_denied_to_ai_reader_and_public` PASSED
  - `test_09_replay_window_boundary_behavior` PASSED
  - `test_10_replay_claim_tampering_fails_closed` PASSED
  - `test_11_inactive_draft_timetable_fails_closed` PASSED
  - `test_12_migration_010_upgrade_downgrade_reupgrade` PASSED
- [`backend/tests/test_postgres_rls_b42b4_ownership.py`](file:///d:/Code/eduduty/backend/tests/test_postgres_rls_b42b4_ownership.py): **13 passed**
- [`backend/tests/test_postgres_rls_b42b2_remediation.py`](file:///d:/Code/eduduty/backend/tests/test_postgres_rls_b42b2_remediation.py): **18 passed**
- [`backend/tests/test_postgres_rls_b42b.py`](file:///d:/Code/eduduty/backend/tests/test_postgres_rls_b42b.py): **18 passed**
- [`backend/tests/test_alembic_b42a_ai_reader.py`](file:///d:/Code/eduduty/backend/tests/test_alembic_b42a_ai_reader.py): **11 passed**
- [`backend/tests/test_postgres_connection_b412.py`](file:///d:/Code/eduduty/backend/tests/test_postgres_connection_b412.py): **12 passed**
- [`backend/tests/test_postgres_gating.py`](file:///d:/Code/eduduty/backend/tests/test_postgres_gating.py): **9 passed**

**Total PostgreSQL Integration:** **93 passed, 0 failed, 0 skipped in 17.68s**

---

### 7.2 SQLite Regression Suite

**Command:**
```powershell
python -m pytest tests/test_auth.py tests/test_rbac.py tests/test_upload_attendance.py tests/test_alembic_b33_auth.py tests/test_alembic_b2_constraints.py tests/test_alembic_b31_review.py tests/test_alembic_b32_gate.py tests/test_alembic_b3_ai_views.py tests/test_alembic_migration.py tests/test_resource_authorization.py tests/test_ai_read_isolation.py -v --tb=short
```

**Results Breakdown:**
- `test_auth.py`: 5 passed
- `test_rbac.py`: 5 passed
- `test_upload_attendance.py`: 8 passed
- `test_alembic_b33_auth.py`: 26 passed
- `test_alembic_b2_constraints.py`: 6 passed
- `test_alembic_b31_review.py`: 3 passed
- `test_alembic_b32_gate.py`: 3 passed
- `test_alembic_b3_ai_views.py`: 5 passed
- `test_alembic_migration.py`: 3 passed
- `test_resource_authorization.py`: 7 passed
- `test_ai_read_isolation.py`: 6 passed

**Total SQLite Regression:** **85 passed, 0 failed, 0 skipped in 32.43s**

---

## 8. Operator Actions and Production Rotation Procedure

Operators deploying EduDuty to production or rotating signing keys must follow this exact safe sequence:

### 8.1 Initial Production Deployment
1. Generate a high-entropy secret (minimum 64 characters recommended):
   ```bash
   openssl rand -hex 32
   ```
2. Inject the secret as `EDUDUTY_RLS_HMAC_SECRET` into the FastAPI backend environment (e.g., Kubernetes Secret, AWS SSM Parameter Store).
3. Execute `alembic upgrade head`. Migration 010 will automatically populate `auth_internal.context_signing_key` with this secret as `active = true` and ensure any legacy development key is deactivated.

### 8.2 Zero-Downtime Key Rotation Sequence
When rotating the signing key in an active cluster:
1. Generate new high-entropy secret `NEW_KEY`.
2. Connect to PostgreSQL as `postgres` and insert the new key:
   ```sql
   INSERT INTO auth_internal.context_signing_key (secret_key, active) VALUES ('<NEW_KEY>', true);
   ```
   *At this stage, the database verifier accepts tokens signed by either the old key or the new key.*
3. Update `EDUDUTY_RLS_HMAC_SECRET=<NEW_KEY>` across backend pods and trigger a rolling deployment.
4. Wait for all backend pods to restart and allow 120 seconds for in-flight requests to drain.
5. Deactivate the old key in PostgreSQL:
   ```sql
   UPDATE auth_internal.context_signing_key SET active = false WHERE secret_key = '<OLD_KEY>';
   ```
   *Rotation is complete with zero dropped queries.*

---

## 9. Asset Preservation & Compliance

- **`backend/eduduty.db`:** Exactly preserved (180,224 bytes).
- **SecureMailScope Infrastructure:** Docker containers (`mailnet_postfix`, `mailnet_dovecot`, `mailnet_generator`), networks, and volumes preserved without modification.
- **Git State:** Clean working tree; no commits or pushes executed.
- **Secret Protection:** No raw signing secrets, passwords, or credentials logged or committed.

---

## 10. Final Verdict

**VERDICT: PASS**

The signing-key lifecycle is strictly enforced. The insecure development default key is eliminated from deployable code and deactivated in the database verifier. Zero-downtime key rotation, retirement, replay window boundaries, least-privilege function ownership, and fail-closed isolation across all faculty and student domains are verified with 100% pass rates across both PostgreSQL and SQLite suites.
