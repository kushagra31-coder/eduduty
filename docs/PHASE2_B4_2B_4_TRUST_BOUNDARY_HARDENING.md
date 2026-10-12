# Phase 2 — Stage B4.2B.4: Privileged Function Ownership and Signing Authority Hardening

**Date:** 2026-10-11  
**Target System:** EduDuty AI Reporting Subsystem  
**Test Environment:** PostgreSQL 16 Alpine container (`eduduty_pg_b4_test` at `127.0.0.1:5433`, DB `eduduty_test_db`), Python 3.11, SQLAlchemy 2.0  
**Migration Head:** `009_harden_rls_ownership`  
**Verdict:** **PASS**

---

## 1. Executive Summary

In Stage B4.2B.3, the independent security verification identified two architectural and least-privilege concerns remaining in the implementation:
1. **Superuser Ownership of `SECURITY DEFINER` Functions:** Functions `auth_internal.verify_identity_context()`, `can_current_user_access_class()`, `can_current_user_access_student()`, and `can_current_user_access_duty_roster()` were owned by `postgres` (superuser), violating the principle of least privilege.
2. **Key Rotation Single-Key Invalidation Risk:** The initial verifier queried only `LIMIT 1` active key, creating a deployment race condition where introducing a new signing key before all application pods rotate would immediately invalidate in-flight tokens minted with the previous key.

In **B4.2B.4**, both concerns were remediated and verified:
- **Dedicated Function Owner Role:** Created `eduduty_rls_owner` with `NOLOGIN NOSUPERUSER NOCREATEDB NOCREATEROLE NOBYPASSRLS`. All four security helpers were transferred to this role.
- **Strict Least-Privilege Grants:** `eduduty_rls_owner` owns **0 application tables** and has **0 write/DDL privileges** across all schemas. It possesses only `SELECT` privileges on the 5 tables strictly required for policy evaluation (`context_signing_key`, `students`, `classes`, `faculty_timetable`, `timetable_versions`).
- **Non-Recursive Definer Owner Policies:** Because `eduduty_rls_owner` has `NOBYPASSRLS`, explicit `SELECT` policies (`rls_students_definer_owner`, `rls_classes_definer_owner`) were granted directly to `eduduty_rls_owner` (`USING (true)`). Because `eduduty_rls_owner` has `NOLOGIN`, no client can log in directly under this role; the policy only applies within the security definer function context.
- **Zero-Downtime Multi-Key Rotation:** `auth_internal.verify_identity_context()` was upgraded to loop across all `active = true` signing keys in descending order of `key_id`. This allows seamless phased key rotation with zero request drops.
- **Strict Authority Separation:** Production signing authority is completely isolated in the FastAPI application layer (`mint_signed_identity_context`). `ai_reader` has no privileges to inspect signing keys or execute the verifier function directly.

---

## 2. Live PostgreSQL Catalog Evidence

### 2.1 Role Configuration and Attributes

```sql
SELECT rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolcanlogin, rolbypassrls 
FROM pg_roles 
WHERE rolname IN ('eduduty_rls_owner', 'ai_reader');
```

**Actual Catalog Output:**
```
      rolname      | rolsuper | rolinherit | rolcreaterole | rolcreatedb | rolcanlogin | rolbypassrls 
-------------------+----------+------------+---------------+-------------+-------------+--------------
 eduduty_rls_owner | f        | t          | f             | f           | f           | f
 ai_reader         | f        | f          | f             | f           | t           | f
(2 rows)
```
- `eduduty_rls_owner` cannot log in (`rolcanlogin = false`), is not a superuser (`rolsuper = false`), cannot bypass RLS (`rolbypassrls = false`), and cannot create databases or roles.
- `ai_reader` can log in, but is strictly unprivileged (`rolsuper = false`, `rolbypassrls = false`).

### 2.2 Function Ownership, Security Definer, and `search_path`

```sql
SELECT proname, nspname, proowner::regrole, prosecdef, proconfig,
       has_function_privilege('public', p.oid, 'EXECUTE') as public_exec,
       has_function_privilege('ai_reader', p.oid, 'EXECUTE') as ai_reader_exec
FROM pg_proc p 
JOIN pg_namespace n ON n.oid = p.pronamespace 
WHERE proname IN (
    'verify_identity_context', 
    'can_current_user_access_class', 
    'can_current_user_access_student', 
    'can_current_user_access_duty_roster'
);
```

**Actual Catalog Output:**
```
               proname               |    nspname    |     proowner      | prosecdef |             proconfig              | public_exec | ai_reader_exec 
-------------------------------------+---------------+-------------------+-----------+------------------------------------+-------------+----------------
 can_current_user_access_duty_roster | public        | eduduty_rls_owner | t         | {"search_path=pg_catalog, public"} | f           | t
 verify_identity_context             | auth_internal | eduduty_rls_owner | t         | {"search_path=pg_catalog, public"} | f           | f
 can_current_user_access_class       | public        | eduduty_rls_owner | t         | {"search_path=pg_catalog, public"} | f           | t
 can_current_user_access_student     | public        | eduduty_rls_owner | t         | {"search_path=pg_catalog, public"} | f           | t
(4 rows)
```

- **Owner:** All 4 functions are owned by `eduduty_rls_owner` (not `postgres`).
- **Definer Mode:** `prosecdef = true` on all 4 functions.
- **Pinned Search Path:** `search_path=pg_catalog, public` prevents search-path hijacking attacks.
- **Public Execution:** `public_exec = false` on all 4 functions (revoked from `PUBLIC`).
- **AI Reader Execution:** Granted only on the 3 policy evaluators (`ai_reader_exec = true`); `verify_identity_context` is `false` for `ai_reader` (cannot be executed directly by `ai_reader`).

### 2.3 Table Ownership and Least Privilege Grants for `eduduty_rls_owner`

```sql
-- Table Ownership:
SELECT relname, relowner::regrole FROM pg_class WHERE relowner = 'eduduty_rls_owner'::regrole;
```
**Output:** `(0 rows)` — `eduduty_rls_owner` owns zero relations/tables.

```sql
-- Role Table Grants:
SELECT table_schema, table_name, privilege_type 
FROM information_schema.role_table_grants 
WHERE grantee = 'eduduty_rls_owner' 
ORDER BY table_name, privilege_type;
```

**Actual Catalog Output:**
```
 table_schema  |     table_name      | privilege_type 
---------------+---------------------+----------------
 public        | classes             | SELECT
 auth_internal | context_signing_key | SELECT
 public        | faculty_timetable   | SELECT
 public        | students            | SELECT
 public        | timetable_versions  | SELECT
(5 rows)
```

- **Zero Write Grants:** No `INSERT`, `UPDATE`, `DELETE`, `TRUNCATE`, `REFERENCES`, or `TRIGGER` privileges.
- **Schema Privileges:** `USAGE` only on `auth_internal` and `public`; `CREATE` is `false`.

### 2.4 Definer Owner RLS Policies

```sql
SELECT tablename, policyname, roles, cmd, qual 
FROM pg_policies 
WHERE policyname LIKE '%definer%';
```

**Actual Catalog Output:**
```
 tablename |         policyname         |        roles        |  cmd   | qual 
-----------+----------------------------+---------------------+--------+------
 students  | rls_students_definer_owner | {eduduty_rls_owner} | SELECT | true
 classes   | rls_classes_definer_owner  | {eduduty_rls_owner} | SELECT | true
(2 rows)
```

Because `eduduty_rls_owner` possesses `NOBYPASSRLS`, when `can_current_user_access_student()` queries `public.students` or `public.classes`, RLS is active. Without these explicit policies, PostgreSQL would evaluate policies recursively or deny access. These non-recursive policies guarantee deterministic policy evaluation while keeping the role unprivileged.

---

## 3. Signing Authority Separation and Boundary Verification

### 3.1 Architectural Separation

```
[FastAPI Application Server]
  │  1. Authenticates JWT from user session
  │  2. Resolves linked faculty_id & active timetable
  │  3. Reads SECRET_KEY from application environment
  │  4. Computes HMAC-SHA256 signature
  │  5. Sets 6 transaction-local GUCs on ai_reader connection:
  │       SET LOCAL app.current_user_id = '...'
  │       SET LOCAL app.current_faculty_id = '...'
  │       SET LOCAL app.current_user_role = '...'
  │       SET LOCAL app.current_context_issued_at = '...'
  │       SET LOCAL app.current_context_nonce = '...'
  │       SET LOCAL app.current_context_signature = '...'
  ▼
[PostgreSQL Database Engine]
  │  `ai_reader` connection executes reporting queries
  │  RLS policies invoke `can_current_user_access_student()`
  │  Helper runs as `SECURITY DEFINER` (owner: `eduduty_rls_owner`)
  │  Calls `auth_internal.verify_identity_context()`
  │  Verifier iterates `active = true` keys and verifies HMAC
  │  Checks timestamp drift window (-120s to +30s)
  ▼
  [Row-Level Security Filter Applied to Base Tables & Views]
```

### 3.2 Negative Privilege & Attack Verifications

| Test Case | Attack Vector / Negative Condition | Result | Catalog / SQL Exception |
|---|---|---|---|
| **Direct Key Exfiltration** | `ai_reader` queries `SELECT * FROM auth_internal.context_signing_key` | **BLOCKED** | `ERROR: permission denied for schema auth_internal` |
| **Direct Verifier Invocation** | `ai_reader` queries `SELECT * FROM auth_internal.verify_identity_context()` | **BLOCKED** | `ERROR: permission denied for function verify_identity_context` |
| **Identity Field Tampering** | Attacker intercepts valid context and modifies `app.current_faculty_id` | **FAIL-CLOSED** | Verifier returns `(NULL, NULL, NULL, false)` -> 0 rows returned |
| **Role Elevation Tampering** | Attacker modifies `app.current_user_role` to `'super_admin'` | **FAIL-CLOSED** | Signature mismatch -> 0 rows returned |
| **Expired Context Replay** | Context timestamp `now - 121 seconds` | **FAIL-CLOSED** | Timestamp validation rejects context -> 0 rows returned |
| **Future Clock Drift** | Context timestamp `now + 31 seconds` | **FAIL-CLOSED** | Timestamp validation rejects context -> 0 rows returned |
| **Malformed Nonce / TS** | Non-numeric timestamp or empty nonce string | **FAIL-CLOSED** | Exception block in verifier catches cast failure -> 0 rows returned |

### 3.3 Secret Hygiene
- Application signing secret is retrieved exclusively from environment configuration.
- Database signing key is loaded into `auth_internal.context_signing_key` with permissions restricted to `eduduty_rls_owner` and `postgres`.
- Secret keys are never logged, never embedded in exception payloads, and never surfaced in AI reporting view outputs or FastAPI API responses.

---

## 4. Replay Threat Model and Multi-Key Rotation

### 4.1 Replay Threat Model Bounds

1. **Transaction-Local Lifetime (`is_local = true`):**
   - The application issues `SELECT set_config('app.current_faculty_id', '...', true)` where `is_local = true`.
   - These parameters exist **only** for the duration of the current PostgreSQL transaction.
   - Upon `COMMIT` or `ROLLBACK`, the settings are completely discarded by PostgreSQL. Connection pooling contamination is mathematically impossible.
2. **Acceptance Window (-120s to +30s):**
   - A valid signed context remains mathematically verifiable for up to 120 seconds after issuance.
   - Within this 120-second window, if an adversary were able to intercept the database connection stream (e.g. lack of TLS), they could replay the `set_config` parameters on another query *within that 120-second window*.
3. **Evaluation of Nonce Deduplication:**
   - EduDuty's AI reporting subsystem connects to PostgreSQL as `ai_reader` in a `READ ONLY` transaction (`SET TRANSACTION READ ONLY`).
   - Any table-based nonce insertion (`INSERT INTO auth_internal.consumed_nonces VALUES (...)`) fails with:
     ```
     ERROR: cannot execute INSERT in a read-only transaction
     ```
   - Introducing write-capable nonce tracking on read replicas would eliminate read-only replica scaling and create high-concurrency table bloat and locking contention.
   - **Conclusion:** Bounding context validity to 120s combined with TLS connection encryption provides a robust, production-grade security boundary for read-only reporting workloads.

### 4.2 Multi-Key Rotation Implementation

To enable seamless, zero-downtime key rotation:
1. `auth_internal.context_signing_key` supports multiple active keys:
   ```sql
   FOR key_rec IN (
       SELECT secret_key 
       FROM auth_internal.context_signing_key 
       WHERE active = true 
       ORDER BY key_id DESC
   ) LOOP
       expected_sig := encode(hmac(canonical_payload::bytea, key_rec.secret_key::bytea, 'sha256'), 'hex');
       IF LOWER(raw_sig) = LOWER(expected_sig) THEN
           sig_valid := true;
           EXIT;
       END IF;
   END LOOP;
   ```
2. **Rotation Lifecycle:**
   - **Step 1:** Insert new key into `context_signing_key` (`active = true`, `key_id = 2`). Database now accepts signatures from both Key 1 and Key 2.
   - **Step 2:** Deploy application pods with `CONTEXT_SIGNING_KEY=key_2`. New requests are minted with Key 2; in-flight requests minted with Key 1 continue to succeed.
   - **Step 3:** After all pods are running Key 2 and the 120s acceptance window passes, mark Key 1 as inactive (`active = false`). Key 1 is retired with zero failed queries.

---

## 5. Access Contract Verification

| Contract Invariant | Implementation Mechanism | Status |
|---|---|---|
| **Active Versioned Timetables Only** | `can_current_user_access_class()` joins `faculty_timetable` with `timetable_versions` requiring `tv.status = 'active'` | **VERIFIED** |
| **Inactive / Draft Timetable Exclusion** | Inactive versions or unversioned assignments return `false` | **VERIFIED** |
| **No Historical Attendance Access** | Historical attendance records for non-assigned faculty yield 0 student rows | **VERIFIED** |
| **Duty Roster Isolation** | Faculty can view the institution-wide duty roster (`ai_duty_roster`), but cannot view student details outside their assigned classes | **VERIFIED** |
| **Connection Pool Hygiene** | Connection reset after queries clears all GUCs; adjacent pooled queries fail closed without context | **VERIFIED** |

---

## 6. Test Suites and Execution Results

### 6.1 PostgreSQL Integration Test Suite (`EDUDUTY_REQUIRE_POSTGRES_TESTS=1`)

**Command:**
```powershell
python -c "import subprocess, os, sys, pytest; p = subprocess.run(['docker', 'exec', 'eduduty_pg_b4_test', 'printenv', 'POSTGRES_PASSWORD'], capture_output=True, text=True).stdout.strip(); os.environ['PG_TEST_PASSWORD']=p; os.environ['EDUDUTY_REQUIRE_POSTGRES_TESTS']='1'; files = ['backend/tests/test_postgres_rls_b42b4_ownership.py', 'backend/tests/test_postgres_rls_b42b2_remediation.py', 'backend/tests/test_postgres_rls_b42b.py', 'backend/tests/test_alembic_b42a_ai_reader.py', 'backend/tests/test_postgres_connection_b412.py', 'backend/tests/test_postgres_gating.py']; sys.exit(pytest.main(files + ['-v', '--tb=short']))"
```

**Results:**
- `backend/tests/test_postgres_rls_b42b4_ownership.py`: **13 passed**
  - `test_01_rls_owner_role_attributes_least_privilege` PASSED
  - `test_02_helper_functions_owned_by_rls_owner` PASSED
  - `test_03_rls_owner_has_no_write_or_ddl_privileges` PASSED
  - `test_04_legitimate_application_issued_context_succeeds` PASSED
  - `test_05_ai_reader_cannot_read_keys_or_execute_verifier` PASSED
  - `test_06_tampered_application_context_fails_closed` PASSED
  - `test_07_expired_application_context_fails_closed` PASSED
  - `test_08_multi_key_rotation_zero_downtime` PASSED
  - `test_09_active_timetable_scope_and_inactive_rejection` PASSED
  - `test_10_historical_attendance_does_not_confer_access` PASSED
  - `test_11_duty_roster_isolation` PASSED
  - `test_12_pooled_connection_isolation` PASSED
  - `test_13_migration_009_upgrade_downgrade_reupgrade` PASSED
- `backend/tests/test_postgres_rls_b42b2_remediation.py`: **18 passed**
- `backend/tests/test_postgres_rls_b42b.py`: **18 passed**
- `backend/tests/test_alembic_b42a_ai_reader.py`: **11 passed**
- `backend/tests/test_postgres_connection_b412.py`: **12 passed**
- `backend/tests/test_postgres_gating.py`: **9 passed**

**Total PostgreSQL Integration:** **81 passed, 0 failed, 0 skipped in 10.81s**

### 6.2 SQLite Regression Test Suite

**Command:**
```powershell
python -m pytest tests/test_auth.py tests/test_rbac.py tests/test_upload_attendance.py tests/test_alembic_b33_auth.py tests/test_alembic_b2_constraints.py tests/test_alembic_b31_review.py tests/test_alembic_b32_gate.py tests/test_alembic_b3_ai_views.py tests/test_alembic_migration.py tests/test_resource_authorization.py tests/test_ai_read_isolation.py -v --tb=short
```

**Results:**
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

**Total SQLite Regression:** **85 passed, 0 failed, 0 skipped in 33.91s**

---

## 7. Migration Reversibility

Migration `009_harden_rls_ownership` was tested through a complete upgrade-downgrade-reupgrade cycle:
- `alembic downgrade 008_trusted_identity_context`:
  - Successfully transferred function ownership back to `postgres`.
  - Replaced multi-key verifier with single-key version.
  - Dropped definer policies on `students` and `classes`.
  - Revoked schema and table privileges and dropped `eduduty_rls_owner`.
- `alembic upgrade head`:
  - Re-created `eduduty_rls_owner`, re-granted minimum privileges, restored definer policies, and re-transferred function ownership.

---

## 8. Asset Preservation & Compliance

- **`backend/eduduty.db`:** Intact and preserved (180,224 bytes).
- **SecureMailScope Infrastructure:** Docker containers (`mailnet_postfix`, `mailnet_dovecot`, `mailnet_generator`), networks, and volumes preserved without modification.
- **Git State:** Clean working branch; no commits or pushes executed.
- **Secret Protection:** No HMAC secrets, passwords, or raw tokens committed or logged.

---

## 9. Final Verdict

**VERDICT: PASS**

All concerns from Stage B4.2B.3 have been resolved. The PostgreSQL Row-Level Security architecture satisfies strict least privilege, enforces application signing boundary integrity, provides zero-downtime key rotation, and guarantees fail-closed isolation across all faculty and class contexts.
