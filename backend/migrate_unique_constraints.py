"""
Migration script: deduplicate MstEligibility and MstAttempt rows, then enforce
UniqueConstraint(student_id, mst_exam_id) across both SQLite and PostgreSQL.
"""

import sys
import logging
from sqlalchemy import text
from database import engine

logger = logging.getLogger(__name__)


def run_unique_constraint_migration(db_engine=None):
    if db_engine is None:
        db_engine = engine

    dialect = db_engine.dialect.name
    results = {
        "eligibility_duplicates": [],
        "attempt_duplicates": [],
        "eligibility_removed_count": 0,
        "attempt_removed_count": 0,
        "constraints_applied": False,
    }

    with db_engine.begin() as conn:
        # 1. Deduplicate mst_eligibility
        elig_dups_query = text("""
            SELECT student_id, mst_exam_id, COUNT(*) as cnt
            FROM mst_eligibility
            GROUP BY student_id, mst_exam_id
            HAVING COUNT(*) > 1
        """)
        dups = conn.execute(elig_dups_query).fetchall()
        for d in dups:
            results["eligibility_duplicates"].append({
                "student_id": d[0],
                "mst_exam_id": d[1],
                "count": d[2],
            })

        if results["eligibility_duplicates"]:
            # Delete older duplicates, preserving the latest (highest id)
            del_elig = text("""
                DELETE FROM mst_eligibility
                WHERE id NOT IN (
                    SELECT MAX(id)
                    FROM mst_eligibility
                    GROUP BY student_id, mst_exam_id
                )
            """)
            res = conn.execute(del_elig)
            results["eligibility_removed_count"] = res.rowcount or len(results["eligibility_duplicates"])
            logger.info("Removed %d duplicate mst_eligibility rows", results["eligibility_removed_count"])

        # 2. Deduplicate mst_attempts
        att_dups_query = text("""
            SELECT student_id, mst_exam_id, COUNT(*) as cnt
            FROM mst_attempts
            GROUP BY student_id, mst_exam_id
            HAVING COUNT(*) > 1
        """)
        att_dups = conn.execute(att_dups_query).fetchall()
        for d in att_dups:
            results["attempt_duplicates"].append({
                "student_id": d[0],
                "mst_exam_id": d[1],
                "count": d[2],
            })

        if results["attempt_duplicates"]:
            del_att = text("""
                DELETE FROM mst_attempts
                WHERE id NOT IN (
                    SELECT MAX(id)
                    FROM mst_attempts
                    GROUP BY student_id, mst_exam_id
                )
            """)
            res = conn.execute(del_att)
            results["attempt_removed_count"] = res.rowcount or len(results["attempt_duplicates"])
            logger.info("Removed %d duplicate mst_attempts rows", results["attempt_removed_count"])

        # 3. Add Unique Index / Constraint
        if dialect == "sqlite":
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_mst_eligibility_student_exam ON mst_eligibility(student_id, mst_exam_id)"
            ))
            conn.execute(text(
                "CREATE UNIQUE INDEX IF NOT EXISTS uq_mst_attempt_student_exam ON mst_attempts(student_id, mst_exam_id)"
            ))
        else:
            # Postgres: check if constraint already exists before adding
            conn.execute(text("""
                DO $$
                BEGIN
                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'uq_mst_eligibility_student_exam'
                    ) THEN
                        ALTER TABLE mst_eligibility
                        ADD CONSTRAINT uq_mst_eligibility_student_exam UNIQUE (student_id, mst_exam_id);
                    END IF;

                    IF NOT EXISTS (
                        SELECT 1 FROM pg_constraint WHERE conname = 'uq_mst_attempt_student_exam'
                    ) THEN
                        ALTER TABLE mst_attempts
                        ADD CONSTRAINT uq_mst_attempt_student_exam UNIQUE (student_id, mst_exam_id);
                    END IF;
                END $$;
            """))

        results["constraints_applied"] = True

    return results


if __name__ == "__main__":
    report = run_unique_constraint_migration()
    print("Migration Report:", report)
