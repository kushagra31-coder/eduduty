-- MST Operations Portal — PostgreSQL schema
-- Core principle: attendance eligibility, MST appearance, and VT eligibility
-- are tracked as SEPARATE fields, never collapsed into one status.

-- ========== PEOPLE & STRUCTURE ==========

CREATE TABLE classes (
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(20) NOT NULL UNIQUE,   -- 'CI-1', 'CS-81', 'Cyber-3'
    branch        VARCHAR(50) NOT NULL,
    year          SMALLINT NOT NULL,             -- 2, 3, 4
    section       VARCHAR(10)
);

CREATE TABLE students (
    id            SERIAL PRIMARY KEY,
    roll_number   VARCHAR(20) NOT NULL UNIQUE,   -- never use name as key
    name          VARCHAR(100) NOT NULL,
    class_id      INT NOT NULL REFERENCES classes(id),
    batch_number  INT,                           -- pair batch (1..40 for 80 students)
    pair_seat     CHAR(1) CHECK (pair_seat IN ('L','R')),
    active        BOOLEAN NOT NULL DEFAULT TRUE
);

CREATE TABLE faculty (
    id                  SERIAL PRIMARY KEY,
    name                VARCHAR(100) NOT NULL,
    department          VARCHAR(50),
    exempt_from_duty    BOOLEAN NOT NULL DEFAULT FALSE,
    exempt_reason       VARCHAR(200),
    max_duties_per_day  SMALLINT DEFAULT 2
);

CREATE TABLE subjects (
    id          SERIAL PRIMARY KEY,
    name        VARCHAR(100) NOT NULL,
    code        VARCHAR(20)
);

-- ========== ATTENDANCE & ELIGIBILITY ==========

CREATE TABLE attendance_records (
    id                  SERIAL PRIMARY KEY,
    student_id          INT NOT NULL REFERENCES students(id),
    faculty_id          INT REFERENCES faculty(id),
    subject_id          INT REFERENCES subjects(id),
    semester            VARCHAR(20),
    classes_conducted   INT NOT NULL,
    classes_attended    INT NOT NULL,
    attendance_pct      NUMERIC(5,2) GENERATED ALWAYS AS
                         (CASE WHEN classes_conducted = 0 THEN 0
                               ELSE ROUND(100.0 * classes_attended / classes_conducted, 2) END) STORED,
    upload_date         TIMESTAMP NOT NULL DEFAULT now(),
    source_file         VARCHAR(255),
    approved            BOOLEAN NOT NULL DEFAULT FALSE
);

CREATE TABLE system_rules (
    key           VARCHAR(50) PRIMARY KEY,       -- e.g. 'eligibility_threshold_pct'
    value         VARCHAR(200) NOT NULL,
    description   VARCHAR(300)
);

-- ========== MST EVENTS ==========

CREATE TABLE mst_exams (
    id            SERIAL PRIMARY KEY,
    label         VARCHAR(20) NOT NULL,          -- 'MST-1', 'MST-2'
    exam_date     DATE,
    time_slot     VARCHAR(20),                   -- '10:00-11:00'
    class_id      INT REFERENCES classes(id)
);

CREATE TABLE mst_eligibility (
    id              SERIAL PRIMARY KEY,
    student_id      INT NOT NULL REFERENCES students(id),
    mst_exam_id     INT NOT NULL REFERENCES mst_exams(id),
    overall_pct     NUMERIC(5,2),
    lowest_subject_pct NUMERIC(5,2),
    status          VARCHAR(20) NOT NULL,        -- Eligible / Not eligible / Borderline / Missing
    override        BOOLEAN NOT NULL DEFAULT FALSE,
    override_reason VARCHAR(300),
    override_by     INT,
    UNIQUE (student_id, mst_exam_id)
);

CREATE TABLE mst_attempts (
    id            SERIAL PRIMARY KEY,
    student_id    INT NOT NULL REFERENCES students(id),
    mst_exam_id   INT NOT NULL REFERENCES mst_exams(id),
    room_id       INT,
    seat_id       INT,
    status        VARCHAR(30) NOT NULL,          -- Present/Absent/Late/Excused/Not eligible/Signature missing
    marked_by     INT REFERENCES faculty(id),
    marked_at     TIMESTAMP,
    remarks       VARCHAR(300),
    UNIQUE (student_id, mst_exam_id)
);

-- ========== SEATING ==========

CREATE TABLE rooms (
    id          SERIAL PRIMARY KEY,
    room_number VARCHAR(20) NOT NULL,
    capacity    INT
);

CREATE TABLE seats (
    id            SERIAL PRIMARY KEY,
    room_id       INT NOT NULL REFERENCES rooms(id),
    mst_exam_id   INT NOT NULL REFERENCES mst_exams(id),
    seat_number   VARCHAR(10),
    left_student  INT REFERENCES students(id),
    right_student INT REFERENCES students(id)
);

-- ========== TIMETABLE & DUTY SCHEDULING ==========

CREATE TABLE faculty_timetable (
    id          SERIAL PRIMARY KEY,
    faculty_id  INT NOT NULL REFERENCES faculty(id),
    day_of_week VARCHAR(10) NOT NULL,
    time_slot   VARCHAR(20) NOT NULL,
    class_id    INT REFERENCES classes(id),
    year        SMALLINT NOT NULL                -- checked regardless of MST class's year
);

CREATE TABLE invigilation_duties (
    id            SERIAL PRIMARY KEY,
    mst_exam_id   INT NOT NULL REFERENCES mst_exams(id),
    room_id       INT NOT NULL REFERENCES rooms(id),
    faculty_id    INT REFERENCES faculty(id),
    status        VARCHAR(20) NOT NULL DEFAULT 'Unfilled', -- Assigned/Unfilled
    assigned_at   TIMESTAMP
);

CREATE TABLE duty_replacements (
    id                SERIAL PRIMARY KEY,
    duty_id           INT NOT NULL REFERENCES invigilation_duties(id),
    original_faculty  INT REFERENCES faculty(id),
    replacement_faculty INT REFERENCES faculty(id),
    reason            VARCHAR(300) NOT NULL,
    changed_by        INT,
    changed_at        TIMESTAMP NOT NULL DEFAULT now()
);

-- ========== USERS & AUDIT ==========

CREATE TABLE users (
    id            SERIAL PRIMARY KEY,
    name          VARCHAR(100) NOT NULL,
    role          VARCHAR(30) NOT NULL,          -- Admin/HOD, Exam Coordinator, Faculty, Invigilator, AI-readonly
    email         VARCHAR(150) UNIQUE
);

CREATE TABLE audit_logs (
    id            SERIAL PRIMARY KEY,
    table_name    VARCHAR(50) NOT NULL,
    record_id     INT NOT NULL,
    field_changed VARCHAR(50),
    old_value     VARCHAR(300),
    new_value     VARCHAR(300),
    changed_by    INT REFERENCES users(id),
    reason        VARCHAR(300),
    changed_at    TIMESTAMP NOT NULL DEFAULT now()
);

-- ========== READ-ONLY VIEW FOR LOCAL AI ==========
-- Expose only aggregated/approved data to the AI's read-only DB role.

CREATE VIEW ai_eligibility_summary AS
SELECT c.name AS class_name, me.label AS mst_label,
       COUNT(*) FILTER (WHERE el.status = 'Eligible') AS eligible_count,
       COUNT(*) FILTER (WHERE el.status = 'Not eligible') AS ineligible_count,
       COUNT(*) FILTER (WHERE el.status = 'Missing') AS missing_count
FROM mst_eligibility el
JOIN mst_exams me ON me.id = el.mst_exam_id
JOIN students s ON s.id = el.student_id
JOIN classes c ON c.id = s.class_id
GROUP BY c.name, me.label;

-- Seed default rules
INSERT INTO system_rules (key, value, description) VALUES
  ('eligibility_threshold_pct', '50', 'Minimum overall attendance % to be MST-eligible'),
  ('borderline_band_pct', '45-49.99', 'Attendance % range flagged as borderline'),
  ('vt_rule', 'compulsory_if_both_mst_missed', 'Configurable VT eligibility rule');
