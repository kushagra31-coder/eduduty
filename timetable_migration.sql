-- Migration: extend faculty_timetable for real Acropolis-format timetables
-- Run this against the existing EduDuty DB (SQLite or Postgres).

ALTER TABLE faculty_timetable ADD COLUMN subject_code VARCHAR(20);
ALTER TABLE faculty_timetable ADD COLUMN subject_name VARCHAR(100);
ALTER TABLE faculty_timetable ADD COLUMN room VARCHAR(20);
ALTER TABLE faculty_timetable ADD COLUMN batch VARCHAR(10);      -- e.g. 'B1', 'B2', or NULL for whole class
ALTER TABLE faculty_timetable ADD COLUMN period_start VARCHAR(10); -- '10:30'
ALTER TABLE faculty_timetable ADD COLUMN period_end VARCHAR(10);   -- '11:20'
ALTER TABLE faculty_timetable ADD COLUMN semester VARCHAR(20);     -- 'III', 'V' etc — for reference/versioning

-- Faculty abbreviations, straight from the timetable legend tables (e.g. VK, AR, RK)
ALTER TABLE faculty ADD COLUMN abbreviation VARCHAR(10);

-- One row per class per timetable revision, so old timetables aren't lost
-- when a new term's sheet is entered.
CREATE TABLE IF NOT EXISTS timetable_versions (
    id          SERIAL PRIMARY KEY,
    class_id    INT NOT NULL REFERENCES classes(id),
    semester    VARCHAR(20) NOT NULL,      -- 'III', 'V'
    session     VARCHAR(30) NOT NULL,      -- 'Jul-Dec 2026'
    doc_no      VARCHAR(30),               -- 'AITR/Acad/09' — from the sheet, for traceability
    active      BOOLEAN NOT NULL DEFAULT TRUE,
    created_at  TIMESTAMP NOT NULL DEFAULT now()
);

ALTER TABLE faculty_timetable ADD COLUMN timetable_version_id INT REFERENCES timetable_versions(id);
