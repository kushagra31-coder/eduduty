# EduDuty — Phase 2, Stage A: Database Migration Strategy & Design

**Date:** October 10, 2026  
**Status:** Audit & Design Complete  
**Scope:** Alembic Migration Architecture, Deployment Strategy, and Staged Implementation Roadmap  
**Phase State:** Stage A Audit Only (No migrations executed yet)

---

## 1. Alembic Tooling & Architecture Strategy

### 1.1 Current Initialization vs Production Requirement
- **Current Runtime Behavior:** `backend/main.py` uses `models.Base.metadata.create_all(bind=engine)` during application startup.
- **Evaluation:**
  - `create_all()` is appropriate for in-memory SQLite pytest environments (`conftest.py`) and initial zero-setup development.
  - In production and populated staging environments, `create_all()` is **incapable** of applying column modifications, index additions, schema migrations, or constraint updates.
  - Alembic version control must be introduced inside `backend/alembic/` to manage all production schema evolution.

### 1.2 Database Driver Standardization (`database.py`)
- **Connector Analysis:** `requirements.txt` specifies `psycopg2-binary==2.9.13`. `backend/database.py` attempts `import psycopg` (psycopg v3).
- **Strategy:** Update `_resolve_database_url` and `_resolve_ai_reader_database_url` in `database.py` to support `psycopg2` (e.g. `postgresql+psycopg2://...`) as well as `psycopg` (v3), enabling seamless PostgreSQL connection detection.

---

## 2. Staged Migration Implementation Roadmap

To avoid breaking working application features or risking data loss, Phase 2 migration implementation will be executed in four small, reversible stages:

```text
Phase 2 Stage A ──► Schema Reconciliation & Migration Design (COMPLETED - AUDIT ONLY)
Phase 2 Stage B1 ─► Alembic Framework Setup & Baseline Initial Revision
Phase 2 Stage B2 ─► Hardened ORM Constraints (Unique MstEligibility & MstAttempt)
Phase 2 Stage B3 ─► PostgreSQL AI Read Views DDL Sync Migration
Phase 2 Stage B4 ─► PostgreSQL Environment Verification & Production Documentation
```

---

### Stage B1: Alembic Framework Initialization & Baseline Migration
- **Target:** Initialize `backend/alembic/` and create baseline revision `001_baseline_schema.py`.
- **Scope:**
  - Generate baseline migration representing all existing 18 tables defined in `models.py`.
  - Configure `backend/alembic/env.py` to import `models.Base.metadata` for autogenerate capability.
  - Retain `create_all()` for SQLite test suite execution.

### Stage B2: Schema Constraint Hardening Migration
- **Target:** Add explicit `UniqueConstraint('student_id', 'mst_exam_id')` to `MstEligibility` and `MstAttempt` in `models.py` and Alembic revision `002_add_unique_constraints.py`.
- **Scope:**
  - Prevents duplicate eligibility or attempt records during concurrent requests or re-imports.
  - Generates migration script supporting both PostgreSQL and SQLite (using Alembic batch mode for SQLite table alterations).

### Stage B3: PostgreSQL AI Views Migration
- **Target:** Create Alembic revision `003_create_ai_views.py`.
- **Scope:**
  - Implements DDL statements to create/update all 5 AI read views in PostgreSQL:
    1. `ai_eligibility_summary`
    2. `ai_attendance_summary`
    3. `ai_vt_candidates`
    4. `ai_duty_roster`
    5. `v_vt_follow_up_status`
  - Grants `SELECT` permissions on these views to the `ai_reader` role.

### Stage B4: Multi-Database Verification & Documentation
- **Target:** Validate migration execution across both local SQLite and PostgreSQL environments.
- **Scope:**
  - Run full pytest test suite (38+ tests) to ensure zero regression.
  - Document production backup (`pg_dump`), drift check (`alembic check`), and rollback (`alembic downgrade`) procedures.

---

## 3. Operational Safeguards & Rollback Strategy

1. **Database Backup & Recovery:**
   - Prior to executing `alembic upgrade head` in staging or production, administrators must take a full logical backup:
     ```bash
     pg_dump -U postgres -F c -b -v -f eduduty_pre_migration.backup eduduty
     ```
2. **Schema Drift Detection:**
   - CI/CD pipelines will execute `alembic check` to detect any discrepancy between `models.py` and the database migration state.
3. **Reversible Downgrade Scripts:**
   - Every Alembic revision file must define a fully functional `downgrade()` function to support immediate rollback:
     ```bash
     alembic downgrade -1
     ```
4. **Zero Data Loss Guarantee:**
   - No migration script will drop columns or recreate populated tables without a staging and data copy strategy.
