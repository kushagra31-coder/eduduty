from typing import Optional
import sys
import os
sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

from fastapi import Depends, HTTPException, Header, Request, status
from sqlalchemy.orm import Session
from database import get_db
import models
from core import security


def get_current_user(
    request: Request,
    authorization: str = Header(None, alias="Authorization"),
    db: Session = Depends(get_db)
) -> models.User:
    """
    FastAPI dependency that extracts Bearer token, verifies JWT, and resolves CurrentUser.
    Rejects unauthenticated requests with HTTP 401.
    """
    token = None
    if authorization:
        parts = authorization.strip().split()
        if len(parts) == 2 and parts[0].lower() == "bearer":
            token = parts[1]
        elif len(parts) == 1:
            token = parts[0]

    # Check cookies or query params if header missing
    if not token:
        token = request.cookies.get("sb-access-token") or request.query_params.get("access_token")

    if not token:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "UNAUTHORIZED",
                    "message": "Authentication required. Bearer token missing.",
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    try:
        payload = security.verify_supabase_jwt(token)
    except ValueError as e:
        raise HTTPException(
            status_code=status.HTTP_401_UNAUTHORIZED,
            detail={
                "error": {
                    "code": "INVALID_TOKEN",
                    "message": str(e),
                }
            },
            headers={"WWW-Authenticate": "Bearer"},
        )

    user = security.get_or_create_user_from_jwt(db, payload)
    return user


def require_permission(permission: str):
    """
    FastAPI dependency factory enforcing server-side RBAC.
    Checks if current_user.role possesses the requested permission.
    Rejects unauthorized requests with HTTP 403.
    """
    def permission_dependency(current_user: models.User = Depends(get_current_user)) -> models.User:
        if not security.has_permission(current_user.role, permission):
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "FORBIDDEN",
                        "message": f"Permission '{permission}' is required for this operation. Role '{current_user.role}' is not authorized.",
                    }
                },
            )
        return current_user

    return permission_dependency


# ── Resource-Level Authorization Helpers ─────────────────────────────────────

def verify_invigilator_room_assignment(
    db: Session,
    current_user: models.User,
    mst_exam_id: int,
    room_id: Optional[int] = None,
    student_id: Optional[int] = None,
) -> None:
    """
    Enforce resource-level authorization: Invigilators and Faculty can only operate on
    examination rooms to which they are explicitly assigned in invigilation_duties.
    Administrative roles (SUPER_ADMIN, ADMIN, EXAM_COORDINATOR) retain global access.
    """
    if current_user.role in (security.SUPER_ADMIN, security.ADMIN, security.EXAM_COORDINATOR):
        return

    if not current_user.faculty_id:
        raise HTTPException(
            status_code=status.HTTP_403_FORBIDDEN,
            detail={
                "error": {
                    "code": "FORBIDDEN",
                    "message": "Access denied: User is not linked to an active faculty record.",
                }
            },
        )

    # Resolve room_id from student's seat assignment if room_id is not explicitly provided
    target_room_id = room_id
    if target_room_id is None and student_id is not None:
        seat = db.query(models.Seat).filter(
            models.Seat.mst_exam_id == mst_exam_id,
            (models.Seat.left_student == student_id) | (models.Seat.right_student == student_id)
        ).first()
        if seat:
            target_room_id = seat.room_id
        else:
            attempt = db.query(models.MstAttempt).filter_by(mst_exam_id=mst_exam_id, student_id=student_id).first()
            if attempt and attempt.room_id:
                target_room_id = attempt.room_id

    if target_room_id is not None:
        duty = db.query(models.InvigilationDuty).filter_by(
            mst_exam_id=mst_exam_id,
            room_id=target_room_id,
            faculty_id=current_user.faculty_id,
            status="Assigned"
        ).first()
        if not duty:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "FORBIDDEN",
                        "message": f"Access denied: You are not assigned to invigilate room {target_room_id} for examination {mst_exam_id}.",
                    }
                },
            )
    else:
        # No specific room identified; check if invigilator is assigned to ANY room for this exam
        duty = db.query(models.InvigilationDuty).filter_by(
            mst_exam_id=mst_exam_id,
            faculty_id=current_user.faculty_id,
            status="Assigned"
        ).first()
        if not duty:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "FORBIDDEN",
                        "message": f"Access denied: You are not assigned to invigilate any room for examination {mst_exam_id}.",
                    }
                },
            )


def verify_faculty_student_access(
    db: Session,
    current_user: models.User,
    student_id: int
) -> models.Student:
    """
    Enforce IDOR protection: Faculty members can only access student records if the student
    is enrolled in a class taught by the faculty member or has attendance records under them.
    Administrative roles retain global access.
    """
    student = db.query(models.Student).filter_by(id=student_id).first()
    if not student:
        raise HTTPException(
            status_code=status.HTTP_404_NOT_FOUND,
            detail={"error": {"code": "NOT_FOUND", "message": f"Student ID {student_id} not found."}}
        )

    if current_user.role in (security.SUPER_ADMIN, security.ADMIN, security.EXAM_COORDINATOR):
        return student

    if current_user.role == security.FACULTY:
        if not current_user.faculty_id:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={"error": {"code": "FORBIDDEN", "message": "Access denied: User is not linked to a faculty record."}}
            )

        teaches_class = db.query(models.FacultyTimetable).filter_by(
            faculty_id=current_user.faculty_id,
            class_id=student.class_id
        ).first()

        has_attendance = db.query(models.AttendanceRecord).filter_by(
            faculty_id=current_user.faculty_id,
            student_id=student.id
        ).first()

        if not teaches_class and not has_attendance:
            raise HTTPException(
                status_code=status.HTTP_403_FORBIDDEN,
                detail={
                    "error": {
                        "code": "FORBIDDEN",
                        "message": f"Access denied: Student record {student.roll_number} is outside your assigned academic class scope.",
                    }
                },
            )

    return student

