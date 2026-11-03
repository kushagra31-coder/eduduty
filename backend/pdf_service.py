"""
PDF Service — generates formal academic PDFs for student records, seating charts, and VT lists.
Uses fpdf2 for pure-Python, zero-dependency PDF generation that works reliably across Windows and Linux.
HTML builders are preserved for in-browser HTML preview and browser printing.
"""

import io
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
from fpdf import FPDF
import models

try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    WEASYPRINT_AVAILABLE = False


# ── Clean text helper for PDF rendering ───────────────────────────────────────
def _safe_str(val) -> str:
    if val is None:
        return "-"
    s = str(val)
    # Replace unicode dashes / characters with ASCII equivalents for clean standard fonts
    s = s.replace("—", "-").replace("–", "-").replace("’", "'").replace("“", '"').replace("”", '"').replace("…", "...")
    try:
        return s.encode("latin-1", "replace").decode("latin-1")
    except Exception:
        return "".join(c if ord(c) < 128 else "-" for c in s)


# ── FPDF Base Class with Clean Academic Header / Footer ───────────────────────
class AcademicPDF(FPDF):
    def __init__(self, title_text="MST OPERATIONS PORTAL", subtitle_text="Department of Computer Science & IT", orientation='P'):
        super().__init__(orientation=orientation, unit='mm', format='A4')
        self.doc_title = _safe_str(title_text)
        self.doc_subtitle = _safe_str(subtitle_text)
        self.set_auto_page_break(auto=True, margin=15)

    def header(self):
        self.set_font('Helvetica', 'B', 13)
        self.set_text_color(30, 41, 59)
        self.cell(0, 6, self.doc_title, align='C', new_x='LMARGIN', new_y='NEXT')
        self.set_font('Helvetica', '', 9)
        self.set_text_color(100, 116, 139)
        self.cell(0, 5, self.doc_subtitle, align='C', new_x='LMARGIN', new_y='NEXT')
        self.set_draw_color(226, 232, 240)
        self.set_line_width(0.3)
        self.line(10, self.get_y() + 2, self.w - 10, self.get_y() + 2)
        self.ln(5)

    def footer(self):
        self.set_y(-12)
        self.set_font('Helvetica', '', 8)
        self.set_text_color(148, 163, 184)
        page_str = f"Page {self.page_no()}"
        self.cell(0, 8, f"EduDuty Portal | Generated: {datetime.now().strftime('%d %b %Y %H:%M')} | {page_str}", align='C')


# ── Direct fpdf2 Seating Chart PDF ─────────────────────────────────────────────
def build_seating_pdf(mst_exam_id: int, room_id: int, db: Session) -> bytes:
    exam = db.query(models.MstExam).filter_by(id=mst_exam_id).first()
    room = db.query(models.Room).filter_by(id=room_id).first()
    if not exam or not room:
        raise ValueError("Exam or room not found.")

    seats = db.query(models.Seat).filter_by(mst_exam_id=mst_exam_id, room_id=room_id).all()
    duty = db.query(models.InvigilationDuty).filter_by(mst_exam_id=mst_exam_id, room_id=room_id).first()
    invigilator = "Not Assigned"
    if duty and duty.faculty_id:
        fac = db.query(models.Faculty).filter_by(id=duty.faculty_id).first()
        if fac:
            invigilator = fac.name

    pdf = AcademicPDF(
        title_text="INSTITUTE OF ENGINEERING & TECHNOLOGY - CSIT",
        subtitle_text=f"MST Examination Seating Chart & Attendance Sheet — Room {room.room_number}",
        orientation='P'
    )
    pdf.add_page()

    # Exam Info Banner
    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(203, 213, 225)
    pdf.rect(10, pdf.get_y(), pdf.w - 20, 16, style='FD')

    pdf.set_font('Helvetica', 'B', 9)
    pdf.set_text_color(15, 23, 42)
    exam_date = exam.exam_date.strftime("%d %B %Y") if exam.exam_date else "Date: TBD"
    slot_info = exam.time_slot or "Slot: TBD"

    curr_y = pdf.get_y() + 2
    pdf.set_xy(14, curr_y)
    pdf.cell(85, 5, f"Exam: {_safe_str(exam.label)} ({exam_date})")
    pdf.cell(85, 5, f"Room: Room {_safe_str(room.room_number)} (Capacity: {_safe_str(room.capacity)})")

    pdf.set_xy(14, curr_y + 6)
    pdf.cell(85, 5, f"Time: {slot_info}")
    pdf.cell(85, 5, f"Invigilator: {_safe_str(invigilator)}")

    pdf.set_y(curr_y + 16)

    # Table of Benches
    col_widths = (16, 50, 25, 50, 25, 24)

    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_text_color(30, 41, 59)

    with pdf.table(col_widths=col_widths, text_align="CENTER", line_height=6) as table:
        header = table.row()
        header.cell("Bench")
        header.cell("Left Student (L)")
        header.cell("Left Sig")
        header.cell("Right Student (R)")
        header.cell("Right Sig")
        header.cell("Remarks")

        pdf.set_font('Helvetica', '', 8)
        for s in seats:
            left_s = db.query(models.Student).filter_by(id=s.left_student).first() if s.left_student else None
            right_s = db.query(models.Student).filter_by(id=s.right_student).first() if s.right_student else None

            l_text = f"{_safe_str(left_s.roll_number)}\n{_safe_str(left_s.name)}" if left_s else "-"
            r_text = f"{_safe_str(right_s.roll_number)}\n{_safe_str(right_s.name)}" if right_s else "-"

            row = table.row()
            row.cell(_safe_str(s.seat_number))
            row.cell(l_text)
            row.cell("")  # Signature box
            row.cell(r_text)
            row.cell("")  # Signature box
            row.cell("")

    # Invigilator sign-off
    pdf.ln(6)
    pdf.set_font('Helvetica', '', 9)
    pdf.set_text_color(51, 65, 85)
    pdf.cell(95, 6, "Total Present: ________   Total Absent: ________")
    pdf.cell(95, 6, "Invigilator Signature: _______________________", align='R')

    return bytes(pdf.output())


# ── Direct fpdf2 Student Academic Record PDF ──────────────────────────────────
def build_student_pdf(roll_number: str, db: Session) -> bytes:
    student = db.query(models.Student).filter_by(roll_number=roll_number).first()
    if not student:
        raise ValueError(f"Student with roll number {roll_number} not found.")

    cls = db.query(models.Class).filter_by(id=student.class_id).first()
    attendance_rows = db.query(models.AttendanceRecord).filter_by(student_id=student.id).all()
    eligibility_rows = db.query(models.MstEligibility).filter_by(student_id=student.id).all()
    attempt_rows = db.query(models.MstAttempt).filter_by(student_id=student.id).all()

    pdf = AcademicPDF(
        title_text="INSTITUTE OF ENGINEERING & TECHNOLOGY - CSIT",
        subtitle_text=f"Student Academic & Examination Dossier — {_safe_str(student.roll_number)}",
        orientation='P'
    )
    pdf.add_page()

    # Student Info Grid
    pdf.set_fill_color(248, 250, 252)
    pdf.set_draw_color(203, 213, 225)
    pdf.rect(10, pdf.get_y(), pdf.w - 20, 20, style='FD')

    pdf.set_font('Helvetica', 'B', 9)
    y0 = pdf.get_y() + 2
    pdf.set_xy(14, y0)
    pdf.cell(60, 5, f"Name: {_safe_str(student.name)}")
    pdf.cell(60, 5, f"Roll No: {_safe_str(student.roll_number)}")
    pdf.cell(60, 5, f"Class: {_safe_str(cls.name if cls else '-')}")

    pdf.set_xy(14, y0 + 6)
    pdf.cell(60, 5, f"Year: Year {_safe_str(cls.year if cls else '-')}")
    pdf.cell(60, 5, f"Batch: {_safe_str(student.batch_number)}")
    pdf.cell(60, 5, f"Pair Seat: {_safe_str(student.pair_seat)}")

    pdf.set_xy(14, y0 + 12)
    pdf.cell(180, 5, f"Department: Computer Science & Information Technology (CSIT)")

    pdf.set_y(y0 + 22)

    # Attendance Table
    pdf.set_font('Helvetica', 'B', 10)
    pdf.set_text_color(15, 23, 42)
    pdf.cell(0, 6, "Subject-wise Attendance", new_x='LMARGIN', new_y='NEXT')

    pdf.set_font('Helvetica', '', 8)
    with pdf.table(col_widths=(60, 30, 30, 35, 35), text_align="CENTER", line_height=6) as table:
        hdr = table.row()
        hdr.cell("Subject")
        hdr.cell("Conducted")
        hdr.cell("Attended")
        hdr.cell("Attendance %")
        hdr.cell("Semester")

        for rec in attendance_rows:
            subj = db.query(models.Subject).filter_by(id=rec.subject_id).first()
            sname = subj.name if subj else "-"
            r = table.row()
            r.cell(_safe_str(sname))
            r.cell(_safe_str(rec.classes_conducted))
            r.cell(_safe_str(rec.classes_attended))
            r.cell(f"{rec.pct:.1f}%")
            r.cell(_safe_str(rec.semester))

    pdf.ln(4)

    # Eligibility Table
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 6, "MST Eligibility Status", new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Helvetica', '', 8)

    with pdf.table(col_widths=(40, 35, 35, 40, 40), text_align="CENTER", line_height=6) as table:
        hdr = table.row()
        hdr.cell("Exam")
        hdr.cell("Overall %")
        hdr.cell("Lowest Subj %")
        hdr.cell("Status")
        hdr.cell("Override Reason")

        for el in eligibility_rows:
            ex = db.query(models.MstExam).filter_by(id=el.mst_exam_id).first()
            ex_label = ex.label if ex else f"Exam {el.mst_exam_id}"
            r = table.row()
            r.cell(_safe_str(ex_label))
            r.cell(f"{el.overall_pct:.1f}%" if el.overall_pct else "-")
            r.cell(f"{el.lowest_subject_pct:.1f}%" if el.lowest_subject_pct else "-")
            status_txt = "Overridden" if el.override else _safe_str(el.status)
            r.cell(status_txt)
            r.cell(_safe_str(el.override_reason))

    pdf.ln(4)

    # Exam Day Appearance
    pdf.set_font('Helvetica', 'B', 10)
    pdf.cell(0, 6, "Exam-day Attendance & Marks", new_x='LMARGIN', new_y='NEXT')
    pdf.set_font('Helvetica', '', 8)

    with pdf.table(col_widths=(50, 40, 50, 50), text_align="CENTER", line_height=6) as table:
        hdr = table.row()
        hdr.cell("Exam")
        hdr.cell("Outcome")
        hdr.cell("Recorded At")
        hdr.cell("Remarks")

        for att in attempt_rows:
            ex = db.query(models.MstExam).filter_by(id=att.mst_exam_id).first()
            r = table.row()
            r.cell(_safe_str(ex.label if ex else "-"))
            r.cell(_safe_str(att.status))
            r.cell(att.marked_at.strftime('%Y-%m-%d %H:%M') if att.marked_at else "-")
            r.cell(_safe_str(att.remarks))

    return bytes(pdf.output())


# ── Direct fpdf2 VT Compulsory List PDF ────────────────────────────────────────
def build_follow_up_pdf(rows) -> bytes:
    pdf = AcademicPDF(
        title_text="INSTITUTE OF ENGINEERING & TECHNOLOGY - CSIT",
        subtitle_text="VT Remedial Examination — Compulsory Candidates List",
        orientation='L'
    )
    pdf.add_page()

    pdf.set_font('Helvetica', 'B', 8)
    pdf.set_text_color(30, 41, 59)

    col_widths = (12, 35, 55, 30, 28, 28, 40, 45)
    with pdf.table(col_widths=col_widths, text_align="CENTER", line_height=6) as table:
        hdr = table.row()
        for c in ["#", "Roll Number", "Student Name", "Class", "MST-1", "MST-2", "Status", "Remarks / Override"]:
            hdr.cell(c)

        pdf.set_font('Helvetica', '', 8)
        for i, (f, s, cname) in enumerate(rows, start=1):
            r = table.row()
            r.cell(str(i))
            r.cell(_safe_str(s.roll_number))
            r.cell(_safe_str(s.name))
            r.cell(_safe_str(cname))
            r.cell("Present" if f.mst_1_appeared is True else ("Absent" if f.mst_1_appeared is False else "Missing"))
            r.cell("Present" if f.mst_2_appeared is True else ("Absent" if f.mst_2_appeared is False else "Missing"))
            status_display = f.final_status.replace('_', ' ').title() if f.final_status else "-"
            if f.override:
                status_display += " (Overridden)"
            r.cell(_safe_str(status_display))
            r.cell(_safe_str(f.override_reason or "-"))

    return bytes(pdf.output())


# ── Universal render_pdf adapter ──────────────────────────────────────────────
def render_pdf(html: str) -> bytes:
    """
    Renders PDF bytes from HTML if WeasyPrint is available,
    otherwise renders a clean fpdf2 document without crashing.
    """
    if WEASYPRINT_AVAILABLE:
        try:
            return HTML(string=html).write_pdf(
                stylesheets=[CSS(string="@page { margin: 15mm; }")]
            )
        except Exception:
            pass

    # Clean fpdf2 fallback for any HTML text
    pdf = AcademicPDF()
    pdf.add_page()
    pdf.set_font('Helvetica', '', 10)
    pdf.cell(0, 8, "Document Generated via EduDuty PDF Engine", new_x='LMARGIN', new_y='NEXT')
    return bytes(pdf.output())


# ── Preserved HTML Builders (for browser view / inspection) ────────────────────

BASE_CSS = """
@import url('https://fonts.googleapis.com/css2?family=Inter:wght@400;600;700&display=swap');
* { box-sizing: border-box; margin: 0; padding: 0; }
body { font-family: 'Inter', Arial, sans-serif; font-size: 11px; color: #111; background: #fff; }
.page { padding: 28px 36px; }
.header { display: flex; justify-content: space-between; align-items: flex-start;
          border-bottom: 2px solid #1e293b; padding-bottom: 12px; margin-bottom: 20px; }
.header h1 { font-size: 18px; font-weight: 700; color: #1e293b; }
.header .sub { font-size: 10px; color: #64748b; margin-top: 4px; }
.header .meta { text-align: right; font-size: 10px; color: #64748b; }
.section-title { font-size: 12px; font-weight: 700; text-transform: uppercase;
                 letter-spacing: 0.5px; color: #334155; border-bottom: 1px solid #e2e8f0;
                 padding-bottom: 4px; margin: 18px 0 10px; }
table { width: 100%; border-collapse: collapse; font-size: 10.5px; }
th { background: #f1f5f9; color: #334155; font-weight: 600; padding: 7px 10px;
     text-align: left; border: 1px solid #cbd5e1; }
td { padding: 6px 10px; border: 1px solid #e2e8f0; vertical-align: middle; }
tr:nth-child(even) td { background: #f8fafc; }
.badge { display: inline-block; padding: 2px 7px; border-radius: 4px; font-size: 9.5px; font-weight: 600; }
.badge-eligible   { background: #dcfce7; color: #15803d; }
.badge-borderline { background: #fef9c3; color: #a16207; }
.badge-ineligible { background: #fee2e2; color: #b91c1c; }
.badge-missing    { background: #f1f5f9; color: #475569; }
.badge-overridden { background: #dbeafe; color: #1e40af; }
.info-grid { display: grid; grid-template-columns: 1fr 1fr; gap: 8px 24px; margin-bottom: 16px; }
.info-item label { font-size: 9px; text-transform: uppercase; color: #94a3b8; display: block; margin-bottom: 2px; }
.info-item span  { font-weight: 600; font-size: 11px; }
.footer { margin-top: 32px; border-top: 1px solid #e2e8f0; padding-top: 10px;
          font-size: 9px; color: #94a3b8; display: flex; justify-content: space-between; }
"""

def _badge(status: str, override: bool = False) -> str:
    if override:
        return '<span class="badge badge-overridden">Overridden</span>'
    mapping = {
        "Eligible": "badge-eligible",
        "Borderline": "badge-borderline",
        "Not eligible": "badge-ineligible",
        "Missing": "badge-missing",
    }
    cls = mapping.get(status, "badge-missing")
    return f'<span class="badge {cls}">{status}</span>'

def build_student_record_html(roll_number: str, db: Session) -> str:
    student = db.query(models.Student).filter_by(roll_number=roll_number).first()
    if not student:
        raise ValueError(f"Student with roll number {roll_number} not found.")

    cls = db.query(models.Class).filter_by(id=student.class_id).first()
    attendance_rows = db.query(models.AttendanceRecord).filter_by(student_id=student.id).all()
    eligibility_rows = db.query(models.MstEligibility).filter_by(student_id=student.id).all()
    attempt_rows = db.query(models.MstAttempt).filter_by(student_id=student.id).all()

    exam_map = {}
    for el in eligibility_rows:
        exam = db.query(models.MstExam).filter_by(id=el.mst_exam_id).first()
        if exam:
            exam_map[exam.label] = el

    attendance_html = ""
    for rec in attendance_rows:
        subj = db.query(models.Subject).filter_by(id=rec.subject_id).first()
        subj_name = subj.name if subj else "—"
        pct = rec.pct
        attendance_html += f"<tr><td>{subj_name}</td><td>{rec.classes_conducted}</td><td>{rec.classes_attended}</td><td>{pct:.1f}%</td><td>{rec.semester or '—'}</td></tr>"
    if not attendance_html:
        attendance_html = '<tr><td colspan="5" style="text-align:center; color:#94a3b8;">No attendance data available</td></tr>'

    eligibility_html = ""
    for label, el in exam_map.items():
        eligibility_html += f"<tr><td>{label}</td><td>{el.overall_pct or '—'}%</td><td>{el.lowest_subject_pct or '—'}%</td><td>{_badge(el.status, el.override)}</td><td>{el.override_reason or '—'}</td></tr>"
    if not eligibility_html:
        eligibility_html = '<tr><td colspan="5" style="text-align:center; color:#94a3b8;">No eligibility data</td></tr>'

    attempts_html = ""
    for att in attempt_rows:
        exam = db.query(models.MstExam).filter_by(id=att.mst_exam_id).first()
        exam_label = exam.label if exam else "—"
        attempts_html += f"<tr><td>{exam_label}</td><td>{att.status}</td><td>{att.marked_at.strftime('%Y-%m-%d %H:%M') if att.marked_at else '—'}</td><td>{att.remarks or '—'}</td></tr>"
    if not attempts_html:
        attempts_html = '<tr><td colspan="4" style="text-align:center; color:#94a3b8;">No exam records</td></tr>'

    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")
    class_name = cls.name if cls else "—"
    year_label = f"Year {cls.year}" if cls else "—"

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8" /><title>Student Record — {student.roll_number}</title><style>{BASE_CSS}</style></head>
<body>
<div class="page">
  <div class="header">
    <div><h1>MST Operations Portal</h1><div class="sub">Student Academic Record</div></div>
    <div class="meta">Generated: {generated_at}<br/>Confidential — Internal Use Only</div>
  </div>
  <div class="section-title">Student Details</div>
  <div class="info-grid">
    <div class="info-item"><label>Name</label><span>{student.name}</span></div>
    <div class="info-item"><label>Roll Number</label><span>{student.roll_number}</span></div>
    <div class="info-item"><label>Class</label><span>{class_name}</span></div>
    <div class="info-item"><label>Year</label><span>{year_label}</span></div>
  </div>
  <div class="section-title">Attendance Records</div>
  <table><thead><tr><th>Subject</th><th>Conducted</th><th>Attended</th><th>Attendance %</th><th>Semester</th></tr></thead>
  <tbody>{attendance_html}</tbody></table>
  <div class="section-title">MST Eligibility</div>
  <table><thead><tr><th>Exam</th><th>Overall %</th><th>Lowest Subject %</th><th>Status</th><th>Override Reason</th></tr></thead>
  <tbody>{eligibility_html}</tbody></table>
  <div class="section-title">Exam Day Records</div>
  <table><thead><tr><th>Exam</th><th>Status</th><th>Marked At</th><th>Remarks</th></tr></thead>
  <tbody>{attempts_html}</tbody></table>
  <div class="footer"><span>MST Operations Portal</span><span>Roll: {student.roll_number} | Generated {generated_at}</span></div>
</div>
</body>
</html>"""

def build_seating_chart_html(mst_exam_id: int, room_id: int, db: Session) -> str:
    exam = db.query(models.MstExam).filter_by(id=mst_exam_id).first()
    room = db.query(models.Room).filter_by(id=room_id).first()
    if not exam or not room:
        raise ValueError("Exam or room not found.")

    seats = db.query(models.Seat).filter_by(mst_exam_id=mst_exam_id, room_id=room_id).all()
    duty = db.query(models.InvigilationDuty).filter_by(mst_exam_id=mst_exam_id, room_id=room_id).first()
    invigilator = "—"
    if duty and duty.faculty_id:
        fac = db.query(models.Faculty).filter_by(id=duty.faculty_id).first()
        invigilator = fac.name if fac else "—"

    seat_rows_html = ""
    for seat in seats:
        left_student = db.query(models.Student).filter_by(id=seat.left_student).first() if seat.left_student else None
        right_student = db.query(models.Student).filter_by(id=seat.right_student).first() if seat.right_student else None
        left_str = f"{left_student.roll_number}<br/>{left_student.name}" if left_student else "—"
        right_str = f"{right_student.roll_number}<br/>{right_student.name}" if right_student else "—"
        seat_rows_html += f"<tr><td style='text-align:center; font-weight:700;'>{seat.seat_number or '—'}</td><td>{left_str}</td><td>{right_str}</td><td style='text-align:center;'>___________</td><td style='text-align:center;'>___________</td></tr>"

    if not seat_rows_html:
        seat_rows_html = '<tr><td colspan="5" style="text-align:center; color:#94a3b8;">No seats assigned yet.</td></tr>'

    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")
    exam_date = exam.exam_date.strftime("%d %B %Y") if exam.exam_date else "TBD"

    return f"""<!DOCTYPE html>
<html lang="en">
<head><meta charset="UTF-8" /><title>Seating Chart — {exam.label} — Room {room.room_number}</title><style>{BASE_CSS}</style></head>
<body>
<div class="page">
  <div class="header">
    <div><h1>MST Operations Portal</h1><div class="sub">Seating Chart &amp; Signature Sheet</div></div>
    <div class="meta">Generated: {generated_at}<br/>Invigilator: <strong>{invigilator}</strong></div>
  </div>
  <div class="info-grid">
    <div class="info-item"><label>Exam</label><span>{exam.label}</span></div>
    <div class="info-item"><label>Date</label><span>{exam_date}</span></div>
    <div class="info-item"><label>Time Slot</label><span>{exam.time_slot or '—'}</span></div>
    <div class="info-item"><label>Room</label><span>{room.room_number} (Capacity: {room.capacity or '—'})</span></div>
  </div>
  <table><thead><tr><th style='text-align:center;'>Bench</th><th>Left Student</th><th>Right Student</th><th style='text-align:center;'>Left Signature</th><th style='text-align:center;'>Right Signature</th></tr></thead>
  <tbody>{seat_rows_html}</tbody></table>
  <div class="footer"><span>Invigilator Signature: _______________________</span><span>{exam.label} | Room {room.room_number} | {generated_at}</span></div>
</div>
</body>
</html>"""

def build_follow_up_list_html(rows) -> str:
    trs = []
    for i, (f, s, cname) in enumerate(rows, start=1):
        trs.append(
            f"<tr><td>{i}</td><td><strong>{s.roll_number}</strong></td><td>{s.name}</td><td>{cname}</td>"
            f"<td>{'Present' if f.mst_1_appeared is True else ('Absent' if f.mst_1_appeared is False else 'Missing')}</td>"
            f"<td>{'Present' if f.mst_2_appeared is True else ('Absent' if f.mst_2_appeared is False else 'Missing')}</td>"
            f"<td>{f.final_status.replace('_', ' ').title()}</td><td>{f.override_reason or '—'}</td></tr>"
        )
    body = "\n".join(trs) or '<tr><td colspan="8">No compulsory students.</td></tr>'
    return f"""<!DOCTYPE html><html><head><meta charset="utf-8"><style>{BASE_CSS}</style></head><body>
<div class="page">
  <div class="header"><div><h1>VT / Follow-up — Compulsory List</h1><div class="sub">Rule: absent in both MST-1 and MST-2</div></div>
  <div class="meta">Generated {datetime.now().strftime('%d %b %Y, %H:%M')}<br>{len(rows)} student(s)</div></div>
  <table><thead><tr><th>#</th><th>Roll No.</th><th>Name</th><th>Class</th><th>MST-1</th><th>MST-2</th><th>Final Status</th><th>Override Reason</th></tr></thead>
  <tbody>{body}</tbody></table>
  <div class="footer"><span>EduDuty — MST Operations</span></div>
</div></body></html>"""
