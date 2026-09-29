from sqlalchemy import Boolean, Column, Integer, String, Numeric, ForeignKey, SmallInteger, Date, DateTime, text
from sqlalchemy.orm import relationship
from database import Base
import datetime

class Class(Base):
    __tablename__ = "classes"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(20), unique=True, nullable=False)
    branch = Column(String(50), nullable=False)
    year = Column(SmallInteger, nullable=False)
    section = Column(String(10))

class Student(Base):
    __tablename__ = "students"
    id = Column(Integer, primary_key=True, index=True)
    roll_number = Column(String(20), unique=True, nullable=False)
    name = Column(String(100), nullable=False)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    batch_number = Column(Integer)
    pair_seat = Column(String(1))
    active = Column(Boolean, default=True)

class Faculty(Base):
    __tablename__ = "faculty"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    department = Column(String(50))
    exempt_from_duty = Column(Boolean, default=False)
    exempt_reason = Column(String(200))
    max_duties_per_day = Column(SmallInteger, default=2)
    abbreviation = Column(String(10))          # e.g. 'VK', 'MG' — from timetable legend

class Subject(Base):
    __tablename__ = "subjects"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    code = Column(String(20))

class AttendanceRecord(Base):
    __tablename__ = "attendance_records"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    faculty_id = Column(Integer, ForeignKey("faculty.id"))
    subject_id = Column(Integer, ForeignKey("subjects.id"))
    semester = Column(String(20))
    classes_conducted = Column(Integer, nullable=False)
    classes_attended = Column(Integer, nullable=False)
    # attendance_pct is computed. In SQLite, we can use a server_default or omit it and compute in Python.
    attendance_pct = Column(Numeric(5, 2))
    upload_date = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
    source_file = Column(String(255))
    approved = Column(Boolean, default=False, nullable=False)

class SystemRule(Base):
    __tablename__ = "system_rules"
    key = Column(String(50), primary_key=True)
    value = Column(String(200), nullable=False)
    description = Column(String(300))

class MstExam(Base):
    __tablename__ = "mst_exams"
    id = Column(Integer, primary_key=True, index=True)
    label = Column(String(20), nullable=False)
    exam_date = Column(Date)
    time_slot = Column(String(20))
    class_id = Column(Integer, ForeignKey("classes.id"))

class MstEligibility(Base):
    __tablename__ = "mst_eligibility"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    mst_exam_id = Column(Integer, ForeignKey("mst_exams.id"), nullable=False)
    overall_pct = Column(Numeric(5, 2))
    lowest_subject_pct = Column(Numeric(5, 2))
    status = Column(String(20), nullable=False)
    override = Column(Boolean, default=False, nullable=False)
    override_reason = Column(String(300))
    override_by = Column(Integer) # Would FK to Users

class MstAttempt(Base):
    __tablename__ = "mst_attempts"
    id = Column(Integer, primary_key=True, index=True)
    student_id = Column(Integer, ForeignKey("students.id"), nullable=False)
    mst_exam_id = Column(Integer, ForeignKey("mst_exams.id"), nullable=False)
    room_id = Column(Integer)
    seat_id = Column(Integer)
    status = Column(String(30), nullable=False)
    marked_by = Column(Integer, ForeignKey("faculty.id"))
    marked_at = Column(DateTime)
    remarks = Column(String(300))

class Room(Base):
    __tablename__ = "rooms"
    id = Column(Integer, primary_key=True, index=True)
    room_number = Column(String(20), nullable=False)
    capacity = Column(Integer)

class Seat(Base):
    __tablename__ = "seats"
    id = Column(Integer, primary_key=True, index=True)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    mst_exam_id = Column(Integer, ForeignKey("mst_exams.id"), nullable=False)
    seat_number = Column(String(10))
    left_student = Column(Integer, ForeignKey("students.id"))
    right_student = Column(Integer, ForeignKey("students.id"))

class TimetableVersion(Base):
    __tablename__ = "timetable_versions"
    id = Column(Integer, primary_key=True, index=True)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    semester = Column(String(20), nullable=False)   # 'III', 'V'
    session = Column(String(30), nullable=False)    # 'Jul-Dec 2026'
    doc_no = Column(String(30))                     # 'AITR/Acad/09' for traceability
    active = Column(Boolean, default=True, nullable=False)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class FacultyTimetable(Base):
    __tablename__ = "faculty_timetable"
    id = Column(Integer, primary_key=True, index=True)
    faculty_id = Column(Integer, ForeignKey("faculty.id"), nullable=False)
    day_of_week = Column(String(10), nullable=False)
    # period_start / period_end replace the old single 'time_slot' column
    period_start = Column(String(10), nullable=False)   # '10:30'
    period_end = Column(String(10), nullable=False)     # '11:20'
    subject_code = Column(String(20))
    subject_name = Column(String(100))
    room = Column(String(20))
    batch = Column(String(10))           # 'B1', 'B2', or NULL for whole class
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    year = Column(Integer, nullable=False)
    semester = Column(String(20))        # 'III', 'V' — for reference
    timetable_version_id = Column(Integer, ForeignKey("timetable_versions.id"))
    faculty = relationship("Faculty")

class InvigilationDuty(Base):
    __tablename__ = "invigilation_duties"
    id = Column(Integer, primary_key=True, index=True)
    mst_exam_id = Column(Integer, ForeignKey("mst_exams.id"), nullable=False)
    room_id = Column(Integer, ForeignKey("rooms.id"), nullable=False)
    faculty_id = Column(Integer, ForeignKey("faculty.id"))
    status = Column(String(20), nullable=False, default="Unfilled")
    assigned_at = Column(DateTime)

class DutyReplacement(Base):
    __tablename__ = "duty_replacements"
    id = Column(Integer, primary_key=True, index=True)
    duty_id = Column(Integer, ForeignKey("invigilation_duties.id"), nullable=False)
    original_faculty = Column(Integer, ForeignKey("faculty.id"))
    replacement_faculty = Column(Integer, ForeignKey("faculty.id"))
    reason = Column(String(300), nullable=False)
    changed_by = Column(Integer)
    changed_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)

class User(Base):
    __tablename__ = "users"
    id = Column(Integer, primary_key=True, index=True)
    name = Column(String(100), nullable=False)
    role = Column(String(30), nullable=False)
    email = Column(String(150), unique=True)

class AuditLog(Base):
    __tablename__ = "audit_logs"
    id = Column(Integer, primary_key=True, index=True)
    table_name = Column(String(50), nullable=False)
    record_id = Column(Integer, nullable=False)
    field_changed = Column(String(50))
    old_value = Column(String(300))
    new_value = Column(String(300))
    changed_by = Column(Integer, ForeignKey("users.id"))
    reason = Column(String(300))
    changed_at = Column(DateTime, default=datetime.datetime.utcnow, nullable=False)
