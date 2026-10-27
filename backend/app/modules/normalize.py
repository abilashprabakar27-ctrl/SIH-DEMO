"""Row normalisation: header aliases, value parsing, name keys. Produces R001/R002 findings."""

from __future__ import annotations

import re
import unicodedata
from datetime import date, datetime

TEMPLATE_COLUMNS = [
    "apaar_id",
    "institution_student_id",
    "full_name",
    "date_of_birth",
    "gender",
    "nationality_status",
    "citizenship_country",
    "programme_code",
    "academic_year",
    "seat_category",
    "admission_date",
    "social_category",
    "email",
    "apaar_pending_reason",
]
OPTIONAL_COLUMNS = {"apaar_id", "citizenship_country", "social_category", "email", "apaar_pending_reason"}
REQUIRED_COLUMNS = [c for c in TEMPLATE_COLUMNS if c not in OPTIONAL_COLUMNS]

HEADER_ALIASES = {
    "apaar": "apaar_id",
    "apaar_no": "apaar_id",
    "apaar_number": "apaar_id",
    "abc_id": "apaar_id",
    "roll_no": "institution_student_id",
    "roll_number": "institution_student_id",
    "rollno": "institution_student_id",
    "student_id": "institution_student_id",
    "enrolment_no": "institution_student_id",
    "enrollment_no": "institution_student_id",
    "name": "full_name",
    "student_name": "full_name",
    "dob": "date_of_birth",
    "birth_date": "date_of_birth",
    "sex": "gender",
    "nationality": "nationality_status",
    "citizenship": "citizenship_country",
    "country": "citizenship_country",
    "programme": "programme_code",
    "program_code": "programme_code",
    "course_code": "programme_code",
    "year": "academic_year",
    "seat": "seat_category",
    "category_of_seat": "seat_category",
    "doa": "admission_date",
    "date_of_admission": "admission_date",
    "category": "social_category",
    "email_id": "email",
    "pending_reason": "apaar_pending_reason",
}

GENDERS = {"M": "M", "MALE": "M", "F": "F", "FEMALE": "F", "T": "T", "TRANSGENDER": "T", "O": "O", "OTHER": "O"}
NATIONALITY = {
    "INDIAN": "INDIAN",
    "INDIA": "INDIAN",
    "NRI": "NRI",
    "OCI": "OCI",
    "PIO": "OCI",
    "FN": "FN",
    "FOREIGN_NATIONAL": "FN",
    "FOREIGN": "FN",
}
SEAT_CATEGORIES = ("REGULAR", "NRI", "SN_FN_OCI", "SN_CIWG", "SN_TFW", "SN_OTHER")
SUPERNUMERARY = ("SN_FN_OCI", "SN_CIWG", "SN_TFW", "SN_OTHER")
PENDING_REASONS = ("FOREIGN_NATIONAL", "APPLIED_AWAITING_ID", "OTHER_DOCUMENTED")
SOCIAL_CATEGORIES = ("GEN", "EWS", "OBC", "SC", "ST")
INDIA_NAMES = {"india", "in", "ind", "bharat", "republic of india"}
EMAIL_RE = re.compile(r"^[^@\s]+@[^@\s]+\.[^@\s]+$")
YEAR_RE = re.compile(r"^(\d{4})-(\d{2})$")


def canonical_header(h: str) -> str:
    key = re.sub(r"[^a-z0-9]+", "_", str(h or "").strip().lower()).strip("_")
    return HEADER_ALIASES.get(key, key)


def name_tokens(name: str) -> list[str]:
    ascii_ = unicodedata.normalize("NFKD", name or "").encode("ascii", "ignore").decode().lower()
    return [t for t in re.split(r"[^a-z]+", ascii_) if t]


def name_key(name: str) -> str:
    """NFKD -> ASCII, lowercase, letters only, tokens sorted."""
    return " ".join(sorted(name_tokens(name)))


def is_india(country: str | None) -> bool:
    return (country or "").strip().lower() in INDIA_NAMES


def parse_date(value) -> date | None:
    if value is None or value == "":
        return None
    if isinstance(value, datetime):
        return value.date()
    if isinstance(value, date):
        return value
    s = str(value).strip()
    for fmt in ("%Y-%m-%d", "%d-%m-%Y", "%d/%m/%Y"):
        try:
            return datetime.strptime(s, fmt).date()
        except ValueError:
            continue
    # Excel sometimes yields "2026-08-01 00:00:00"
    try:
        return datetime.fromisoformat(s).date()
    except ValueError:
        return None


def valid_academic_year(value: str) -> bool:
    m = YEAR_RE.match(value or "")
    return bool(m) and (int(m.group(1)) + 1) % 100 == int(m.group(2))


def clean_cell(value) -> str:
    if value is None:
        return ""
    if isinstance(value, float) and value.is_integer():
        value = int(value)
    if isinstance(value, datetime):
        return value.date().isoformat()
    if isinstance(value, date):
        return value.isoformat()
    return str(value).strip()


def clean_apaar(value: str) -> str:
    return re.sub(r"[\s-]", "", value or "")


def finding(rule_id, severity, field, message, evidence=None, suggestion=None) -> dict:
    f = {"rule_id": rule_id, "severity": severity, "field": field, "message": message, "evidence": evidence or {}}
    if suggestion:
        f["suggestion"] = suggestion
    return f


def normalise_row(raw: dict) -> tuple[dict, dict, list[dict]]:
    """Returns (data, parsed, findings).

    data: canonical string values (what the user sees and edits).
    parsed: typed values (dates, enums) for rules; None where unparsable.
    findings: R001 / R002 findings (severity filled from catalogue later).
    """
    data = {c: "" for c in TEMPLATE_COLUMNS}
    for k, v in raw.items():
        col = canonical_header(k)
        if col in data:
            data[col] = clean_cell(v)
    findings: list[dict] = []
    parsed: dict = {}

    for col in REQUIRED_COLUMNS:
        if not data[col]:
            findings.append(
                finding("R001_REQUIRED", None, col, f"{col.replace('_', ' ').capitalize()} is required.")
            )

    def bad(col, msg):
        findings.append(finding("R002_FORMAT", None, col, msg, {"value": data[col]}))

    data["apaar_id"] = clean_apaar(data["apaar_id"])
    parsed["apaar_id"] = data["apaar_id"] or None
    data["full_name"] = re.sub(r"\s+", " ", data["full_name"])
    parsed["full_name"] = data["full_name"] or None
    parsed["name_key"] = name_key(data["full_name"])
    parsed["institution_student_id"] = data["institution_student_id"] or None
    parsed["programme_code"] = data["programme_code"].upper() or None
    data["programme_code"] = data["programme_code"].upper()

    for col in ("date_of_birth", "admission_date"):
        parsed[col] = None
        if data[col]:
            d = parse_date(data[col])
            if d is None:
                bad(col, "Use a date like 2007-05-21 (YYYY-MM-DD), 21-05-2007 or 21/05/2007.")
            else:
                parsed[col] = d
                data[col] = d.isoformat()

    parsed["gender"] = None
    if data["gender"]:
        g = GENDERS.get(data["gender"].upper())
        if g is None:
            bad("gender", "Gender must be M, F, T or O.")
        else:
            parsed["gender"] = data["gender"] = g

    parsed["nationality_status"] = None
    if data["nationality_status"]:
        key = re.sub(r"[\s-]+", "_", data["nationality_status"].upper())
        n = NATIONALITY.get(key)
        if n is None:
            bad("nationality_status", "Nationality status must be INDIAN, NRI, OCI or FN (PIO is recorded as OCI).")
        else:
            parsed["nationality_status"] = data["nationality_status"] = n

    parsed["citizenship_country"] = data["citizenship_country"] or None

    parsed["seat_category"] = None
    if data["seat_category"]:
        s = re.sub(r"[\s-]+", "_", data["seat_category"].upper())
        if s not in SEAT_CATEGORIES:
            bad("seat_category", "Seat category must be one of " + ", ".join(SEAT_CATEGORIES) + ".")
        else:
            parsed["seat_category"] = data["seat_category"] = s

    parsed["academic_year"] = None
    if data["academic_year"]:
        if not valid_academic_year(data["academic_year"]):
            bad("academic_year", "Academic year must look like 2026-27.")
        else:
            parsed["academic_year"] = data["academic_year"]

    parsed["social_category"] = None
    if data["social_category"]:
        sc = data["social_category"].upper()
        if sc not in SOCIAL_CATEGORIES:
            bad("social_category", "Social category must be one of " + ", ".join(SOCIAL_CATEGORIES) + " or blank.")
        else:
            parsed["social_category"] = data["social_category"] = sc

    parsed["email"] = None
    if data["email"]:
        if not EMAIL_RE.match(data["email"]):
            bad("email", "Email address is not valid.")
        else:
            parsed["email"] = data["email"] = data["email"].lower()

    parsed["apaar_pending_reason"] = None
    if data["apaar_pending_reason"]:
        r = re.sub(r"[\s-]+", "_", data["apaar_pending_reason"].upper())
        if r not in PENDING_REASONS:
            bad("apaar_pending_reason", "Pending reason must be one of " + ", ".join(PENDING_REASONS) + ".")
        else:
            parsed["apaar_pending_reason"] = data["apaar_pending_reason"] = r

    return data, parsed, findings
