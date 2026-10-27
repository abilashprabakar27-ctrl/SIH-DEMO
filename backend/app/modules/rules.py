"""The validation rule catalogue (stable IDs). Seeded into validation_rules; AICTE can toggle
enabled/severity except for locked rules."""

from __future__ import annotations

from dataclasses import dataclass

from sqlalchemy import select
from sqlalchemy.orm import Session

from ..models import ValidationRule

LOCKED = {"R001_REQUIRED", "R002_FORMAT", "D002_ROLL_CONFLICT", "F001_DUP_APAAR_IN_FILE", "F002_DUP_ROLL_IN_FILE"}

# rule_id, severity, stage, title, description, remediation
CATALOGUE = [
    ("R001_REQUIRED", "ERROR", "ROW", "Required value missing",
     "A required column is empty. Required: everything except apaar_id, citizenship_country, social_category, email, apaar_pending_reason.",
     "Fill in the highlighted field."),
    ("R002_FORMAT", "ERROR", "ROW", "Value in wrong format",
     "A date, code list value, email or academic year is not in an accepted format.",
     "Use the format shown in the message; the Excel template has drop-down lists."),
    ("R003_APAAR_MISSING", "ERROR", "ROW", "APAAR ID missing without a reason",
     "No APAAR ID and no documented pending reason.",
     "Enter the student's 12-digit APAAR ID, or choose a pending reason (FOREIGN_NATIONAL, APPLIED_AWAITING_ID, OTHER_DOCUMENTED)."),
    ("R004_APAAR_PENDING", "REVIEW", "ROW", "APAAR ID pending with a documented reason",
     "No APAAR ID; a pending reason was given. Accepted and flagged for follow-up.",
     "Add the APAAR ID once it is issued; the record will be updated, not duplicated."),
    ("R005_APAAR_FORMAT", "ERROR", "ROW", "APAAR ID not well formed",
     "APAAR ID must be exactly 12 digits and not one repeated digit. No checksum is assumed.",
     "Check the ID against the student's APAAR card or DigiLocker."),
    ("R006_APAAR_NOT_FOUND", "ERROR", "ADAPTER", "APAAR ID not found in registry (SIMULATED)",
     "The APAAR registry adapter (SIMULATED) reports the ID as not found or inactive.",
     "Re-check the ID; if a 'did you mean' suggestion is shown, confirm it with the student before using it."),
    ("R007_APAAR_MISMATCH", "REVIEW", "ADAPTER", "Name or date of birth differs from registry (SIMULATED)",
     "The registry (SIMULATED) holds a different name or date of birth for this APAAR ID.",
     "Check the spelling against the student's APAAR record; correct whichever side is wrong."),
    ("R008_APAAR_UNVERIFIED", "WARNING", "ADAPTER", "Registry unavailable; APAAR not verified",
     "The registry adapter was unavailable. The record is stored as UNVERIFIED and re-checked later.",
     "No action needed now; the ID will be re-verified."),
    ("R009_DUPLICATE_ENROLMENT", "ERROR", "REPOSITORY", "Student already enrolled in this programme-year",
     "The same student already has an enrolment in this programme and year under a different roll number.",
     "Use the existing roll number, or correct the programme or year."),
    ("R010_DATE_LOGIC", "ERROR", "ROW", "Impossible date",
     "Date of birth or admission date is in the future, or age at admission is under 15.",
     "Correct the date; check day and month order."),
    ("R011_DATE_UNUSUAL", "WARNING", "ROW", "Unusual date",
     "Age at admission over 45, or admission date outside 1 May (start year) to 31 March (next year).",
     "Confirm the date is right; no change is needed if it is."),
    ("R012_PROGRAMME", "ERROR", "ROW", "Programme not approved for this institution and year",
     "Programme code does not belong to this institution or has no approved intake for the year.",
     "Use one of your approved programme codes (see the template drop-down)."),
    ("R013_CATEGORY_CONSISTENCY", "ERROR", "ROW", "Seat category inconsistent with nationality",
     "SN_FN_OCI needs FN/OCI; NRI seat needs NRI; SN_CIWG needs INDIAN/NRI; FN needs non-India citizenship; INDIAN/NRI cannot have non-India citizenship; FOREIGN_NATIONAL pending reason only for FN/OCI.",
     "Correct the seat category or the nationality status."),
    ("R014_YEAR_MISMATCH", "ERROR", "ROW", "Academic year differs from upload year",
     "The row's academic year is not the year chosen for this upload.",
     "Change the row's year or upload it under the right year."),
    ("F001_DUP_APAAR_IN_FILE", "ERROR", "FILE", "Same APAAR ID on more than one row",
     "The APAAR ID appears on several rows of this file.",
     "Keep one row for the student and leave out the others."),
    ("F002_DUP_ROLL_IN_FILE", "ERROR", "FILE", "Same roll number on more than one row",
     "The institution student ID appears on several rows of this file.",
     "Give each student a distinct roll number or leave out the duplicate row."),
    ("F003_POSSIBLE_DUP_IN_FILE", "WARNING", "FILE", "Possible duplicate person in file",
     "Two rows share name and date of birth but have different APAAR IDs.",
     "Check whether these rows describe the same person."),
    ("F004_REPEATED_FILE", "WARNING", "FILE", "File uploaded before",
     "An identical file (same SHA-256) was uploaded before by this institution.",
     "Make sure you meant to upload it again; re-committing updates records, it does not duplicate them."),
    ("D001_EXISTING_RECORD", "WARNING", "REPOSITORY", "Will update an existing record",
     "This row matches an existing enrolment; committing updates it and keeps the history.",
     "No action needed if the update is intended."),
    ("D002_ROLL_CONFLICT", "ERROR", "REPOSITORY", "Roll number belongs to another student",
     "The roll number is already used by a different student at this institution.",
     "Check the roll number; each student keeps one roll number."),
    ("D003_XINST_ACTIVE", "REVIEW", "REPOSITORY", "Active enrolment at another institution",
     "This APAAR ID has an active or provisional enrolment at another AICTE-approved institution.",
     "Confirm the admission; if the student has left the other institution, that institution records the transfer."),
    ("D004_ATTR_CONFLICT", "REVIEW", "REPOSITORY", "Different name or date of birth on file",
     "The register already holds this APAAR ID with a different name or date of birth. The master record is not overwritten.",
     "Check which spelling is right; raise a correction if the master record is wrong."),
    ("D005_POSSIBLE_DUP_IDENTITY", "REVIEW", "REPOSITORY", "Possible same person under another ID",
     "Identity resolution found an existing student who is probably the same person but has a different or no APAAR ID.",
     "A reviewer compares the two records and decides; nothing is merged automatically."),
    ("C001_EXCESS_INTAKE", "REVIEW", "AGGREGATE", "Enrolment over approved intake",
     "Within-intake enrolments (REGULAR + NRI) exceed the approved intake for the programme-year.",
     "Check admissions; cancel duplicates or explain. Records are accepted and AICTE is flagged."),
    ("C002_SUPERNUMERARY_CAP", "REVIEW", "AGGREGATE", "Supernumerary category over its cap",
     "A supernumerary category has more enrolments than its cap. Unused seats in other categories are not transferable.",
     "Check the seat category of each admission in this category."),
]


@dataclass
class RuleConfig:
    severity: str
    enabled: bool


def seed_rules(db: Session) -> None:
    existing = {r.rule_id for r in db.execute(select(ValidationRule)).scalars()}
    for rule_id, sev, stage, title, desc, rem in CATALOGUE:
        if rule_id in existing:
            continue
        db.add(
            ValidationRule(
                rule_id=rule_id,
                title=title,
                description=desc,
                severity=sev,
                stage=stage,
                enabled=True,
                remediation=rem,
                locked=rule_id in LOCKED,
            )
        )
    db.flush()


def load_config(db: Session) -> dict[str, RuleConfig]:
    cfg = {r.rule_id: RuleConfig(r.severity, r.enabled) for r in db.execute(select(ValidationRule)).scalars()}
    for rule_id, sev, *_ in CATALOGUE:
        cfg.setdefault(rule_id, RuleConfig(sev, True))
    return cfg


def remediation_for(rule_id: str) -> str:
    for rid, _sev, _stage, _t, _d, rem in CATALOGUE:
        if rid == rule_id:
            return rem
    return ""


def title_for(rule_id: str) -> str:
    for rid, _sev, _stage, title, *_ in CATALOGUE:
        if rid == rule_id:
            return title
    return rule_id
