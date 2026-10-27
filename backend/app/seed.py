"""Deterministic synthetic seed: `python -m app.seed --reset`.

Everything is synthetic. Seed rows are loaded through the same validation engine and import
path as real uploads, so seeded flags, revisions and audit events are genuine.
"""

from __future__ import annotations

import argparse
import csv
import io
import random
from datetime import UTC, date, datetime, timedelta

from openpyxl import Workbook
from sqlalchemy import select

from .config import REPO_ROOT, settings
from .db import Base, SessionLocal, engine, utcnow
from .models import (
    ApprovedIntake,
    Enrolment,
    Institution,
    IntegrationClient,
    Programme,
    SimApaarRegistry,
    Student,
    User,
)
from .modules import credentials, intake, ledger
from .modules.identity import phonetic_fold, swapped
from .modules.normalize import TEMPLATE_COLUMNS, name_tokens
from .modules.rules import seed_rules
from .security import actor_from_user, hash_api_key, hash_password, new_api_key

PASSWORD = "Demo@2026"
SAMPLE_DIR = REPO_ROOT / "sample_data"

INSTITUTIONS = [
    # code, short, prefix, name, state, region, type
    ("SYN-1-0001", "kaveri", "KIT", "Kaveri Institute of Technology (Synthetic)", "Tamil Nadu", "South", "ENGINEERING"),
    ("SYN-1-0002", "godavari", "GEC", "Godavari Engineering College (Synthetic)", "Telangana", "South", "ENGINEERING"),
    ("SYN-1-0003", "narmada", "NSM", "Narmada School of Management (Synthetic)", "Maharashtra", "West", "MANAGEMENT"),
    ("SYN-1-0004", "yamuna", "YIM", "Yamuna Institute of Management – PGDM (Synthetic)", "Delhi", "North", "PGDM"),
    ("SYN-1-0005", "brahmaputra", "BPE", "Brahmaputra Polytechnic & Engineering (Synthetic)", "Karnataka", "South-West",
     "ENGINEERING"),
]
# short -> [(code, name, level, discipline, intake, regular 2026-27, regular 2025-26)]
PROGRAMMES = {
    "kaveri": [("BTECH-CSE", "B.Tech Computer Science and Engineering", "UG", "ENGINEERING", 60, 50, 50),
               ("BTECH-ECE", "B.Tech Electronics and Communication Engineering", "UG", "ENGINEERING", 60, 54, 55),
               ("MTECH-CSE", "M.Tech Computer Science and Engineering", "PG", "ENGINEERING", 18, 12, 15),
               ("MBA", "Master of Business Administration", "PG", "MANAGEMENT", 60, 41, 50)],
    "godavari": [("BTECH-CSE", "B.Tech Computer Science and Engineering", "UG", "ENGINEERING", 120, 115, 118),
                 ("BTECH-ME", "B.Tech Mechanical Engineering", "UG", "ENGINEERING", 60, 38, 45)],
    "narmada": [("MBA", "Master of Business Administration", "PG", "MANAGEMENT", 60, 64, 40),
                ("MCA", "Master of Computer Applications", "PG", "COMPUTER_APPLICATIONS", 60, 57, 55)],
    "yamuna": [("PGDM", "Post Graduate Diploma in Management", "PG", "MANAGEMENT", 120, 112, 110),
               ("PGDM-BA", "PGDM (Business Analytics)", "PG", "MANAGEMENT", 60, 58, 0)],
    "brahmaputra": [("DIP-ME", "Diploma in Mechanical Engineering", "DIPLOMA", "ENGINEERING", 60, 36, 48),
                    ("BTECH-CIVIL", "B.Tech Civil Engineering", "UG", "ENGINEERING", 60, 33, 41)],
}
NEW_IN_2026 = {("yamuna", "PGDM-BA")}

FIRST_F = ["Aarthi", "Bhavana", "Chitra", "Deepa", "Gayathri", "Hema", "Indu", "Janani", "Kavya", "Lakshmi", "Madhu",
           "Nithya", "Padma", "Revathi", "Sowmya", "Tara", "Uma", "Vaishnavi", "Yamini", "Anjali", "Brinda", "Charulata",
           "Dharini", "Esha", "Fathima", "Geetha", "Ishita", "Jyothi", "Keerthana", "Lavanya", "Mythili", "Neha",
           "Oviya", "Pooja", "Radhika", "Shruti", "Tanvi", "Usha", "Varsha", "Zoya", "Aditi", "Bhumika", "Diya",
           "Heena", "Kritika", "Mansi", "Nikita", "Priyanka", "Rashmi", "Sakshi", "Swathi", "Trisha", "Vidya"]
FIRST_M = ["Abhishek", "Bharath", "Chandan", "Dinesh", "Ganesh", "Harish", "Imran", "Jagan", "Kiran", "Lokesh",
           "Manoj", "Naveen", "Omkar", "Prasanna", "Raghav", "Sandeep", "Tarun", "Uday", "Varun", "Yash", "Ajay",
           "Balaji", "Chetan", "Deepak", "Eshwar", "Farhan", "Gautam", "Hemanth", "Ishaan", "Jayant", "Kunal",
           "Mahesh", "Nikhil", "Pranav", "Rohit", "Siddharth", "Tejas", "Vikram", "Vivek", "Yogesh", "Aakash",
           "Bhuvan", "Darshan", "Girish", "Hrithik", "Karthikeyan", "Mukund", "Nitin", "Prakash", "Rajesh",
           "Sharan", "Sunil", "Vinay"]
SURNAMES = ["Reddy", "Nair", "Menon", "Pillai", "Rao", "Sharma", "Verma", "Gupta", "Joshi", "Kulkarni", "Patil",
            "Deshpande", "Iyer", "Chatterjee", "Banerjee", "Das", "Bose", "Mukherjee", "Singh", "Yadav", "Chauhan",
            "Thakur", "Mishra", "Pandey", "Tiwari", "Agarwal", "Bhat", "Hegde", "Shetty", "Gowda", "Naidu",
            "Choudhary", "Saxena", "Kapoor", "Malhotra", "Mehra", "Khanna", "Sinha", "Jha", "Dubey", "Kumar",
            "Prabhu", "Kamath", "Shenoy", "Varghese", "Thomas", "Fernandes", "D'Souza", "Ansari", "Qureshi",
            "Siddiqui", "Khan", "Mathew", "Kurian", "Bhatt", "Trivedi", "Desai", "Shah", "Parikh", "Kaur"]
FOREIGN = [("Linh", "Tran", "Vietnam"), ("Amara", "Okafor", "Nigeria"), ("Bilal", "Rahimi", "Afghanistan"),
           ("Sanduni", "Perera", "Sri Lanka"), ("Tenzin", "Dorji", "Bhutan"), ("Kaveh", "Rostami", "Iran"),
           ("Nimal", "Fernando", "Sri Lanka"), ("Aiko", "Tanaka", "Japan"), ("Mohamed", "Abdi", "Kenya"),
           ("Sabin", "Thapa", "Nepal"), ("Farida", "Karimova", "Uzbekistan"), ("Joseph", "Mwangi", "Kenya"),
           ("Chen", "Wei", "Singapore"), ("Hana", "Yusuf", "Ethiopia")]
OCI_COUNTRIES = ["United States", "United Kingdom", "Canada", "Australia", "Singapore"]


class Gen:
    """Deterministic synthetic people; avoids accidental identity look-alikes (same DOB + shared name token)."""

    def __init__(self, rng: random.Random):
        self.rng = rng
        self.by_dob: dict[date, list[set[str]]] = {}
        self.serial: dict[str, int] = {}

    def reserve(self, name: str, dob: date) -> None:
        self.by_dob.setdefault(dob, []).append({phonetic_fold(t) for t in name_tokens(name)})

    def clashes(self, name: str, dob: date) -> bool:
        toks = {phonetic_fold(t) for t in name_tokens(name)}
        for d in (dob, swapped(dob)):
            if d is None:
                continue
            for other in self.by_dob.get(d, []):
                if toks & other:
                    return True
        return False

    def person(self, birth_year_range: tuple[int, int], gender: str | None = None, name: str | None = None):
        while True:
            g = gender or self.rng.choice("MF")
            n = name or f"{self.rng.choice(FIRST_M if g == 'M' else FIRST_F)} {self.rng.choice(SURNAMES)}"
            y = self.rng.randint(*birth_year_range)
            dob = date(y, self.rng.randint(1, 12), self.rng.randint(1, 28))
            if not self.clashes(n, dob):
                self.reserve(n, dob)
                return n, dob, g

    def apaar(self, inst_index: int, year: str) -> str:
        key = f"{inst_index}{year[3]}"
        self.serial[key] = self.serial.get(key, 0) + 1
        return f"9{inst_index}{year[3]}{self.serial[key]:09d}"


def _row(**kw) -> dict:
    r = {c: "" for c in TEMPLATE_COLUMNS}
    r.update({k: (v.isoformat() if isinstance(v, date) else str(v)) for k, v in kw.items() if v is not None})
    return r


def _csv_bytes(rows: list[dict]) -> bytes:
    buf = io.StringIO()
    w = csv.DictWriter(buf, fieldnames=TEMPLATE_COLUMNS)
    w.writeheader()
    w.writerows(rows)
    return buf.getvalue().encode()


def _birth_years(level: str, year: str) -> tuple[int, int]:
    start = int(year[:4])
    if level == "DIPLOMA":
        return start - 17, start - 16
    if level == "UG":
        return start - 19, start - 18
    return start - 26, start - 22


def _adm_date(rng: random.Random, year: str) -> date:
    start = int(year[:4])
    return date(start, 7, 15) + timedelta(days=rng.randint(0, 70))


DEMO_A_PEOPLE = [
    # registry id suffix, name in registry, dob, gender
    ("01", "Meenakshi Sundaram", date(2008, 5, 12), "F"),
    ("02", "Karthik Narayanan", date(2008, 1, 23), "M"),
    ("03", "Divya Lakshmi", date(2008, 7, 30), "F"),
    ("04", "Rohan Mehta", date(2007, 11, 2), "M"),
    ("05", "Sophie Laurent", date(2003, 4, 17), "F"),
    ("06", "Arun Prakash", date(2008, 2, 9), "M"),
    ("07", "Nandini Raghavan", date(2008, 9, 14), "F"),
    ("08", "Sanjana Balaji", date(2008, 6, 5), "F"),
    ("09", "Vignesh Subramanian", date(2008, 3, 27), "M"),
    ("10", "Harini Gopal", date(2008, 6, 18), "F"),
    ("11", "Riya Krishnan", date(2008, 12, 1), "F"),
    ("12", "Rakesh Iyengar", date(2008, 4, 4), "M"),
    ("13", "Aishwarya Ramesh", date(2002, 10, 10), "F"),
    ("14", "Pavithra Senthil", date(2008, 8, 8), "F"),
]
DEMO_B_PEOPLE = [
    ("01", "Sravani Kotha", date(2008, 2, 14), "F"),
    ("02", "Venkat Rayudu", date(2007, 12, 30), "M"),
    ("03", "Harsha Vardhan", date(2008, 5, 5), "M"),
    ("04", "Mounika Reddy", date(2008, 1, 19), "F"),
]


def demo_a_rows() -> list[dict]:
    p = {s: (n, d, g) for s, n, d, g in DEMO_A_PEOPLE}

    def r(roll, sfx, prog, seat="REGULAR", apaar=None, name=None, dob=None, gender=None, nat="INDIAN",
          country="India", reason=None):
        n, d, g = p[sfx] if sfx else (None, None, None)
        return _row(apaar_id=apaar if apaar is not None else f"9111000000{sfx}", institution_student_id=roll,
                    full_name=name or n, date_of_birth=dob or d, gender=gender or g, nationality_status=nat,
                    citizenship_country=country, programme_code=prog, academic_year="2026-27", seat_category=seat,
                    admission_date=date(2026, 8, 3), email=None, apaar_pending_reason=reason)

    return [
        r("KIT26CSE901", "01", "BTECH-CSE"),
        r("KIT26CSE902", "02", "BTECH-CSE"),
        r("KIT26ECE903", "03", "BTECH-ECE"),
        r("KIT26CSE904", "04", "BTECH-CSE", seat="NRI", nat="NRI"),
        r("KIT26MBA905", "05", "MBA", seat="SN_FN_OCI", nat="OCI", country="France"),
        r("KIT26CSE906", "06", "BTECH-CSE", apaar=""),  # missing APAAR, no reason
        r("KIT26ECE907", "07", "BTECH-ECE", apaar="91110000007"),  # 11 digits
        r("KIT26ECE908", "08", "BTECH-ECE", apaar="911100000098"),  # one-digit typo of 911100000008
        r("KIT26ECE909", "09", "BTECH-ECE", name="Vignesh Subramaniam"),  # spelling differs from registry
        r("KIT26ECE910", "10", "BTECH-ECE", dob=date(2028, 6, 18)),  # future DOB
        r("KIT26CSE911", "11", "BTECH-CSE"),
        r("KIT26CSE912", "11", "BTECH-CSE"),  # same APAAR twice
        r("KIT26CSE913", "12", "BTECH-CSE", seat="SN_FN_OCI"),  # Indian national on FN/OCI seat
        r("KIT26MTA914", "13", "MTECH-AI"),  # unknown programme
        r("KIT26ECE915", "14", "BTECH-ECE", gender="X"),  # bad gender
        _row(apaar_id="", institution_student_id="KIT26MBA916", full_name="Tomas Herrera",
             date_of_birth=date(2001, 9, 21), gender="M", nationality_status="FN", citizenship_country="Spain",
             programme_code="MBA", academic_year="2026-27", seat_category="SN_FN_OCI",
             admission_date=date(2026, 8, 3), apaar_pending_reason="FOREIGN_NATIONAL"),
    ]


def reset_schema() -> None:
    Base.metadata.drop_all(engine)
    Base.metadata.create_all(engine)


def run(reset: bool = True, write_samples: bool = True, quiet: bool = False) -> dict:
    if reset:
        reset_schema()
    else:
        Base.metadata.create_all(engine)
    rng = random.Random(2026)
    gen = Gen(rng)
    for _s, n, d, _g in DEMO_A_PEOPLE + DEMO_B_PEOPLE:
        gen.reserve(n, d)
    gen.reserve("Ananya Iyer", date(2008, 3, 14))
    gen.reserve("Tomas Herrera", date(2001, 9, 21))
    for n, d in (("K. Anil Rao", date(2008, 7, 11)), ("Anil Kumar Rao", date(2008, 7, 11)),
                 ("Mohammed Farook", date(2002, 2, 22)), ("Mohamed Farooq", date(2002, 2, 22)),
                 ("Linh Tran", date(2007, 10, 3))):
        gen.reserve(n, d)
    pw = hash_password(PASSWORD)  # one hash reused: same password for all synthetic demo accounts

    db = SessionLocal()
    try:
        seed_rules(db)
        insts: dict[str, Institution] = {}
        progs: dict[tuple[str, str], Programme] = {}
        for idx, (code, short, _prefix, name, state, region, typ) in enumerate(INSTITUTIONS, start=1):
            inst = Institution(aicte_code=code, short_name=short, name=name, state=state, region=region,
                               institution_type=typ)
            db.add(inst)
            db.flush()
            insts[short] = inst
            for pcode, pname, level, disc, intake_n, _r26, _r25 in PROGRAMMES[short]:
                p = Programme(institution_id=inst.id, code=pcode, name=pname, level=level, discipline=disc)
                db.add(p)
                db.flush()
                progs[(short, pcode)] = p
                for year in ("2025-26", "2026-27"):
                    if year == "2025-26" and (short, pcode) in NEW_IN_2026:
                        continue
                    ai = ApprovedIntake(programme_id=p.id, academic_year=year, approved_intake=intake_n,
                                        approval_reference=f"EOA/{year}/{code}/{pcode} (synthetic)")
                    db.add(ai)
                    db.flush()
                    ledger.apply_default_caps(db, ai, p)
            _ = idx

        users = {}

        def user(email, full_name, role, inst=None, org=None, student_id=None):
            u = User(email=email, full_name=full_name, role=role, institution_id=inst.id if inst else None,
                     organisation=org, password_hash=pw, student_id=student_id)
            db.add(u)
            db.flush()
            users[email] = u
            return u

        user("aicte.admin@demo.local", "Asha Raman (AICTE monitoring, synthetic)", "AICTE_ADMIN")
        user("aicte.analyst@demo.local", "Vikram Sethi (AICTE policy analyst, synthetic)", "AICTE_ANALYST")
        user("auditor@demo.local", "Meera Kulkarni (Auditor, synthetic)", "AUDITOR")
        user("verifier@demo.local", "Rahul Nanda (HR verifier, synthetic)", "VERIFIER", org="Synthetic Employer Pvt Ltd")
        for _code, short, *_ in INSTITUTIONS:
            user(f"{short}.admin@demo.local", f"{short.capitalize()} nodal officer (synthetic)", "INST_ADMIN", insts[short])
            user(f"{short}.staff@demo.local", f"{short.capitalize()} data-entry staff (synthetic)", "INST_STAFF", insts[short])
        db.commit()

        # ---- synthetic registry + cohort rows, loaded through the engine
        registry: dict[str, SimApaarRegistry] = {}

        def reg(apaar_id, name, dob):
            registry.setdefault(apaar_id, SimApaarRegistry(apaar_id=apaar_id, full_name=name, date_of_birth=dob,
                                                           active=True))

        for sfx, n, d, _g in DEMO_A_PEOPLE:
            reg(f"9111000000{sfx}", n, d)
        for sfx, n, d, _g in DEMO_B_PEOPLE:
            reg(f"9222000000{sfx}", n, d)

        files: dict[tuple[str, str], list[dict]] = {}
        shared_student = None  # Yamuna PGDM student also enrolled at Narmada MCA (seeded D003)
        for year in ("2025-26", "2026-27"):
            gen_order = ["kaveri", "godavari", "yamuna", "narmada", "brahmaputra"]  # Yamuna before Narmada (D003)
            for idx, (_code, short, prefix, *_rest) in sorted(enumerate(INSTITUTIONS, start=1),
                                                              key=lambda t: gen_order.index(t[1][1])):
                rows = []
                for pcode, _pn, level, _disc, _n, r26, r25 in PROGRAMMES[short]:
                    count = r26 if year == "2026-27" else r25
                    yy = year[2:4]
                    serial = 0

                    def add(name, dob, g, seat="REGULAR", nat="INDIAN", country="India", apaar=None, reason=None,
                            adm=None, registry_name=None):
                        nonlocal serial
                        serial += 1
                        aid = apaar if apaar is not None else gen.apaar(idx, year)
                        if aid:
                            reg(aid, registry_name or name, dob)
                        rows.append(_row(apaar_id=aid, institution_student_id=f"{prefix}{yy}{pcode.replace('-', '')}{serial:03d}",
                                         full_name=name, date_of_birth=dob, gender=g, nationality_status=nat,
                                         citizenship_country=country, programme_code=pcode, academic_year=year,
                                         seat_category=seat, admission_date=adm or _adm_date(rng, year),
                                         social_category=rng.choice(["GEN", "OBC", "SC", "ST", "EWS", ""]),
                                         email=None, apaar_pending_reason=reason))
                        return aid

                    by = _birth_years(level, year)
                    for i in range(count):
                        if year == "2026-27" and short == "kaveri" and pcode == "BTECH-CSE" and i == 0:
                            add("Ananya Iyer", date(2008, 3, 14), "F")
                            continue
                        if year == "2026-27" and short == "narmada" and pcode == "MCA" and i == 0 and shared_student:
                            n, d, g, aid = shared_student
                            add(n, d, g, apaar=aid)
                            continue
                        if year == "2026-27" and short == "brahmaputra" and pcode == "BTECH-CIVIL" and i == 0:
                            add("K. Anil Rao", date(2008, 7, 11), "M")
                            continue
                        if year == "2026-27" and short == "godavari" and pcode == "BTECH-ME" and i == 0:
                            add("Anil Kumar Rao", date(2008, 7, 11), "M")
                            continue
                        if year == "2026-27" and short == "narmada" and pcode == "MCA" and i == 1:
                            add("Mohammed Farook", date(2002, 2, 22), "M")
                            continue
                        if year == "2026-27" and short == "brahmaputra" and pcode == "DIP-ME" and i == 0:
                            add("Mohamed Farooq", date(2002, 2, 22), "M", apaar="", reason="APPLIED_AWAITING_ID")
                            continue
                        n, d, g = gen.person(by)
                        reg_name = None
                        if year == "2026-27" and short == "brahmaputra" and pcode == "DIP-ME" and 1 <= i <= 4:
                            first, last = n.split(" ", 1)
                            reg_name = f"{first} {last[:-1] if len(last) > 4 else last + 'a'}"  # registry spelling differs
                        adm = date(2026, 4, 20) if (year == "2026-27" and short == "narmada" and pcode == "MBA"
                                                    and i < 6) else None
                        aid = add(n, d, g, adm=adm, registry_name=reg_name)
                        if year == "2026-27" and short == "yamuna" and pcode == "PGDM" and i == 0:
                            shared_student = (n, d, g, aid)
                    if year != "2026-27":
                        continue
                    sp = {
                        ("kaveri", "BTECH-CSE"): [("NRI", "NRI", 3), ("SN_FN_OCI", "FN", 2), ("SN_TFW", "INDIAN", 3)],
                        ("kaveri", "MBA"): [("SN_FN_OCI", "OCI", 1)],
                        ("godavari", "BTECH-CSE"): [("NRI", "NRI", 5), ("SN_TFW", "INDIAN", 6)],
                        ("narmada", "MBA"): [("NRI", "NRI", 4), ("SN_FN_OCI", "FN", 7), ("SN_CIWG", "INDIAN", 6)],
                        ("yamuna", "PGDM"): [("SN_FN_OCI", "FN", 4), ("SN_FN_OCI", "OCI", 2), ("NRI", "NRI", 6)],
                    }.get((short, pcode), [])
                    for seat, nat, k in sp:
                        for _ in range(k):
                            if nat == "FN":
                                while True:
                                    first, last, country = FOREIGN[rng.randrange(1, len(FOREIGN))]
                                    d = date(rng.randint(*by), rng.randint(1, 12), rng.randint(1, 28))
                                    if not gen.clashes(f"{first} {last}", d):
                                        gen.reserve(f"{first} {last}", d)
                                        break
                                add(f"{first} {last}", d, rng.choice("MF"), seat=seat, nat="FN", country=country)
                            elif nat == "OCI":
                                n, d, g = gen.person(by)
                                add(n, d, g, seat=seat, nat="OCI", country=rng.choice(OCI_COUNTRIES))
                            else:
                                n, d, g = gen.person(by)
                                add(n, d, g, seat=seat, nat=nat)
                    if (short, pcode) == ("kaveri", "BTECH-CSE"):
                        add("Linh Tran", date(2007, 10, 3), "F", seat="SN_FN_OCI", nat="FN", country="Vietnam",
                            apaar="", reason="FOREIGN_NATIONAL")
                files[(short, year)] = rows
        db.add_all(registry.values())
        db.commit()

        stats = {}
        order = ["kaveri", "godavari", "yamuna", "narmada", "brahmaputra"]
        for year in ("2025-26", "2026-27"):
            for short in order:
                rows = files[(short, year)]
                staff = actor_from_user(users[f"{short}.staff@demo.local"])
                content = _csv_bytes(rows)
                job = intake.create_job(db, staff, insts[short], year, f"seed_{short}_{year}.csv", content, rows=rows)
                db.commit()
                res = intake.commit_job(db, job, staff)
                stats[f"{short} {year}"] = {"rows": len(rows), "committed": res["committed_now"],
                                            "counts": job.summary.get("counts")}

        # Yamuna declared its 2026-27 submission complete
        for (short, _pc), p in progs.items():
            if short == "yamuna":
                ai = ledger.get_intake(db, p.id, "2026-27")
                ai.submitted_at = utcnow()
                ai.submitted_by = users["yamuna.admin@demo.local"].id

        # Student account for Ananya Iyer, with one signed record issued by the Kaveri admin
        ananya = db.execute(select(Student).where(Student.full_name == "Ananya Iyer")).scalar_one()
        u = user("student.ananya@demo.local", "Ananya Iyer (student, synthetic)", "STUDENT", student_id=ananya.id)
        en = db.execute(select(Enrolment).where(Enrolment.student_id == ananya.id)).scalar_one()
        cred = credentials.issue(db, en, users["kaveri.admin@demo.local"].id)
        from . import audit

        audit.record(db, actor_from_user(users["kaveri.admin@demo.local"]), "credential.issue", "credential", cred.id,
                     detail={"enrolment_id": en.id, "seed": True})

        # Kaveri ERP API key (scopes enrolments:write, seat:check); shown once, stored only as a hash
        key, prefix = new_api_key()
        db.add(IntegrationClient(name="Kaveri ERP (synthetic)", key_prefix=prefix, key_hash=hash_api_key(key),
                                 institution_id=insts["kaveri"].id, scopes=["enrolments:write", "seat:check"]))
        db.commit()
        keyfile = settings.var_dir / "demo_api_key.txt"
        keyfile.write_text(key + "\n")
        keyfile.chmod(0o600)
        _ = u

        if write_samples:
            write_sample_files(db, rng)
        return stats
    finally:
        db.close()


def write_sample_files(db, rng) -> None:
    SAMPLE_DIR.mkdir(exist_ok=True)
    rows = demo_a_rows()
    (SAMPLE_DIR / "demo_A_kaveri_upload_2026-27.csv").write_bytes(_csv_bytes(rows))
    wb = Workbook()
    ws = wb.active
    ws.title = "students"
    ws.append(TEMPLATE_COLUMNS)
    for r in rows:
        ws.append([r[c] for c in TEMPLATE_COLUMNS])
    wb.save(SAMPLE_DIR / "demo_A_kaveri_upload_2026-27.xlsx")

    # Demo B: Godavari BTECH-CSE, generated from the database so the existing Kaveri student's IDs match
    kaveri = db.execute(select(Institution).where(Institution.short_name == "kaveri")).scalar_one()
    ece = db.execute(select(Programme).where(Programme.institution_id == kaveri.id, Programme.code == "BTECH-ECE")).scalar_one()
    existing = db.execute(
        select(Enrolment).join(Student).where(Enrolment.programme_id == ece.id, Enrolment.academic_year == "2026-27",
                                              Enrolment.status == "ACTIVE", Student.apaar_status == "VERIFIED")
        .order_by(Enrolment.institution_student_id)
    ).scalars().first()
    st = existing.student
    first, last = st.full_name.split(" ", 1)
    misspelt = f"{first} {last[:-2] + last[-1] if len(last) > 3 else last + 'h'}"
    p = {s: (n, d, g) for s, n, d, g in DEMO_B_PEOPLE}

    def r(roll, sfx, seat="REGULAR"):
        n, d, g = p[sfx]
        return _row(apaar_id=f"9222000000{sfx}", institution_student_id=roll, full_name=n, date_of_birth=d, gender=g,
                    nationality_status="INDIAN", citizenship_country="India", programme_code="BTECH-CSE",
                    academic_year="2026-27", seat_category=seat, admission_date=date(2026, 9, 1))

    rows_b = [
        r("GEC26CSE901", "01"),
        r("GEC26CSE902", "02"),
        r("GEC26CSE903", "03"),
        _row(apaar_id=st.apaar_id, institution_student_id="GEC26CSE904", full_name=misspelt,
             date_of_birth=st.date_of_birth, gender=st.gender, nationality_status=st.nationality_status,
             citizenship_country=st.citizenship_country or "India", programme_code="BTECH-CSE", academic_year="2026-27",
             seat_category="REGULAR", admission_date=date(2026, 9, 1)),
        r("GEC26CSE905", "04", seat="SN_TFW"),
    ]
    (SAMPLE_DIR / "demo_B_godavari_upload_2026-27.csv").write_bytes(_csv_bytes(rows_b))
    (SAMPLE_DIR / "README.md").write_text(
        "# Sample files (synthetic)\n\nGenerated by `python -m app.seed --reset`. All people, institutions and APAAR IDs "
        "are synthetic.\n\n- `demo_A_kaveri_upload_2026-27.csv` / `.xlsx`: 16 rows for Demo A "
        "(expected preview 5 VALID, 2 REVIEW, 9 ERROR).\n- `demo_B_godavari_upload_2026-27.csv`: 5 rows for Demo B "
        f"(row 4 is Kaveri BTECH-ECE student {existing.institution_student_id}, name misspelt).\n"
    )


def main() -> None:
    ap = argparse.ArgumentParser(description="Seed the prototype with synthetic data.")
    ap.add_argument("--reset", action="store_true", help="drop and recreate all tables first")
    ap.add_argument("--if-empty", action="store_true", help="seed only when the database has no institutions yet")
    args = ap.parse_args()
    if args.if_empty:
        from sqlalchemy import inspect

        if inspect(engine).has_table("institutions"):
            with SessionLocal() as s:
                if s.execute(select(Institution.id).limit(1)).first():
                    print("Database already seeded; skipping (use --reset to start over).")
                    return
        args.reset = True
    started = datetime.now(UTC)
    stats = run(reset=args.reset)
    for k, v in stats.items():
        print(f"{k:<22} rows={v['rows']:<4} committed={v['committed']:<4} {v['counts']}")
    print(f"Seeded in {(datetime.now(UTC) - started).total_seconds():.1f}s. Demo password: {PASSWORD}")
    print(f"Demo ERP API key written to {settings.var_dir / 'demo_api_key.txt'}")
    print(f"Sample files in {SAMPLE_DIR}")


if __name__ == "__main__":
    main()
