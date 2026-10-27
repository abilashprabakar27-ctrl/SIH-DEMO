"""Indian-name-aware identity resolution (Fellegi-Sunter style, log-likelihood weights).

Weights (each candidate pair stores the ones that applied, shown as "Why we think these match"):
  name exact token set           +6
  all tokens equivalent          +4.5   (equal after phonetic fold, or Jaro-Winkler >= 0.92)
  initial-compatible             +3     ("K." matches "Kumar"; all tokens matched)
  partial overlap                +2 per shared token
  DOB exact                      +4
  DOB day/month swapped          +1.5
  gender agree / disagree        +1 / -3
  different APAAR IDs, both set  -2
  linked by recorded transfer    -2
Score >= 9 -> D005 REVIEW flag; 6 <= score < 9 -> listed as a candidate only. Never auto-merged.
"""

from __future__ import annotations

import re
from datetime import date

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import Enrolment, IdentityCandidate, Student
from .normalize import name_tokens

REVIEW_THRESHOLD = 9.0
LIST_THRESHOLD = 6.0
JW_THRESHOLD = 0.92

_FOLDS = [("aa", "a"), ("ee", "i"), ("oo", "u"), ("th", "t"), ("dh", "d"), ("bh", "b"), ("kh", "k"),
          ("ph", "f"), ("w", "v"), ("z", "j")]


def phonetic_fold(token: str) -> str:
    t = token
    for a, b in _FOLDS:
        t = t.replace(a, b)
    t = re.sub(r"(.)\1+", r"\1", t)
    if len(t) > 1 and t.endswith("h"):
        t = t[:-1]
    return t


def jaro_winkler(s1: str, s2: str) -> float:
    if s1 == s2:
        return 1.0
    l1, l2 = len(s1), len(s2)
    if not l1 or not l2:
        return 0.0
    window = max(max(l1, l2) // 2 - 1, 0)
    m1 = [False] * l1
    m2 = [False] * l2
    matches = 0
    for i, c in enumerate(s1):
        for j in range(max(0, i - window), min(l2, i + window + 1)):
            if not m2[j] and s2[j] == c:
                m1[i] = m2[j] = True
                matches += 1
                break
    if not matches:
        return 0.0
    k = trans = 0
    for i in range(l1):
        if m1[i]:
            while not m2[k]:
                k += 1
            if s1[i] != s2[k]:
                trans += 1
            k += 1
    jaro = (matches / l1 + matches / l2 + (matches - trans / 2) / matches) / 3
    prefix = 0
    for a, b in zip(s1[:4], s2[:4], strict=False):
        if a != b:
            break
        prefix += 1
    return jaro + prefix * 0.1 * (1 - jaro)


def tokens_equivalent(a: str, b: str) -> bool:
    if len(a) == 1 or len(b) == 1:
        return a == b
    return a == b or phonetic_fold(a) == phonetic_fold(b) or jaro_winkler(a, b) >= JW_THRESHOLD


def initial_compatible(a: str, b: str) -> bool:
    return (len(a) == 1 and b.startswith(a)) or (len(b) == 1 and a.startswith(b))


def _match_tokens(ta: list[str], tb: list[str]) -> tuple[int, int]:
    """Greedy one-to-one token matching. Returns (equivalent matches, initial matches)."""
    remaining = list(tb)
    eq = ini = 0
    leftovers = []
    for t in ta:
        hit = next((u for u in remaining if tokens_equivalent(t, u)), None)
        if hit is not None:
            remaining.remove(hit)
            eq += 1
        else:
            leftovers.append(t)
    for t in leftovers:
        hit = next((u for u in remaining if initial_compatible(t, u)), None)
        if hit is not None:
            remaining.remove(hit)
            ini += 1
    return eq, ini


def swapped(d: date) -> date | None:
    if d.day > 12 or d.day == d.month:
        return None
    try:
        return date(d.year, d.day, d.month)
    except ValueError:
        return None


def score_pair(a: dict, b: dict) -> tuple[float, list[dict]]:
    """a/b: {full_name, date_of_birth, gender, apaar_id, transfer_linked?}. Returns (score, weights)."""
    weights: list[dict] = []
    ta, tb = name_tokens(a["full_name"]), name_tokens(b["full_name"])
    if sorted(ta) == sorted(tb):
        weights.append({"factor": "Same name tokens", "weight": 6.0})
    else:
        eq, ini = _match_tokens(ta, tb)
        same_count = len(ta) == len(tb)
        if same_count and eq == len(ta):
            weights.append({"factor": "All name tokens equivalent (spelling or transliteration variant)", "weight": 4.5})
        elif same_count and eq + ini == len(ta) and ini > 0:
            weights.append({"factor": "Names compatible allowing initials", "weight": 3.0})
        elif eq + ini > 0:
            shared = eq + ini
            weights.append({"factor": f"{shared} shared name token(s)", "weight": 2.0 * shared})
    if a["date_of_birth"] == b["date_of_birth"]:
        weights.append({"factor": "Same date of birth", "weight": 4.0})
    elif swapped(a["date_of_birth"]) == b["date_of_birth"]:
        weights.append({"factor": "Date of birth with day and month swapped", "weight": 1.5})
    if a.get("gender") and b.get("gender"):
        if a["gender"] == b["gender"]:
            weights.append({"factor": "Same gender", "weight": 1.0})
        else:
            weights.append({"factor": "Different gender", "weight": -3.0})
    if a.get("apaar_id") and b.get("apaar_id") and a["apaar_id"] != b["apaar_id"]:
        weights.append({"factor": "Different APAAR IDs on both records", "weight": -2.0})
    if a.get("transfer_linked") or b.get("transfer_linked"):
        weights.append({"factor": "Linked by a recorded transfer", "weight": -2.0})
    return round(sum(w["weight"] for w in weights), 2), weights


def _blocking_dobs(dob: date) -> list[date]:
    out = [dob]
    s = swapped(dob)
    if s:
        out.append(s)
    return out


def find_candidates(
    db: Session,
    full_name: str,
    dob: date,
    gender: str | None,
    apaar_id: str | None,
    exclude_student_ids: set[str] | None = None,
    institution_id: str | None = None,
) -> list[dict]:
    """Existing students that may be the same person, scored >= LIST_THRESHOLD, best first."""
    exclude = exclude_student_ids or set()
    q = select(Student).where(Student.date_of_birth.in_(_blocking_dobs(dob)))
    out = []
    for st in db.execute(q).scalars():
        if st.id in exclude:
            continue
        if apaar_id and st.apaar_id == apaar_id:
            continue  # same registry identity: handled by D004, not identity resolution
        transfer_linked = False
        if institution_id:
            transfer_linked = (
                db.execute(
                    select(Enrolment.id).where(
                        Enrolment.student_id == st.id,
                        Enrolment.status == "TRANSFERRED_OUT",
                        Enrolment.institution_id != institution_id,
                    )
                ).first()
                is not None
            )
        score, weights = score_pair(
            {"full_name": full_name, "date_of_birth": dob, "gender": gender, "apaar_id": apaar_id},
            {
                "full_name": st.full_name,
                "date_of_birth": st.date_of_birth,
                "gender": st.gender,
                "apaar_id": st.apaar_id,
                "transfer_linked": transfer_linked,
            },
        )
        if score >= LIST_THRESHOLD:
            out.append({"student_id": st.id, "score": score, "weights": weights})
    out.sort(key=lambda c: -c["score"])
    return out


def ordered_pair(a: str, b: str) -> tuple[str, str]:
    return (a, b) if a < b else (b, a)


def record_candidates(db: Session, student: Student, candidates: list[dict]) -> list[IdentityCandidate]:
    """Persist candidate pairs for a committed student. Returns pairs that are not decided DIFFERENT_PEOPLE."""
    kept = []
    for c in candidates:
        a, b = ordered_pair(student.id, c["student_id"])
        row = db.execute(
            select(IdentityCandidate).where(IdentityCandidate.student_a == a, IdentityCandidate.student_b == b)
        ).scalar_one_or_none()
        if row is None:
            row = IdentityCandidate(student_a=a, student_b=b, score=c["score"], weights=c["weights"])
            db.add(row)
            db.flush()
        elif row.decision is None:
            row.score, row.weights = c["score"], c["weights"]
        if row.decision != "DIFFERENT_PEOPLE":
            kept.append(row)
    return kept


def decided_different(db: Session, a: str, b: str) -> bool:
    x, y = ordered_pair(a, b)
    return (
        db.execute(
            select(IdentityCandidate.id).where(
                IdentityCandidate.student_a == x,
                IdentityCandidate.student_b == y,
                IdentityCandidate.decision == "DIFFERENT_PEOPLE",
            )
        ).first()
        is not None
    )


__all__ = ["find_candidates", "score_pair", "phonetic_fold", "jaro_winkler", "record_candidates"]
