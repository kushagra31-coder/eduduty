"""
Seed duty exemptions for exactly three senior faculty members (D3):
- Dr. Shilpa Bhalerao (HOD) - abbreviation SHB
- Dr. Praveen Gupta - abbreviation PG
- Dr. Vandana Kate - abbreviation VK
"""
import os
import sys
from sqlalchemy.orm import Session

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import models
from database import SessionLocal

EXEMPT_TARGETS = [
    {"abbreviation": "SHB", "full_name": "Dr. Shilpa Bhalerao"},
    {"abbreviation": "PG", "full_name": "Dr. Praveen Gupta"},
    {"abbreviation": "VK", "full_name": "Dr. Vandana Kate"},
]

EXEMPT_REASON = "Senior faculty, excluded by department"


def apply_d3_exemptions(db: Session) -> list[models.Faculty]:
    """
    Match exactly the three faculty members by abbreviation or full name,
    print their details, verify each matches exactly once, and seed their exemptions.
    """
    matched_faculty = []
    for target in EXEMPT_TARGETS:
        abbr = target["abbreviation"]
        name = target["full_name"]

        # Match by faculty.abbreviation. If not populated yet, match by exact full name.
        # No fuzzy matching.
        matches = db.query(models.Faculty).filter(models.Faculty.abbreviation == abbr).all()
        if not matches:
            matches = db.query(models.Faculty).filter(models.Faculty.name == name).all()

        if len(matches) != 1:
            raise RuntimeError(
                f"D3 exemption match failure: target '{abbr}' ('{name}') matched {len(matches)} times (expected exactly 1). Stopping."
            )

        f = matches[0]
        print(f"D3 matched row: id={f.id}, name='{f.name}', abbreviation='{f.abbreviation}'")
        matched_faculty.append(f)

    # All three matched exactly once -> update records
    for f in matched_faculty:
        f.exempt_from_duty = True
        f.exempt_reason = EXEMPT_REASON

    db.commit()
    for f in matched_faculty:
        db.refresh(f)

    return matched_faculty


def main():
    db = SessionLocal()
    try:
        updated = apply_d3_exemptions(db)
        print(f"Successfully seeded duty exemptions for {len(updated)} faculty members.")
    finally:
        db.close()


if __name__ == "__main__":
    main()
