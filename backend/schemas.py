from pydantic import BaseModel
from typing import Optional, List
from decimal import Decimal
from datetime import datetime, date

class ClassBase(BaseModel):
    name: str
    branch: str
    year: int
    section: Optional[str] = None

class ClassOut(ClassBase):
    id: int

    class Config:
        orm_mode = True

class StudentBase(BaseModel):
    roll_number: str
    name: str
    class_id: int
    batch_number: Optional[int] = None
    pair_seat: Optional[str] = None
    active: bool = True

class StudentOut(StudentBase):
    id: int
    
    class Config:
        orm_mode = True

class StudentWithClass(StudentOut):
    # This might require some relationships not strictly set in pydantic yet
    pass

class AttendanceRecordBase(BaseModel):
    student_id: int
    faculty_id: Optional[int] = None
    subject_id: Optional[int] = None
    semester: Optional[str] = None
    classes_conducted: int
    classes_attended: int

class AttendanceRecordOut(AttendanceRecordBase):
    id: int
    attendance_pct: Optional[Decimal] = None
    upload_date: datetime
    source_file: Optional[str] = None
    approved: bool
    
    class Config:
        orm_mode = True

class MstEligibilityBase(BaseModel):
    student_id: int
    mst_exam_id: int
    overall_pct: Optional[Decimal] = None
    lowest_subject_pct: Optional[Decimal] = None
    status: str
    override: bool = False
    override_reason: Optional[str] = None
    override_by: Optional[int] = None

class MstEligibilityOut(MstEligibilityBase):
    id: int
    
    class Config:
        orm_mode = True

# Used for joining data on frontend
class MstEligibilityDisplay(BaseModel):
    id: int
    student_id: int
    roll_number: str
    name: str
    mst_exam_id: int
    overall_pct: Optional[Decimal] = None
    lowest_subject_pct: Optional[Decimal] = None
    status: str
    override: bool
    override_reason: Optional[str] = None
    
    class Config:
        orm_mode = True


# ── Timetable ──────────────────────────────────────────────────────────────────

class TimetableVersionCreate(BaseModel):
    class_id: int
    semester: str       # 'III', 'V'
    session: str        # 'Jul-Dec 2026'
    doc_no: Optional[str] = None

class TimetableVersionOut(TimetableVersionCreate):
    id: int
    active: bool
    class Config:
        from_attributes = True

class TimetableEntryBase(BaseModel):
    faculty_id: int
    day_of_week: str           # 'MON','TUE','WED','THUR','FRI'
    period_start: str          # '10:30'
    period_end: str            # '11:20'
    subject_code: Optional[str] = None
    subject_name: Optional[str] = None
    room: Optional[str] = None
    batch: Optional[str] = None    # 'B1' / 'B2' / None for whole class
    class_id: int
    year: int                  # taught class's actual year
    semester: Optional[str] = None

class TimetableEntryCreate(TimetableEntryBase):
    timetable_version_id: int

class TimetableEntryOut(TimetableEntryBase):
    id: int
    faculty_name: Optional[str] = None
    class Config:
        from_attributes = True

class FacultyAvailabilityCheck(BaseModel):
    day_of_week: str
    period_start: str
    period_end: str

class FacultyAvailabilityResult(BaseModel):
    faculty_id: int
    faculty_name: str
    status: str        # 'Available' | 'Blocked' | 'Exempt'
    reason: str
