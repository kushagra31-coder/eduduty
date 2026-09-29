"""Seed the faculty timetable from the official Jul-Dec 2026 sheets.

Reads timetable_seed.json (classes, faculty legend, subjects) and
timetable_entries.json (day x period cells transcribed from the 5 jpeg sheets).

Idempotent: for each class+semester it removes previously seeded timetable rows,
deactivates old versions, then inserts a fresh active version.

Usage:  cd backend && python seed_timetable.py
"""
import json
import os
import re
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))

from database import SessionLocal, engine  # noqa: E402
import models  # noqa: E402

models.Base.metadata.create_all(bind=engine)

HERE = os.path.dirname(os.path.abspath(__file__))


from difflib import SequenceMatcher


def canon_tokens(n) -> set:
    n = (n or "").lower()
    n = re.sub(r"^(prof\.?|dr\.?)\s*", "", n).strip()
    for a, b in (("shweta", "sweta"), ("aarti", "arti"),
                 ("shrivastava", "shrivastva"), ("anajana", "anjana")):
        n = n.replace(a, b)
    return set(re.sub(r"[^a-z ]", " ", n).split())


def tok_sim(a: str, b: str) -> float:
    return max(SequenceMatcher(None, a, b).ratio(),
               SequenceMatcher(None, b, a).ratio())


def same_person(a, b) -> bool:
    ta, tb = canon_tokens(a), canon_tokens(b)
    if not ta or not tb:
        return False
    small, large = (ta, tb) if len(ta) <= len(tb) else (tb, ta)
    used = set()
    for t in small:
        best, bj = 0.0, -1
        for j, u in enumerate(large):
            if j in used:
                continue
            r = tok_sim(t, u)
            if r > best:
                best, bj = r, j
        if best < 0.78:
            return False
        used.add(bj)
    return True


def get_or_create_class(db, name, branch, year):
    c = db.query(models.Class).filter(models.Class.name == name).first()
    if not c:
        c = models.Class(name=name, branch=branch, year=year)
        db.add(c)
        db.commit()
        db.refresh(c)
    return c


def get_or_create_faculty(db, abbr, full_name):
    full_name = normalize_faculty_name(full_name)
    # exact abbreviation + same person -> reuse
    for f in db.query(models.Faculty).filter(models.Faculty.abbreviation == abbr).all():
        if same_person(f.name, full_name):
            return f
    # same person under a missing/different abbreviation -> reuse, fill abbreviation
    for f in db.query(models.Faculty).all():
        if same_person(f.name, full_name):
            if not f.abbreviation:
                f.abbreviation = abbr
                db.commit()
            return f
    print(f"  + faculty {abbr}: {full_name}")
    f = models.Faculty(name=full_name[:100], abbreviation=abbr)
    db.add(f)
    db.commit()
    db.refresh(f)
    return f


def fix_name_word(w: str) -> str:
    if w.isupper() and len(w) > 1:
        return w.title()
    if re.match(r"^[a-z][A-Z]+$", w):
        return w.title()
    return w


def normalize_faculty_name(n: str) -> str:
    n = re.sub(r"^(prof|dr)\.([A-Za-z])", r"\1. \2", (n or "").strip(), flags=re.IGNORECASE)
    parts = n.split(" ", 1)
    head, rest = parts[0], (parts[1] if len(parts) > 1 else "")
    rest = " ".join(fix_name_word(w) for w in rest.split())
    return (head + " " + rest).strip()[:100]


def get_or_create_subject(db, code, name):
    s = db.query(models.Subject).filter(models.Subject.code == code).first()
    if not s:
        s = models.Subject(code=code[:20], name=(name or code).strip()[:100])
        db.add(s)
        db.commit()
        db.refresh(s)
    return s


def to_min(t: str) -> int:
    h, m = t.split(":")
    return int(h) * 60 + int(m)


def main():
    seed = json.load(open(os.path.join(HERE, "timetable_seed.json")))
    entries = json.load(open(os.path.join(HERE, "timetable_entries.json")))
    periods = seed["periods"]
    classes = {c["class"]: c for c in seed["classes"]}

    db = SessionLocal()
    try:
        # resolve classes / faculty / subjects first
        cls_map, fac_map, subj_map = {}, {}, {}
        for cname, c in classes.items():
            cls = get_or_create_class(db, cname, c["branch"], c["year"])
            cls_map[cname] = cls
            fac_map[cname] = {a: get_or_create_faculty(db, a, n)
                              for a, n in c["faculty"].items()}
            subj_map[cname] = {code: get_or_create_subject(db, code, name)
                               for code, name in c["subjects"].items()}

        # wipe previous rows for these class+semester pairs (idempotent re-seed)
        for cname, c in classes.items():
            cls = cls_map[cname]
            n = db.query(models.FacultyTimetable).filter(
                models.FacultyTimetable.class_id == cls.id,
                models.FacultyTimetable.semester == c["semester"]).delete()
            db.query(models.TimetableVersion).filter(
                models.TimetableVersion.class_id == cls.id,
                models.TimetableVersion.semester == c["semester"]).update(
                    {"active": False})
            if n:
                print(f"  cleared {n} old rows for {cname}")
        db.commit()

        total = 0
        for cname, c in classes.items():
            cls = cls_map[cname]
            ver = models.TimetableVersion(
                class_id=cls.id, semester=c["semester"],
                session="Jul-Dec 2026", doc_no=c["sheet"], active=True)
            db.add(ver)
            db.commit()
            db.refresh(ver)
            for e in entries:
                if e["class"] != cname:
                    continue
                for p in e["periods"]:
                    start, end = periods[p]
                    for g in e["groups"]:
                        subj = subj_map[cname][g["subject"]]
                        for abbr in g["faculty"]:
                            db.add(models.FacultyTimetable(
                                faculty_id=fac_map[cname][abbr].id,
                                day_of_week=e["day"],
                                period_start=start, period_end=end,
                                subject_code=subj.code,
                                subject_name=subj.name,
                                room=g.get("room") or "",
                                batch=g.get("batch"),
                                class_id=cls.id, year=c["year"],
                                semester=c["semester"],
                                timetable_version_id=ver.id))
                            total += 1
            db.commit()
            print(f"  seeded {cname} (version {ver.id})")

        # self-check: no faculty double-booked in the same day/period
        print("checking for double-booked faculty...")
        clashes = 0
        rows = db.query(models.FacultyTimetable).all()
        seen = {}
        for r in rows:
            key = (r.faculty_id, r.day_of_week, r.period_start)
            if key in seen:
                other = seen[key]
                fname = db.query(models.Faculty).filter_by(id=r.faculty_id).first().name
                print(f"  CLASH: {fname} {r.day_of_week} {r.period_start}: "
                      f"{other.subject_code} vs {r.subject_code}")
                clashes += 1
            else:
                seen[key] = r
        # overlap check across different period labels (safety net)
        by_fac_day = {}
        for r in rows:
            by_fac_day.setdefault((r.faculty_id, r.day_of_week), []).append(r)
        for (fid, day), rs in by_fac_day.items():
            rs.sort(key=lambda r: to_min(r.period_start))
            for a, b in zip(rs, rs[1:]):
                if to_min(b.period_start) < to_min(a.period_end) and a.id != b.id:
                    fname = db.query(models.Faculty).filter_by(id=fid).first().name
                    print(f"  OVERLAP: {fname} {day} "
                          f"{a.period_start}-{a.period_end} ({a.subject_code}) vs "
                          f"{b.period_start}-{b.period_end} ({b.subject_code})")
                    clashes += 1
        print(f"done: {total} timetable rows, {clashes} clashes")
    finally:
        db.close()


if __name__ == "__main__":
    main()
