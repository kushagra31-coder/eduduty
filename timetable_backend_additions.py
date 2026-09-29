# ============================================================
# ADD TO schemas.py
# ============================================================
from pydantic import BaseModel
from typing import Optional, List

class TimetableEntryBase(BaseModel):
    faculty_id: int
    day_of_week: str          # 'MON','TUE','WED','THUR','FRI'
    period_start: str         # '10:30'
    period_end: str           # '11:20'
    subject_code: Optional[str] = None
    subject_name: Optional[str] = None
    room: Optional[str] = None
    batch: Optional[str] = None   # 'B1' / 'B2' / None
    class_id: int
    year: int                 # 2, 3, 4 — always the taught class's actual year
    semester: Optional[str] = None

class TimetableEntryCreate(TimetableEntryBase):
    timetable_version_id: int

class TimetableEntryOut(TimetableEntryBase):
    id: int
    faculty_name: Optional[str] = None
    class Config:
        from_attributes = True

class TimetableVersionCreate(BaseModel):
    class_id: int
    semester: str
    session: str
    doc_no: Optional[str] = None

class TimetableVersionOut(TimetableVersionCreate):
    id: int
    active: bool
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


# ============================================================
# ADD TO crud.py
# ============================================================
from sqlalchemy.orm import Session
from sqlalchemy import and_
import models, schemas

def create_timetable_version(db: Session, v: schemas.TimetableVersionCreate):
    # deactivate any existing active version for this class+semester so old
    # data is kept but no longer counted as current
    db.query(models.TimetableVersion).filter(
        models.TimetableVersion.class_id == v.class_id,
        models.TimetableVersion.semester == v.semester,
        models.TimetableVersion.active == True,
    ).update({"active": False})
    obj = models.TimetableVersion(**v.dict(), active=True)
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

def create_timetable_entry(db: Session, e: schemas.TimetableEntryCreate):
    obj = models.FacultyTimetable(**e.dict())
    db.add(obj)
    db.commit()
    db.refresh(obj)
    return obj

def bulk_create_timetable_entries(db: Session, entries: List[schemas.TimetableEntryCreate]):
    objs = [models.FacultyTimetable(**e.dict()) for e in entries]
    db.add_all(objs)
    db.commit()
    return objs

def get_timetable_for_class(db: Session, class_id: int, semester: str = None):
    q = db.query(models.FacultyTimetable).filter(models.FacultyTimetable.class_id == class_id)
    if semester:
        q = q.filter(models.FacultyTimetable.semester == semester)
    return q.all()

def check_faculty_availability(db: Session, day_of_week: str, period_start: str, period_end: str):
    """
    Core clash rule: a faculty member is blocked if they have ANY class,
    in ANY year, whose period overlaps this slot — not just classes in
    the years sitting the MST.
    """
    results = []
    faculty_all = db.query(models.Faculty).all()
    for f in faculty_all:
        if f.exempt_from_duty:
            results.append(schemas.FacultyAvailabilityResult(
                faculty_id=f.id, faculty_name=f.name,
                status="Exempt", reason=f.exempt_reason or "Excluded by administrator"))
            continue

        clash = db.query(models.FacultyTimetable).filter(
            models.FacultyTimetable.faculty_id == f.id,
            models.FacultyTimetable.day_of_week == day_of_week,
            # overlap check: existing.start < new.end AND existing.end > new.start
            models.FacultyTimetable.period_start < period_end,
            models.FacultyTimetable.period_end > period_start,
        ).first()

        if clash:
            results.append(schemas.FacultyAvailabilityResult(
                faculty_id=f.id, faculty_name=f.name,
                status="Blocked",
                reason=f"Year {clash.year} class ({clash.subject_code or 'class'}) "
                       f"{clash.period_start}-{clash.period_end}"))
        else:
            results.append(schemas.FacultyAvailabilityResult(
                faculty_id=f.id, faculty_name=f.name,
                status="Available", reason="No class or duty conflict"))
    return results


# ============================================================
# ADD TO models.py
# ============================================================
from sqlalchemy import Column, Integer, String, Boolean, ForeignKey, DateTime
from sqlalchemy.orm import relationship
from database import Base
import datetime

class TimetableVersion(Base):
    __tablename__ = "timetable_versions"
    id = Column(Integer, primary_key=True)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    semester = Column(String, nullable=False)
    session = Column(String, nullable=False)
    doc_no = Column(String)
    active = Column(Boolean, default=True)
    created_at = Column(DateTime, default=datetime.datetime.utcnow)

class FacultyTimetable(Base):
    __tablename__ = "faculty_timetable"
    id = Column(Integer, primary_key=True)
    faculty_id = Column(Integer, ForeignKey("faculty.id"), nullable=False)
    day_of_week = Column(String, nullable=False)
    period_start = Column(String, nullable=False)
    period_end = Column(String, nullable=False)
    subject_code = Column(String)
    subject_name = Column(String)
    room = Column(String)
    batch = Column(String, nullable=True)
    class_id = Column(Integer, ForeignKey("classes.id"), nullable=False)
    year = Column(Integer, nullable=False)
    semester = Column(String)
    timetable_version_id = Column(Integer, ForeignKey("timetable_versions.id"))
    faculty = relationship("Faculty")


# ============================================================
# ADD TO main.py
# ============================================================
from fastapi import APIRouter, Depends
from sqlalchemy.orm import Session
import crud, schemas
# assumes get_db already defined elsewhere in main.py

router = APIRouter(prefix="/timetable", tags=["timetable"])

@router.post("/version", response_model=schemas.TimetableVersionOut)
def create_version(v: schemas.TimetableVersionCreate, db: Session = Depends(get_db)):
    return crud.create_timetable_version(db, v)

@router.post("/entry", response_model=schemas.TimetableEntryOut)
def create_entry(e: schemas.TimetableEntryCreate, db: Session = Depends(get_db)):
    return crud.create_timetable_entry(db, e)

@router.post("/entries/bulk")
def create_entries_bulk(entries: list[schemas.TimetableEntryCreate], db: Session = Depends(get_db)):
    crud.bulk_create_timetable_entries(db, entries)
    return {"created": len(entries)}

@router.get("/class/{class_id}", response_model=list[schemas.TimetableEntryOut])
def get_class_timetable(class_id: int, semester: str = None, db: Session = Depends(get_db)):
    return crud.get_timetable_for_class(db, class_id, semester)

@router.post("/availability", response_model=list[schemas.FacultyAvailabilityResult])
def faculty_availability(check: schemas.FacultyAvailabilityCheck, db: Session = Depends(get_db)):
    return crud.check_faculty_availability(db, check.day_of_week, check.period_start, check.period_end)

# then in main app setup: app.include_router(router)
