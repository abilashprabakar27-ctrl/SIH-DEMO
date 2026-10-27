import { useEffect, useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError, fmtDate, fmtDateTime, openDocument, useApi } from "../api";
import { useAuth } from "../App";
import SeatStrip from "../components/SeatStrip";
import { Apaar, Badge, Confirm, ErrorBox, Field, Findings, Loading, Tabs, useToast } from "../components/ui";

const EDITABLE: [string, string][] = [
  ["full_name", "Full name"], ["date_of_birth", "Date of birth"], ["gender", "Gender"], ["nationality_status", "Nationality status"],
  ["citizenship_country", "Citizenship country"], ["apaar_id", "APAAR ID"], ["institution_student_id", "Roll number"],
  ["programme_code", "Programme code"], ["seat_category", "Seat category"], ["admission_date", "Admission date"],
  ["social_category", "Social category"], ["email", "Email"], ["apaar_pending_reason", "APAAR pending reason"],
];

function current(e: any): Record<string, string> {
  const s = e.student;
  return {
    full_name: s.full_name, date_of_birth: s.date_of_birth, gender: s.gender, nationality_status: s.nationality_status,
    citizenship_country: s.citizenship_country || "", apaar_id: s.apaar_masked ? "" : s.apaar_id || "",
    institution_student_id: e.institution_student_id, programme_code: e.programme_code, seat_category: e.seat_category,
    admission_date: e.admission_date, social_category: s.social_category || "", email: s.email || "",
    apaar_pending_reason: s.apaar_pending_reason || "",
  };
}

export default function RecordDetail() {
  const { id } = useParams();
  const [sp] = useSearchParams();
  const { user } = useAuth();
  const d = useApi<any>(`/api/v1/enrolments/${id}`, [id]);
  const [mode, setMode] = useState<"" | "correct" | "status">("");
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [reason, setReason] = useState("");
  const [status, setStatus] = useState("");
  const [findings, setFindings] = useState<any[]>([]);
  const [needsAck, setNeedsAck] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [revoke, setRevoke] = useState<any>(null);
  const [revokeReason, setRevokeReason] = useState("");
  const [toast, show] = useToast();
  const [tab, setTab] = useState("details");
  const inst = user?.role === "INST_ADMIN" || user?.role === "INST_STAFF";

  useEffect(() => {
    if (d.data && sp.get("field") && inst) {
      setMode("correct");
      setDraft({ ...current(d.data.enrolment), [sp.get("field")!]: sp.get("value") || "" });
      setReason(`Student correction request: ${sp.get("field")}`);
    }
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, [d.data?.enrolment?.id]);

  if (d.loading && !d.data) return <Loading what="Loading record" />;
  if (d.error) return <ErrorBox error={d.error} onRetry={() => d.reload()} />;
  const { enrolment: e, history, flags, credentials, allowed_transitions, position } = d.data;
  const s = e.student;

  async function act(fn: () => Promise<any>, ok: string) {
    setBusy(true);
    setErr(null);
    try {
      await fn();
      show(ok);
      setMode("");
      setFindings([]);
      setNeedsAck(false);
      setReason("");
      await d.reload(true);
    } catch (ex) {
      const ae = ex as ApiError;
      setErr(ae);
      setFindings(ae.data?.findings || []);
      setNeedsAck(!!ae.data?.needs_acknowledgement);
    } finally {
      setBusy(false);
    }
  }
  const saveCorrection = (ack = false) => {
    const base = current(e);
    const changes: Record<string, string> = {};
    for (const [k] of EDITABLE) if ((draft[k] ?? "") !== (base[k] ?? "") && !(k === "apaar_id" && !draft[k])) changes[k] = draft[k] ?? "";
    return act(() => api(`/api/v1/enrolments/${id}`, { method: "PATCH", body: { version: e.version, reason, changes, acknowledge_review: ack,
      correction_request_id: sp.get("cr") || undefined } }), "Correction saved. The previous values are kept in the history.");
  };

  return (
    <div className="stack">
      <div className="pagehead">
        <div>
          <h1>{s.full_name}</h1>
          <p className="muted">{e.institution_name} · {e.programme_code} {e.programme_name} · {e.academic_year}</p>
        </div>
        {inst && (
          <div className="row">
            <button className="secondary" onClick={() => { setMode("correct"); setDraft(current(e)); setTab("details"); }}>Correct this record</button>
            {allowed_transitions.length > 0 && <button className="secondary" onClick={() => { setMode("status"); setStatus(allowed_transitions[0]); setTab("details"); }}>Change status</button>}
          </div>
        )}
      </div>
      {toast}
      <Tabs active={tab} onChange={setTab} tabs={[["details", "Details"], ["signed", `Signed records (${credentials.length})`],
        ["flags", `Flags (${flags.length})`], ["history", `History (${history.length})`]]} />
      {tab === "details" && <>
      <div className="grid g2">
        <section className="card">
          <h2>Student</h2>
          <table><tbody>
            <tr><td className="muted">APAAR ID</td><td><Apaar value={s.apaar_id} status={s.apaar_status} masked={s.apaar_masked} />
              {s.apaar_pending_reason && <div className="small muted">Pending: {s.apaar_pending_reason}</div>}</td></tr>
            <tr><td className="muted">Institution student ID</td><td className="mono">{e.institution_student_id}</td></tr>
            <tr><td className="muted">Date of birth</td><td>{fmtDate(s.date_of_birth)}</td></tr>
            <tr><td className="muted">Gender</td><td>{s.gender}</td></tr>
            <tr><td className="muted">Nationality</td><td>{s.nationality_status}{s.citizenship_country ? ` · ${s.citizenship_country}` : ""}</td></tr>
            {s.social_category !== null && <tr><td className="muted">Social category (sensitive)</td><td>{s.social_category || "—"}</td></tr>}
            {s.email !== null && <tr><td className="muted">Email</td><td>{s.email || "—"}</td></tr>}
          </tbody></table>
          {d.data.enrolled_elsewhere && <p className="banner info small" style={{ marginTop: 10 }}>This student also has a record at another institution. Identity fields are shared and can only be corrected by AICTE.</p>}
        </section>
        <section className="card">
          <h2>Enrolment</h2>
          <table><tbody>
            <tr><td className="muted">Status</td><td><Badge v={e.status} /></td></tr>
            <tr><td className="muted">Seat category</td><td>{e.seat_category}</td></tr>
            <tr><td className="muted">Admission date</td><td>{fmtDate(e.admission_date)}</td></tr>
            <tr><td className="muted">Source</td><td>{e.source}</td></tr>
            <tr><td className="muted">Version</td><td>{e.version}</td></tr>
          </tbody></table>
          <h3 style={{ marginTop: 12 }}>{e.programme_code} seat position</h3>
          <SeatStrip pos={position} />
        </section>
      </div>
      <ErrorBox error={err} />
      {findings.length > 0 && <section className="card"><Findings items={findings} /></section>}
      {mode === "correct" && (
        <section className="card">
          <h2>Correct this record</h2>
          <p className="small muted">Changes are re-checked with the same rules as uploads. Leave APAAR ID blank to keep it unchanged.</p>
          <div className="grid g3">
            {EDITABLE.map(([k, label]) => (
              <Field key={k} label={label}><input value={draft[k] ?? ""} onChange={(ev) => setDraft({ ...draft, [k]: ev.target.value })} /></Field>
            ))}
          </div>
          <Field label="Reason for the change (kept in the history)"><textarea value={reason} onChange={(ev) => setReason(ev.target.value)} /></Field>
          <div className="row">
            <button disabled={busy || reason.trim().length < 5} onClick={() => saveCorrection(false)}>Save correction</button>
            {needsAck && <button className="secondary" disabled={busy} onClick={() => saveCorrection(true)}>Save and open a review flag</button>}
            <button className="secondary" onClick={() => setMode("")}>Cancel</button>
          </div>
        </section>
      )}
      {mode === "status" && (
        <section className="card">
          <h2>Change enrolment status</h2>
          <div className="inline">
            <Field label="New status"><select value={status} onChange={(ev) => setStatus(ev.target.value)}>{allowed_transitions.map((t: string) => <option key={t}>{t}</option>)}</select></Field>
            <div className="field" style={{ flex: "1 1 280px" }}><label>Reason</label><input value={reason} onChange={(ev) => setReason(ev.target.value)} /></div>
            <button disabled={busy || reason.trim().length < 5} onClick={() => act(() => api(`/api/v1/enrolments/${id}/status`, { body: { status, reason, version: e.version } }), `Status changed to ${status}. Seat counts updated.`)}>
              Mark as {status.replace("_", " ").toLowerCase()}</button>
            <button className="secondary" onClick={() => setMode("")}>Cancel</button>
          </div>
        </section>
      )}
      </>}
      {tab === "signed" && (
      <section className="card">
        <div className="row between"><h2>Signed records</h2>
          {user?.role === "INST_ADMIN" && ["ACTIVE", "GRADUATED"].includes(e.status) && (
            <button onClick={() => act(() => api(`/api/v1/enrolments/${id}/credentials`, { method: "POST" }), "Signed record issued. Any earlier record is superseded.")} disabled={busy}>
              Issue signed record</button>)}
        </div>
        {credentials.length === 0 ? <p className="muted">No signed record issued.</p> : (
          <table><thead><tr><th>Record</th><th>Status</th><th>Issued</th><th>Valid until</th><th></th></tr></thead><tbody>
            {credentials.map((c: any) => (
              <tr key={c.id}><td className="mono small">{c.id.slice(0, 8)}</td>
                <td><Badge v={c.status} />{c.revocation_reason && <div className="small muted">{c.revocation_reason}</div>}</td>
                <td>{fmtDate(c.issued_at)}</td><td>{fmtDate(c.expires_at)}</td>
                <td className="row">
                  {(inst || user?.role === "AICTE_ADMIN") && <button className="small secondary" onClick={() => openDocument(`/api/v1/credentials/${c.id}/certificate`).catch(setErr)}>Open certificate</button>}
                  {c.status === "ACTIVE" && (user?.role === "INST_ADMIN" || user?.role === "AICTE_ADMIN") && <button className="small danger" onClick={() => setRevoke(c)}>Revoke record</button>}
                </td></tr>
            ))}
          </tbody></table>
        )}
      </section>
      )}
      {tab === "flags" && (
        <section className="card">
          <h2>Flags on this record</h2>
          {flags.length === 0 ? <p className="muted">None.</p> : flags.map((f: any) => (
            <p key={f.id}><Badge v={f.status} /> <Link to={`/issues/${f.id}`}><code>{f.rule_id}</code></Link> {f.message}</p>
          ))}
        </section>
      )}
      {tab === "history" && (
        <section className="card">
          <h2>History</h2>
          <ul className="timeline">
            {history.map((h: any, i: number) => (
              <li key={i}><strong>{h.entity_type} v{h.version}</strong> · <span className="small muted">{fmtDateTime(h.at)}</span><br />
                <span className="small">{h.reason}</span><br />
                <span className="small muted">{Object.entries(h.changes).map(([k, v]: any) => `${k}: ${v.old ?? "—"} → ${v.new ?? "—"}`).join("; ")}</span></li>
            ))}
          </ul>
        </section>
      )}
      {revoke && (
        <Confirm title="Revoke this signed record?" confirmLabel="Revoke record" danger busy={busy} onCancel={() => setRevoke(null)}
          onConfirm={() => act(() => api(`/api/v1/credentials/${revoke.id}/revoke`, { body: { reason: revokeReason } }), "Record revoked. Verifiers will see the reason.").then(() => setRevoke(null))}>
          <p>Anyone verifying it will see "Revoked" with your reason. This cannot be undone; you can issue a new record.</p>
          <Field label="Reason (shown to verifiers)"><input value={revokeReason} onChange={(ev) => setRevokeReason(ev.target.value)} /></Field>
        </Confirm>
      )}
    </div>
  );
}
