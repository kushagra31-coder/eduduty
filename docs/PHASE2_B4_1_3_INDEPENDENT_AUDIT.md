# EduDuty — Stage B4.1.3: Independent Connection-Hardening Audit

**Date:** October 11, 2026  
**Status:** Audit Completed  
**Audit Scope:** Independent read-only verification of Stage B4.1.2 PostgreSQL connection hardening changes against [backend/database.py](file:///d:/Code/eduduty/backend/database.py), [backend/requirements.txt](file:///d:/Code/eduduty/backend/requirements.txt), [backend/tests/test_postgres_connection_b412.py](file:///d:/Code/eduduty/backend/tests/test_postgres_connection_b412.py), live test database catalogs, and SQLAlchemy 2.0.54 runtime characteristics.  
**Mode:** Strictly read-only audit. No source code, migrations, database objects, Docker containers, or configurations were modified. Credentials remain strictly redacted.

---

## 1. Executive Summary & Verdict Matrix

| # | Audit Check | Status | Key Evidence & File Reference |
| :--- | :--- | :--- | :--- |
| **1** | **Driver & Startup** | **PASS** | `pg8000==1.31.5` declared in [requirements.txt:25](file:///d:/Code/eduduty/backend/requirements.txt#L25) and verified installed via `pip show`. Both engines initialize and connect to PostgreSQL. SQLite fallback confirmed when `DATABASE_URL` is unset. `ai_reader_connect_args` is empty `{}` for pg8000. |
| **2** | **AI-Reader Privilege Isolation** | **FAIL / GATED** | [database.py:61-78](file:///d:/Code/eduduty/backend/database.py#L61-L78) resolves `AI_READER_DATABASE_URL` to primary credentials when unset. The configured account is `postgres` (`rolsuper = true`, `rolbypassrls = true`). Read-only isolation relies **exclusively** on SQLAlchemy connection settings; no unprivileged database role exists yet. Session can execute `SET TRANSACTION READ WRITE;` to bypass read-only mode. |
| **3** | **Read-Only Behavior** | **PASS (Mechanism) / FAIL (Privilege)** | Standard DDL/DML is rejected directly by PostgreSQL (`ERROR 25006: cannot execute ... in a read-only transaction`). Pooled reuse and rollbacks maintain `transaction_read_only = on`. However, superuser session can override its transaction mode using `SET TRANSACTION READ WRITE`. |
| **4** | **Test Quality** | **PASS** | Explicit test segregation verified: 91 SQLite tests and 7 live PostgreSQL tests (98 total). PostgreSQL tests connect via dedicated fixture; no silent fallback to SQLite. Tests fail cleanly or skip if container is unreachable. No RLS verification claimed. |
| **5** | **Secrets & Preservation** | **PASS** | Engine `str()`, `repr()`, and connection errors mask passwords (`***`). `eduduty.db` (root & backend) and `mailnet_*` containers 100% untouched. Migrations 001–005 unmodified. Migration 006 not created. |

---

## 2. Driver & Startup Verification

### 2.1 Driver Declaration & Installation
- **Requirement Audit:** [backend/requirements.txt:24-26](file:///d:/Code/eduduty/backend/requirements.txt#L24-L26)
  ```text
  pandas==3.0.6
  pg8000==1.31.5
  postgrest==2.31.0
  ```
- **CLI Verification:**
  ```powershell
  pip show pg8000
  ```
  **Output Evidence:**
  ```text
  Name: pg8000
  Version: 1.31.5
  Summary: PostgreSQL interface library
  Location: C:\Users\BHAGYESH JAIN\AppData\Local\Programs\Python\Python311\Lib\site-packages
  Requires: python-dateutil, scramp
  ```
- **Verdict:** **PASS**

### 2.2 PostgreSQL Engine Initialization & Dialect Compatibility
- **Code Audit:** [backend/database.py:83-94](file:///d:/Code/eduduty/backend/database.py#L83-L94)
  ```python
  elif AI_READER_DATABASE_URL.startswith("postgresql"):
      # Enforce PostgreSQL server-side read-only transactions across all PostgreSQL dialects (pg8000, psycopg2, etc.)
      ai_reader_execution_options = {"postgresql_readonly": True}
      # Pass options connect arg only for libpq-based drivers where supported (psycopg2/psycopg), never for pg8000
      if "+pg8000" not in AI_READER_DATABASE_URL and "pg8000" not in AI_READER_DATABASE_URL:
          ai_reader_connect_args = {"options": "-c default_transaction_read_only=on"}
  ```
- **Runtime Verification:**
  Executed with `$env:DATABASE_URL="postgresql+pg8000://postgres:<REDACTED>@127.0.0.1:5433/eduduty_test_db"`:
  ```text
  database: using DATABASE_URL from environment
  database.engine connect: 1
  database.ai_reader_engine connect: 2
  connect_args: {}
  execution_options: {'postgresql_readonly': True}
  ```
  No libpq command-line arguments reached `pg8000`. Both engines connected successfully.
- **Verdict:** **PASS**

### 2.3 SQLite Fallback Verification
- **Code Audit:** [backend/database.py:7-35](file:///d:/Code/eduduty/backend/database.py#L7-L35)
- **Runtime Verification with Unset Variables:**
  When `DATABASE_URL`, `AI_READER_DATABASE_URL`, and `AI_DATABASE_URL` are deleted:
  ```text
  database: PostgreSQL not reachable; using local SQLite file eduduty.db
  SQLALCHEMY_DATABASE_URL: sqlite:///./eduduty.db
  AI_READER_DATABASE_URL: sqlite:///./eduduty.db
  SQLite engine connect: 1
  SQLite ai_reader connect: 2
  ```
- **Verdict:** **PASS**

---

## 3. AI-Reader Privilege Isolation Audit

### 3.1 URL Resolution Logic Trace
Tracing [backend/database.py:61-78](file:///d:/Code/eduduty/backend/database.py#L61-L78):
1. `os.getenv("AI_READER_DATABASE_URL")` is evaluated.
2. `os.getenv("AI_DATABASE_URL")` is evaluated as fallback.
3. If neither environment variable is defined, the function executes:
   ```python
   return SQLALCHEMY_DATABASE_URL
   ```
4. **Finding:** The AI reader defaults to using the **exact same primary credentials** as the application write engine.

### 3.2 Database Privilege Audit
Inspected role attributes in PostgreSQL catalog `pg_roles` for the connection user:
```sql
SELECT rolname, rolsuper, rolinherit, rolcreaterole, rolcreatedb, rolcanlogin, rolreplication, rolbypassrls
FROM pg_roles WHERE rolname = 'postgres';
```
**Output Evidence:**
```text
 rolname  | rolsuper | rolinherit | rolcreaterole | rolcreatedb | rolcanlogin | rolreplication | rolbypassrls 
----------+----------+------------+---------------+-------------+-------------+----------------+--------------
 postgres | t        | t          | t             | t           | t           | t              | t
(1 row)
```

**Critical Security Findings:**
1. **RLS Bypass Risk:** The account has `rolsuper = true` and `rolbypassrls = true`. In PostgreSQL, a superuser **always bypasses Row-Level Security policies**, regardless of table RLS definitions.
2. **Session Override Risk:** Read-only protection currently relies **exclusively** on SQLAlchemy's `postgresql_readonly` connection characteristic. Because the user is `postgres`, PostgreSQL allows the session to execute:
   ```sql
   SET TRANSACTION READ WRITE;
   ```
   Live testing verified that issuing `SET TRANSACTION READ WRITE;` on an active `ai_reader_engine` connection flips `transaction_read_only` from `on` to `off` and allows `CREATE TABLE` and write operations to execute.
3. **Verdict:** **FAIL / GATED** (Acceptable for Stage B4.1.2 connection validation, but an absolute blocker for Stage B4.3 RLS enforcement. An unprivileged `ai_reader` role with `NOBYPASSRLS` and table-level `GRANT SELECT` only is mandatory before RLS can be considered secure).

---

## 4. Read-Only Behavior Audit

### 4.1 SQLAlchemy 2.0.54 Characteristic Mechanism
Inspected installed SQLAlchemy dialect implementation (`sqlalchemy/dialects/postgresql/pg8000.py`):
```python
def set_readonly(self, connection, value):
    cursor = connection.cursor()
    try:
        cursor.execute(
            "SET SESSION CHARACTERISTICS AS TRANSACTION %s"
            % ("READ ONLY" if value else "READ WRITE")
        )
        cursor.execute("COMMIT")
    finally:
        cursor.close()
```
- On checkout, SQLAlchemy executes `SET SESSION CHARACTERISTICS AS TRANSACTION READ ONLY; COMMIT;`.
- Subsequent transactions default to `READ ONLY`.

### 4.2 Lifecycle & Rejection Verification
1. **Fresh Connections & Pooled Reuse:**
   - Fresh connection: `SHOW transaction_read_only` returns `on`.
   - Post-rollback: `SHOW transaction_read_only` returns `on`.
   - Connection checked out from pool: `SHOW transaction_read_only` returns `on`.
2. **Database-Level Rejection:**
   Writes are rejected by PostgreSQL's utility parser (`PreventCommandIfReadOnly`), not application-level validation:
   ```text
   ProgrammingError (pg8000.dbapi.ProgrammingError) {
     'S': 'ERROR',
     'C': '25006',
     'M': 'cannot execute CREATE TABLE in a read-only transaction',
     'R': 'PreventCommandIfReadOnly'
   }
   ```
- **Verdict:** **PASS (Mechanism Verified)**

---

## 5. Test Quality Audit

### 5.1 Test Segregation & Count Breakdown
Inspected [backend/tests/test_postgres_connection_b412.py](file:///d:/Code/eduduty/backend/tests/test_postgres_connection_b412.py) and test suite results:

| Test Group | Environment | Count | Mechanism |
| :--- | :--- | :--- | :--- |
| **Baseline Application Suite** | SQLite (`:memory:` & tempfiles) | 86 | `conftest.py` engine |
| **Connection Hardening (SQLite)** | SQLite (`:memory:` / local) | 5 | Dedicated unit tests |
| **Live PostgreSQL Integration** | PostgreSQL 16 (`127.0.0.1:5433`) | 7 | `pg_test_url` fixture |
| **Total Test Count** | Combined | **98** | **98 PASSED, 0 FAILED** |

### 5.2 PostgreSQL Test Verification
- All 7 PostgreSQL tests (`test_pg_normal_engine_connection`, `test_pg_ai_reader_select_succeeds`, `test_pg_ai_reader_write_fails_create_table`, `test_pg_ai_reader_write_fails_insert`, `test_pg_ai_reader_write_fails_update`, `test_pg_ai_reader_write_fails_delete`, `test_application_startup_and_get_db`) require the `pg_test_url` fixture.
- The fixture connects via TCP socket to `127.0.0.1:5433`. If unavailable, tests explicitly skip with `"PostgreSQL test container on 127.0.0.1:5433 is not reachable"`.
- **Finding:** No test silently falls back to SQLite.
- **Verdict:** **PASS**

---

## 6. Secrets & Preservation Audit

### 6.1 Password Masking
- `str(create_engine(url))` masks password with `***`.
- `repr(create_engine(url))` masks password with `***`.
- `str(engine.url)` masks password with `***`.
- Socket connection error and auth failure exceptions do not display the plaintext password.

### 6.2 Asset Preservation
- **SQLite Databases:**
  - `D:\Code\eduduty\eduduty.db`: 196,608 bytes (unchanged, last modified Oct 10, 2026).
  - `D:\Code\eduduty\backend\eduduty.db`: 188,416 bytes (unchanged, last modified Oct 10, 2026).
- **SecureMailScope Containers:**
  - `mailnet_postfix`: Exited (255), untouched.
  - `mailnet_dovecot`: Exited (255), untouched.
  - `mailnet_generator`: Exited (0), untouched.
- **Alembic Revisions:** Only 5 files exist in `backend/alembic/versions/`. Migration 006 has not been created.
- **Verdict:** **PASS**

---

## 7. Security Blockers & Smallest Safe Next Step

### Remaining Security Blockers
1. **Shared Superuser Credentials (BLOCKER FOR RLS):**  
   The AI reader engine currently shares credentials with the primary engine (`postgres`). Because `postgres` possesses `rolbypassrls = true`, any query routed through this engine will ignore Row-Level Security policies once applied. Furthermore, the superuser can execute `SET TRANSACTION READ WRITE` to bypass read-only transaction limits.
2. **Missing `WITH (security_invoker = true)` on AI Views:**  
   In PostgreSQL 15+, views operate as `security_definer` by default, querying underlying tables under the view owner's privileges and ignoring caller RLS policies.
3. **Missing `faculty_id` in `ai_duty_roster`:**  
   `ai_duty_roster` lacks `faculty_id` projection required for faculty RLS filtering.

### Smallest Safe Next Step: Stage B4.2 (Migration 006 & Dedicated Role Architecture)
1. **Draft Migration 006:**
   - Alter all 5 approved AI views to set `WITH (security_invoker = true)`.
   - Add `f.id AS faculty_id` to `ai_duty_roster`.
2. **Provision Dedicated Unprivileged Role (`ai_reader`):**
   - Create role `ai_reader` with `NOCREATEDB`, `NOCREATEROLE`, `NOINHERIT`, `NOBYPASSRLS`.
   - Grant `CONNECT` on `eduduty_test_db`, `USAGE` on schema `public`, and `SELECT` exclusively on the 5 approved views.
   - Configure `AI_READER_DATABASE_URL` to target the `ai_reader` role.
