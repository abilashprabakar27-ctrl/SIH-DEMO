import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, CURRENT_YEAR, useApi } from "../api";
import { ErrorBox, Field, Findings, useToast } from "../components/ui";

const EMPTY = {
  apaar_id: "", apaar_pending_reason: "", institution_student_id: "", full_name: "", date_of_birth: "", gender: "F",
  nationality_status: "INDIAN", citizenship_country: "India", programme_code: "", academic_year: CURRENT_YEAR,
  seat_category: "REGULAR", admission_date: "", social_category: "", email: "",
};

export default function AddStudent() {
  const progs = useApi<any[]>(`/api/v1/programmes?academic_year=${CURRENT_YEAR}`);
  const [f, setF] = useState<Record<string, string>>(EMPTY);
  const [status, setStatus] = useState("ACTIVE");
  const [err, setErr] = useState<ApiError | null>(null);
  const [findings, setFindings] = useState<any[]>([]);
  const [needsAck, setNeedsAck] = useState(false);
  const [saved, setSaved] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [toast, show] = useToast();
  const set = (k: string) => (e: { target: { value: string } }) => setF({ ...f, [k]: e.target.value });

  async function save(e?: FormEvent, ack = false) {
    e?.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const record = { ...f, programme_code: f.programme_code || progs.data?.[0]?.code || "" };
      const r = await api<any>("/api/v1/enrolments", { body: { academic_year: f.academic_year, record, acknowledge_review: ack, status } });
      setSaved(r.enrolment);
      setFindings(r.findings);
      setNeedsAck(false);
      show(`Saved ${r.enrolment.student.full_name} (${r.enrolment.institution_student_id}).`);
      setF({ ...EMPTY, programme_code: record.programme_code });
    } catch (ex) {
      const ae = ex as ApiError;
      setErr(ae);
      setFindings(ae.data?.findings || []);
      setNeedsAck(!!ae.data?.needs_acknowledgement);
    } finally {
      setBusy(false);
    }
  }

  const flagged = new Set(findings.filter((x) => x.severity === "ERROR" || x.severity === "REVIEW").map((x) => x.field));
  return (
    <div className="stack">
      <div className="pagehead"><div><h1>Add a student</h1>
        <p className="muted">For a single admission. The same rules as uploads apply; for many students, <Link to="/inst/upload">upload a file</Link>.</p></div></div>
      {toast}
      {saved && <div className="banner ok">Saved. <Link to={`/records/${saved.id}`}>Open {saved.student.full_name}'s record</Link></div>}
      <form className="card" onSubmit={save}>
        <div className="grid g3">
          <Field label="APAAR ID (12 digits)" flagged={flagged.has("apaar_id")} hint="Leave blank only with a pending reason.">
            <input value={f.apaar_id} onChange={set("apaar_id")} inputMode="numeric" /></Field>
          <Field label="APAAR pending reason" flagged={flagged.has("apaar_pending_reason")}>
            <select value={f.apaar_pending_reason} onChange={set("apaar_pending_reason")}>
              <option value="">(APAAR ID given)</option><option>FOREIGN_NATIONAL</option><option>APPLIED_AWAITING_ID</option><option>OTHER_DOCUMENTED</option></select></Field>
          <Field label="Roll number" flagged={flagged.has("institution_student_id")}><input value={f.institution_student_id} onChange={set("institution_student_id")} required /></Field>
          <Field label="Full name" flagged={flagged.has("full_name")}><input value={f.full_name} onChange={set("full_name")} required /></Field>
          <Field label="Date of birth" flagged={flagged.has("date_of_birth")}><input type="date" value={f.date_of_birth} onChange={set("date_of_birth")} required /></Field>
          <Field label="Gender" flagged={flagged.has("gender")}><select value={f.gender} onChange={set("gender")}>
            <option value="F">Female</option><option value="M">Male</option><option value="T">Transgender</option><option value="O">Other</option></select></Field>
          <Field label="Nationality status" flagged={flagged.has("nationality_status")}><select value={f.nationality_status} onChange={set("nationality_status")}>
            {["INDIAN", "NRI", "OCI", "FN"].map((x) => <option key={x}>{x}</option>)}</select></Field>
          <Field label="Citizenship country" flagged={flagged.has("citizenship_country")}><input value={f.citizenship_country} onChange={set("citizenship_country")} /></Field>
          <Field label="Programme" flagged={flagged.has("programme_code")}><select value={f.programme_code} onChange={set("programme_code")}>
            {progs.data?.map((p) => <option key={p.code} value={p.code}>{p.code} — {p.name}</option>)}</select></Field>
          <Field label="Seat category" flagged={flagged.has("seat_category")}><select value={f.seat_category} onChange={set("seat_category")}>
            {["REGULAR", "NRI", "SN_FN_OCI", "SN_CIWG", "SN_TFW", "SN_OTHER"].map((x) => <option key={x}>{x}</option>)}</select></Field>
          <Field label="Admission date" flagged={flagged.has("admission_date")}><input type="date" value={f.admission_date} onChange={set("admission_date")} required /></Field>
          <Field label="Status"><select value={status} onChange={(e) => setStatus(e.target.value)}><option>ACTIVE</option><option>PROVISIONAL</option></select></Field>
          <Field label="Social category (optional, sensitive)"><select value={f.social_category} onChange={set("social_category")}>
            <option value="">(not given)</option>{["GEN", "EWS", "OBC", "SC", "ST"].map((x) => <option key={x}>{x}</option>)}</select></Field>
          <Field label="Email (optional)" flagged={flagged.has("email")}><input type="email" value={f.email} onChange={set("email")} /></Field>
        </div>
        <ErrorBox error={err} />
        {findings.length > 0 && <div style={{ marginBottom: 10 }}><Findings items={findings} /></div>}
        <div className="row">
          <button type="submit" disabled={busy}>{busy ? "Checking…" : "Check and save student"}</button>
          {needsAck && <button type="button" className="secondary" disabled={busy} onClick={() => save(undefined, true)}>Save and open a review flag</button>}
        </div>
      </form>
    </div>
  );
}
