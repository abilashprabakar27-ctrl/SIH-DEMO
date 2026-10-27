import { FormEvent, useState } from "react";
import { api, ApiError, fmtDate, useApi } from "../api";
import { Apaar, Badge, Confirm, Empty, ErrorBox, Field, Loading, useToast } from "../components/ui";

export default function MyRecord() {
  const me = useApi<any>("/api/v1/me/record");
  const reqs = useApi<any[]>("/api/v1/verification/requests");
  const [chosen, setChosen] = useState<Record<string, boolean>>({ institution: true, programme: true, enrolmentStatus: true });
  const [shared, setShared] = useState<any>(null);
  const [consent, setConsent] = useState<any>(null);
  const [cr, setCr] = useState({ enrolment_id: "", field: "full_name", requested_value: "", explanation: "" });
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [toast, show] = useToast();
  if (me.loading && !me.data) return <Loading what="Loading your record" />;
  if (me.error) return <ErrorBox error={me.error} onRetry={() => me.reload()} />;
  const { student: s, enrolments, credentials, correction_requests } = me.data;
  const active = credentials.find((c: any) => c.status === "ACTIVE");

  async function share() {
    setErr(null);
    try {
      setShared(await api(`/api/v1/me/credentials/${active.id}/present`, { body: { claims: Object.keys(chosen).filter((k) => chosen[k]) } }));
    } catch (e) {
      setErr(e as ApiError);
    }
  }
  async function decide(decision: string) {
    setBusy(true);
    try {
      await api(`/api/v1/verification/requests/${consent.id}/consent`, { body: { decision } });
      show(decision === "APPROVE" ? "You allowed this verification." : "You declined this verification.");
      setConsent(null);
      reqs.reload(true);
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }
  async function raise(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      await api("/api/v1/me/correction-requests", { body: { ...cr, enrolment_id: cr.enrolment_id || enrolments[0]?.id } });
      show("Correction request sent to your institution. They should respond within 14 days.");
      setCr({ ...cr, requested_value: "", explanation: "" });
      me.reload(true);
    } catch (ex) {
      setErr(ex as ApiError);
    }
  }
  const pending = (reqs.data || []).filter((r) => r.status === "PENDING_CONSENT" && !r.expired);

  return (
    <div className="stack">
      <div className="pagehead"><div><h1>{s.full_name}</h1><p className="muted">This is what your institution reported to the AICTE register.</p></div></div>
      {toast}
      <ErrorBox error={err} />
      {pending.length > 0 && (
        <section className="card" style={{ borderColor: "var(--amber)" }}>
          <h2>Verification requests waiting for you</h2>
          {pending.map((r) => (
            <div key={r.id} className="row between" style={{ padding: "6px 0" }}>
              <span><strong>{r.requester_org}</strong> · {r.purpose} <span className="small muted">expires {fmtDate(r.expires_at)}</span>
                {r.consent_hold_reason && <div className="small banner warn">Guardian consent is required. This prototype cannot collect guardian consent, so this request is on hold.</div>}</span>
              {!r.consent_hold_reason && <button onClick={() => setConsent(r)}>Review request</button>}
            </div>
          ))}
        </section>
      )}
      <section className="card">
        <h2>My details</h2>
        <table><tbody>
          <tr><td className="muted">APAAR ID</td><td><Apaar value={s.apaar_id} status={s.apaar_status} /></td></tr>
          <tr><td className="muted">Date of birth</td><td>{fmtDate(s.date_of_birth)}</td></tr>
          <tr><td className="muted">Nationality</td><td>{s.nationality_status}</td></tr>
        </tbody></table>
        <h3 style={{ marginTop: 12 }}>Enrolments</h3>
        <table><thead><tr><th>Institution</th><th>Student ID</th><th>Programme</th><th>Year</th><th>Status</th></tr></thead><tbody>
          {enrolments.map((e: any) => <tr key={e.id}><td>{e.institution_name}</td><td className="mono">{e.institution_student_id}</td><td>{e.programme_code}</td><td>{e.academic_year}</td><td><Badge v={e.status} /></td></tr>)}
        </tbody></table>
      </section>
      <section className="card">
        <h2>Share a signed record</h2>
        {!active ? <Empty>Your institution has not issued an active signed record yet.</Empty> : (
          <>
            <p className="small muted">Tick only what the verifier needs. Anything you leave unticked stays hidden, and the verifier can still check that what you share is genuine.</p>
            <div className="grid g2">
              {active.claims.map((c: any) => (
                <label key={c.claim} style={{ fontWeight: 400, display: "flex", gap: 8, alignItems: "center" }}>
                  <input type="checkbox" style={{ width: "auto" }} checked={!!chosen[c.claim]} onChange={(e) => setChosen({ ...chosen, [c.claim]: e.target.checked })} />
                  <span><strong>{c.label}</strong>: {String(c.value)}</span>
                </label>
              ))}
            </div>
            <button style={{ marginTop: 10 }} onClick={share} disabled={!Object.values(chosen).some(Boolean)}>Create share token</button>
            {shared && (
              <div className="grid g2" style={{ marginTop: 12 }}>
                <div><label>Token (send this to the verifier)</label><div className="token">{shared.token}</div>
                  <button className="secondary small" style={{ marginTop: 6 }} onClick={() => navigator.clipboard?.writeText(shared.token).then(() => show("Token copied."))}>Copy token</button></div>
                {shared.qr_svg ? <div className="qr" aria-label="QR code that opens the verification page" dangerouslySetInnerHTML={{ __html: shared.qr_svg }} /> : <p className="small muted">The token is too long for one QR code; share the token text instead.</p>}
              </div>
            )}
          </>
        )}
      </section>
      <section className="card">
        <h2>Ask for a correction</h2>
        <form onSubmit={raise} className="grid g2">
          <Field label="Enrolment"><select value={cr.enrolment_id} onChange={(e) => setCr({ ...cr, enrolment_id: e.target.value })}>
            {enrolments.map((e: any) => <option key={e.id} value={e.id}>{e.institution_name} · {e.programme_code}</option>)}</select></Field>
          <Field label="What is wrong"><select value={cr.field} onChange={(e) => setCr({ ...cr, field: e.target.value })}>
            {[["full_name", "Name"], ["date_of_birth", "Date of birth"], ["gender", "Gender"], ["apaar_id", "APAAR ID"], ["programme_code", "Programme"],
              ["admission_date", "Admission date"], ["email", "Email"], ["citizenship_country", "Citizenship"]].map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
          <Field label="Correct value"><input value={cr.requested_value} onChange={(e) => setCr({ ...cr, requested_value: e.target.value })} required /></Field>
          <Field label="Explanation (at least 10 characters)"><input value={cr.explanation} onChange={(e) => setCr({ ...cr, explanation: e.target.value })} minLength={10} required /></Field>
          <div><button type="submit">Send correction request</button></div>
        </form>
        {correction_requests.length > 0 && (
          <table style={{ marginTop: 12 }}><thead><tr><th>Field</th><th>Requested</th><th>Status</th><th>Due</th><th>Note</th></tr></thead><tbody>
            {correction_requests.map((c: any) => <tr key={c.id}><td>{c.field}</td><td>{c.requested_value}</td><td><Badge v={c.status} /></td><td>{fmtDate(c.due_at)}</td><td className="small">{c.resolution_note || "—"}</td></tr>)}
          </tbody></table>)}
      </section>
      {consent && (
        <Confirm title={`Share your record with ${consent.requester_org}?`} confirmLabel="Allow" busy={busy} onCancel={() => decide("DENY")} onConfirm={() => decide("APPROVE")}>
          <p>Purpose: {consent.purpose}</p>
          <p>If you allow, they will see only:</p>
          <ul>{consent.fields_shared.map((f: string) => <li key={f}>{f}</li>)}</ul>
          <p className="small muted">They will not see your date of birth, nationality, category or contact details. Choosing Cancel declines the request.</p>
        </Confirm>
      )}
    </div>
  );
}
