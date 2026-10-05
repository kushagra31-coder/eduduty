"""
PDF Service — generates formal academic PDFs for student records and seating charts.
Uses WeasyPrint (HTML → PDF) for pure-Python rendering with no headless browser required.
"""

import io
from datetime import datetime
from sqlalchemy.orm import Session
from sqlalchemy import text
import models

try:
    from weasyprint import HTML, CSS
    WEASYPRINT_AVAILABLE = True
except (ImportError, OSError):
    # OSError: native Pango/GTK libs missing (common on Windows) — app still
    # boots; PDF endpoints raise a clear error instead.
    WEASYPRINT_AVAILABLE = False


# ── HTML Templates ─────────────────────────────────────────────────────────────

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
     text-align: left; border: 1px solid #e2e8f0; }
td { padding: 6px 10px; border: 1px solid #e2e8f0; vertical-align: top; }
tr:nth-child(even) td { background: #f8fafc; }

.badge { display: inline-block; padding: 2px 8px; border-radius: 12px; font-size: 9.5px; font-weight: 600; }
.badge-eligible   { background: #dcfce7; color: #166534; }
.badge-borderline { background: #fef9c3; color: #854d0e; }
.badge-ineligible { background: #fee2e2; color: #991b1b; }
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
        "Eligible":     "badge-eligible",
        "Borderline":   "badge-borderline",
        "Not eligible": "badge-ineligible",
        "Missing":      "badge-missing",
    }
    cls = mapping.get(status, "badge-missing")
    return f'<span class="badge {cls}">{status}</span>'


# ── Student Record PDF ─────────────────────────────────────────────────────────

def build_student_record_html(roll_number: str, db: Session) -> str:
    student = db.query(models.Student).filter_by(roll_number=roll_number).first()
    if not student:
        raise ValueError(f"Student with roll number {roll_number} not found.")

    cls = db.query(models.Class).filter_by(id=student.class_id).first()
    attendance_rows = db.query(models.AttendanceRecord).filter_by(student_id=student.id).all()
    eligibility_rows = db.query(models.MstEligibility).filter_by(student_id=student.id).all()
    attempt_rows = db.query(models.MstAttempt).filter_by(student_id=student.id).all()
    audit_rows = db.query(models.AuditLog).filter(
        models.AuditLog.table_name.in_(["mst_eligibility", "mst_attempts"]),
        models.AuditLog.record_id.in_([e.id for e in eligibility_rows] + [a.id for a in attempt_rows])
    ).order_by(models.AuditLog.changed_at.desc()).limit(10).all()

    # Eligibility lookup by exam
    exam_map = {}
    for el in eligibility_rows:
        exam = db.query(models.MstExam).filter_by(id=el.mst_exam_id).first()
        if exam:
            exam_map[exam.label] = el

    attendance_html = ""
    for rec in attendance_rows:
        subj = db.query(models.Subject).filter_by(id=rec.subject_id).first()
        subj_name = subj.name if subj else "—"
        pct = rec.attendance_pct or 0
        attendance_html += f"""
        <tr>
          <td>{subj_name}</td>
          <td>{rec.classes_conducted}</td>
          <td>{rec.classes_attended}</td>
          <td>{pct:.1f}%</td>
          <td>{rec.semester or '—'}</td>
        </tr>"""

    if not attendance_html:
        attendance_html = '<tr><td colspan="5" style="text-align:center; color:#94a3b8;">No attendance data available</td></tr>'

    eligibility_html = ""
    for label, el in exam_map.items():
        eligibility_html += f"""
        <tr>
          <td>{label}</td>
          <td>{el.overall_pct or '—'}%</td>
          <td>{el.lowest_subject_pct or '—'}%</td>
          <td>{_badge(el.status, el.override)}</td>
          <td>{el.override_reason or '—'}</td>
        </tr>"""

    if not eligibility_html:
        eligibility_html = '<tr><td colspan="5" style="text-align:center; color:#94a3b8;">No eligibility data</td></tr>'

    attempts_html = ""
    for att in attempt_rows:
        exam = db.query(models.MstExam).filter_by(id=att.mst_exam_id).first()
        exam_label = exam.label if exam else "—"
        attempts_html += f"""
        <tr>
          <td>{exam_label}</td>
          <td>{att.status}</td>
          <td>{att.marked_at.strftime('%Y-%m-%d %H:%M') if att.marked_at else '—'}</td>
          <td>{att.remarks or '—'}</td>
        </tr>"""

    if not attempts_html:
        attempts_html = '<tr><td colspan="4" style="text-align:center; color:#94a3b8;">No exam records</td></tr>'

    audit_html = ""
    for log in audit_rows:
        audit_html += f"""
        <tr>
          <td>{log.table_name}</td>
          <td>{log.field_changed or '—'}</td>
          <td>{log.old_value or '—'}</td>
          <td>{log.new_value or '—'}</td>
          <td>{log.reason or '—'}</td>
          <td>{log.changed_at.strftime('%Y-%m-%d %H:%M') if log.changed_at else '—'}</td>
        </tr>"""

    if not audit_html:
        audit_html = '<tr><td colspan="6" style="text-align:center; color:#94a3b8;">No audit entries</td></tr>'

    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")
    class_name = cls.name if cls else "—"
    year_label = f"Year {cls.year}" if cls else "—"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Student Record — {student.roll_number}</title>
  <style>{BASE_CSS}</style>
</head>
<body>
<div class="page">
  <div class="header">
    <div>
      <h1>MST Operations Portal</h1>
      <div class="sub">Student Academic Record</div>
    </div>
    <div class="meta">
      Generated: {generated_at}<br/>
      Confidential — Internal Use Only
    </div>
  </div>

  <div class="section-title">Student Details</div>
  <div class="info-grid">
    <div class="info-item"><label>Name</label><span>{student.name}</span></div>
    <div class="info-item"><label>Roll Number</label><span>{student.roll_number}</span></div>
    <div class="info-item"><label>Class</label><span>{class_name}</span></div>
    <div class="info-item"><label>Year</label><span>{year_label}</span></div>
    <div class="info-item"><label>Batch</label><span>{student.batch_number or '—'}</span></div>
    <div class="info-item"><label>Seat (L/R)</label><span>{student.pair_seat or '—'}</span></div>
  </div>

  <div class="section-title">Attendance Records</div>
  <table>
    <thead>
      <tr><th>Subject</th><th>Conducted</th><th>Attended</th><th>Attendance %</th><th>Semester</th></tr>
    </thead>
    <tbody>{attendance_html}</tbody>
  </table>

  <div class="section-title">MST Eligibility</div>
  <table>
    <thead>
      <tr><th>Exam</th><th>Overall %</th><th>Lowest Subject %</th><th>Status</th><th>Override Reason</th></tr>
    </thead>
    <tbody>{eligibility_html}</tbody>
  </table>

  <div class="section-title">Exam Day Records</div>
  <table>
    <thead>
      <tr><th>Exam</th><th>Status</th><th>Marked At</th><th>Remarks</th></tr>
    </thead>
    <tbody>{attempts_html}</tbody>
  </table>

  <div class="section-title">Audit Trail</div>
  <table>
    <thead>
      <tr><th>Table</th><th>Field</th><th>Old Value</th><th>New Value</th><th>Reason</th><th>Changed At</th></tr>
    </thead>
    <tbody>{audit_html}</tbody>
  </table>

  <div class="footer">
    <span>MST Operations Portal — Confidential</span>
    <span>Roll: {student.roll_number} | Generated {generated_at}</span>
  </div>
</div>
</body>
</html>"""


# ── Seating Chart PDF ──────────────────────────────────────────────────────────

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
        left_str  = f"{left_student.roll_number}<br/>{left_student.name}"  if left_student  else "—"
        right_str = f"{right_student.roll_number}<br/>{right_student.name}" if right_student else "—"
        seat_rows_html += f"""
        <tr>
          <td style="text-align:center; font-weight:700;">{seat.seat_number or '—'}</td>
          <td>{left_str}</td>
          <td style="text-align:center; color:#94a3b8; font-size:9px;">L &nbsp; R</td>
          <td>{right_str}</td>
          <td style="text-align:center;">___________</td>
          <td style="text-align:center;">___________</td>
        </tr>"""

    if not seat_rows_html:
        seat_rows_html = '<tr><td colspan="6" style="text-align:center; color:#94a3b8;">No seats assigned yet.</td></tr>'

    generated_at = datetime.now().strftime("%d %b %Y, %H:%M")
    exam_date = exam.exam_date.strftime("%d %B %Y") if exam.exam_date else "TBD"

    return f"""<!DOCTYPE html>
<html lang="en">
<head>
  <meta charset="UTF-8" />
  <title>Seating Chart — {exam.label} — Room {room.room_number}</title>
  <style>{BASE_CSS}</style>
</head>
<body>
<div class="page">
  <div class="header">
    <div>
      <h1>MST Operations Portal</h1>
      <div class="sub">Seating Chart &amp; Signature Sheet</div>
    </div>
    <div class="meta">Generated: {generated_at}<br/>Invigilator: <strong>{invigilator}</strong></div>
  </div>

  <div class="info-grid" style="margin-bottom: 20px;">
    <div class="info-item"><label>Exam</label><span>{exam.label}</span></div>
    <div class="info-item"><label>Date</label><span>{exam_date}</span></div>
    <div class="info-item"><label>Time Slot</label><span>{exam.time_slot or '—'}</span></div>
    <div class="info-item"><label>Room</label><span>{room.room_number} (Capacity: {room.capacity or '—'})</span></div>
  </div>

  <table>
    <thead>
      <tr>
        <th style="text-align:center;">Bench</th>
        <th>Left Student</th>
        <th style="text-align:center;"></th>
        <th>Right Student</th>
        <th style="text-align:center;">Left Signature</th>
        <th style="text-align:center;">Right Signature</th>
      </tr>
    </thead>
    <tbody>{seat_rows_html}</tbody>
  </table>

  <div class="footer">
    <span>Invigilator Signature: _______________________</span>
    <span>{exam.label} | Room {room.room_number} | {generated_at}</span>
  </div>
</div>
</body>
</html>"""


# ── PDF renderer ───────────────────────────────────────────────────────────────

def render_pdf(html: str) -> bytes:
    """Render HTML to PDF bytes using WeasyPrint."""
    if not WEASYPRINT_AVAILABLE:
        raise RuntimeError(
            "PDF export needs WeasyPrint's system libraries (Pango/GTK). "
            "On Windows install the GTK3 runtime, or skip PDF export."
        )
    pdf_bytes = HTML(string=html).write_pdf(
        stylesheets=[CSS(string="@page { margin: 15mm; }")]
    )
    return pdf_bytes


# ── VT / Follow-up compulsory list PDF ─────────────────────────────────────────

def _appearance_label(appeared) -> str:
    if appeared is True:
        return "Present"
    if appeared is False:
        return "Absent"
    return "Missing"


def build_follow_up_list_html(rows) -> str:
    """rows: list of (FollowUpStatus, Student, class_name) tuples."""
    trs = []
    for i, (f, s, cname) in enumerate(rows, start=1):
        trs.append(
            "<tr>"
            f"<td>{i}</td>"
            f"<td><strong>{s.roll_number}</strong></td>"
            f"<td>{s.name}</td>"
            f"<td>{cname}</td>"
            f"<td>{_appearance_label(f.mst_1_appeared)}</td>"
            f"<td>{_appearance_label(f.mst_2_appeared)}</td>"
            f"<td>{f.final_status.replace('_', ' ').title()}"
            f"{' (rule: ' + f.calculated_status.replace('_', ' ') + ')' if f.override else ''}</td>"
            f"<td>{f.override_reason or '—'}</td>"
            "</tr>"
        )
    body = "\n".join(trs) or '<tr><td colspan="8">No compulsory students.</td></tr>'
    return f"""<!DOCTYPE html>
<html><head><meta charset="utf-8">
  <style>{BASE_CSS}</style>
</head>
<body><div class="page">
<div class="header">
  <div><h1>VT / Follow-up — Compulsory List</h1>
  <div class="sub">Rule: absent in both MST-1 and MST-2 (absent-both-mst-v1)</div></div>
  <div class="meta">Generated {datetime.now().strftime('%d %b %Y, %H:%M')}<br>
  {len(rows)} student(s)</div>
</div>
<table>
  <thead><tr>
    <th>#</th><th>Roll No.</th><th>Name</th><th>Class</th>
    <th>MST-1</th><th>MST-2</th><th>Final Status</th><th>Override Reason</th>
  </tr></thead>
  <tbody>{body}</tbody>
</table>
<div class="footer">
  <span>EduDuty — MST Operations</span>
  <span>Coordinator signature: ____________________</span>
</div>
</div></body></html>"""
