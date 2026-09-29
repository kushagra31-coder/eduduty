from fastapi import FastAPI, Depends, HTTPException, UploadFile, File, Body
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import Response
from sqlalchemy.orm import Session
from pydantic import BaseModel
from database import engine, get_db
import models, schemas, crud
import ai_service, pdf_service
import pandas as pd
import io

models.Base.metadata.create_all(bind=engine)

app = FastAPI(title="MST Operations Portal API")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

@app.get("/")
def read_root():
    return {"message": "MST Operations Portal Backend"}

# ── Attendance upload ──────────────────────────────────────────────────────────

@app.post("/upload-attendance/")
async def upload_attendance(
    file: UploadFile = File(...),
    db: Session = Depends(get_db)
):
    if not file.filename.endswith(('.xls', '.xlsx')):
        raise HTTPException(status_code=400, detail="Invalid file type. Please upload an Excel file.")

    contents = await file.read()
    try:
        df = pd.read_excel(io.BytesIO(contents))
        mst_exam_id = 1
        dummy_exam = db.query(models.MstExam).filter_by(id=mst_exam_id).first()
        if not dummy_exam:
            dummy_exam = models.MstExam(id=mst_exam_id, label="MST-1")
            db.add(dummy_exam)
            db.commit()

        imported_count = 0
        for _, row in df.iterrows():
            roll_number = str(row.get('Roll Number', ''))
            if not roll_number or roll_number == 'nan':
                continue
            name     = str(row.get('Name', 'Unknown'))
            total    = int(row.get('Total Classes', 0))
            attended = int(row.get('Attended', 0))
            student  = crud.get_student_by_roll(db, roll_number)
            if not student:
                c = crud.get_class_by_name(db, "CI-1")
                if not c:
                    c = models.Class(name="CI-1", branch="CSE", year=3)
                    db.add(c); db.commit(); db.refresh(c)
                student = models.Student(roll_number=roll_number, name=name, class_id=c.id)
                db.add(student); db.commit(); db.refresh(student)
            att = schemas.AttendanceRecordBase(
                student_id=student.id,
                classes_conducted=total,
                classes_attended=attended
            )
            crud.create_attendance_record(db, att)
            crud.compute_eligibility_for_student(db, student.id, mst_exam_id)
            imported_count += 1
        return {"filename": file.filename, "rows_imported": imported_count}
    except Exception as e:
        raise HTTPException(status_code=500, detail=f"Error processing file: {str(e)}")

# ── Eligibility ────────────────────────────────────────────────────────────────

@app.get("/eligibility/{mst_exam_id}", response_model=list[schemas.MstEligibilityDisplay])
def get_eligibility(mst_exam_id: int, db: Session = Depends(get_db)):
    return crud.get_mst_eligibility(db, mst_exam_id)

@app.post("/eligibility/override/{eligibility_id}")
def override_eligibility(
    eligibility_id: int,
    override: bool = Body(...),
    reason: str = Body(...),
    db: Session = Depends(get_db)
):
    user_id = 1
    record = crud.update_eligibility_override(db, eligibility_id, override, reason, user_id)
    if not record:
        raise HTTPException(status_code=404, detail="Eligibility record not found")
    return {"message": "Override applied successfully"}

# ── AI assistant ───────────────────────────────────────────────────────────────

class AIMessageRequest(BaseModel):
    message: str

class WriteConfirmRequest(BaseModel):
    op_json: dict

@app.post("/ai/query")
async def ai_query(req: AIMessageRequest, db: Session = Depends(get_db)):
    """
    Route a natural language message to read / write-proposal / pdf path.
    Returns { type, content }
    """
    try:
        result = await ai_service.handle_ai_message(req.message, db)
        return result
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

@app.post("/ai/confirm-write")
def ai_confirm_write(req: WriteConfirmRequest, db: Session = Depends(get_db)):
    """
    Execute an AI-proposed write ONLY after the user has explicitly confirmed in the UI.
    """
    try:
        result = ai_service.execute_write_op(req.op_json, db)
        return {"success": True, "changed": result}
    except ValueError as e:
        raise HTTPException(status_code=400, detail=str(e))
    except Exception as e:
        raise HTTPException(status_code=500, detail=str(e))

# ── PDF generation ─────────────────────────────────────────────────────────────

@app.get("/pdf/student/{roll_number}")
def get_student_pdf(roll_number: str, db: Session = Depends(get_db)):
    """Generate and stream a formal student record PDF."""
    try:
        html      = pdf_service.build_student_record_html(roll_number, db)
        pdf_bytes = pdf_service.render_pdf(html)
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename=student_{roll_number}.pdf"},
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

@app.get("/pdf/seating/{mst_exam_id}/{room_id}")
def get_seating_pdf(mst_exam_id: int, room_id: int, db: Session = Depends(get_db)):
    """Generate and stream a seating chart + signature sheet PDF."""
    try:
        html      = pdf_service.build_seating_chart_html(mst_exam_id, room_id, db)
        pdf_bytes = pdf_service.render_pdf(html)
        exam  = db.query(models.MstExam).filter_by(id=mst_exam_id).first()
        room  = db.query(models.Room).filter_by(id=room_id).first()
        fname = f"seating_{exam.label if exam else mst_exam_id}_room{room.room_number if room else room_id}.pdf"
        return Response(
            content=pdf_bytes,
            media_type="application/pdf",
            headers={"Content-Disposition": f"inline; filename={fname}"},
        )
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))
    except RuntimeError as e:
        raise HTTPException(status_code=503, detail=str(e))

@app.get("/pdf/student/{roll_number}/html")
def get_student_html(roll_number: str, db: Session = Depends(get_db)):
    """Debug: returns raw HTML preview without WeasyPrint installed."""
    try:
        html = pdf_service.build_student_record_html(roll_number, db)
        return Response(content=html, media_type="text/html")
    except ValueError as e:
        raise HTTPException(status_code=404, detail=str(e))


# ── Timetable ──────────────────────────────────────────────────────────────────
from fastapi import APIRouter

timetable_router = APIRouter(prefix="/timetable", tags=["timetable"])

@timetable_router.post("/version", response_model=schemas.TimetableVersionOut)
def create_timetable_version(v: schemas.TimetableVersionCreate, db: Session = Depends(get_db)):
    return crud.create_timetable_version(db, v)

@timetable_router.post("/entry", response_model=schemas.TimetableEntryOut)
def create_timetable_entry(e: schemas.TimetableEntryCreate, db: Session = Depends(get_db)):
    return crud.create_timetable_entry(db, e)

@timetable_router.post("/entries/bulk")
def create_timetable_entries_bulk(
    entries: list[schemas.TimetableEntryCreate],
    db: Session = Depends(get_db),
):
    crud.bulk_create_timetable_entries(db, entries)
    return {"created": len(entries)}

@timetable_router.get("/class/{class_id}", response_model=list[schemas.TimetableEntryOut])
def get_class_timetable(
    class_id: int,
    semester: str = None,
    db: Session = Depends(get_db),
):
    return crud.get_timetable_for_class(db, class_id, semester)

@timetable_router.post("/availability", response_model=list[schemas.FacultyAvailabilityResult])
def faculty_availability(
    check: schemas.FacultyAvailabilityCheck,
    db: Session = Depends(get_db),
):
    return crud.check_faculty_availability(
        db, check.day_of_week, check.period_start, check.period_end
    )

app.include_router(timetable_router)


# ── Classes / Faculty helpers (used by timetable frontend) ─────────────────────

@app.get("/classes", response_model=list[schemas.ClassOut])
def list_classes(db: Session = Depends(get_db)):
    return crud.get_classes(db)

@app.get("/faculty")
def list_faculty(db: Session = Depends(get_db)):
    rows = db.query(models.Faculty).all()
    return [
        {
            "id": f.id,
            "name": f.name,
            "abbreviation": f.abbreviation,
            "department": f.department,
            "exempt_from_duty": f.exempt_from_duty,
        }
        for f in rows
    ]
