import { FormEvent, useState } from "react";
import { api, ApiError, fmtDate, useApi } from "../api";
import { Badge, ErrorBox, Field, useToast } from "../components/ui";

export default function VerifierRequests() {
  const list = useApi<any[]>("/api/v1/verification/requests");
  const [f, setF] = useState({ apaar_id: "", date_of_birth: "", purpose: "" });
  const [err, setErr] = useState<ApiError | null>(null);
  const [results, setResults] = useState<Record<string, any>>({});
  const [toast, show] = useToast();
  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      const r = await api<any>("/api/v1/verification/requests", { body: f });
      show(r.message, "info");
      setF({ apaar_id: "", date_of_birth: "", purpose: "" });
      list.reload(true);
    } catch (ex) {
      setErr(ex as ApiError);
    }
  }
  async function result(id: string) {
    try {
      setResults({ ...results, [id]: await api(`/api/v1/verification/requests/${id}/result`) });
    } catch (ex) {
      setResults({ ...results, [id]: { error: (ex as ApiError).message } });
    }
  }
  return (
    <div className="stack">
      <div className="pagehead"><div><h1>Request verification</h1>
        <p className="muted">You need the student's full APAAR ID and date of birth. The student decides whether to share. You see only name, masked APAAR, institutions, programmes, years and statuses.</p></div></div>
      {toast}
      <section className="card">
        <form onSubmit={submit} className="grid g3">
          <Field label="APAAR ID (12 digits)"><input value={f.apaar_id} onChange={(e) => setF({ ...f, apaar_id: e.target.value })} inputMode="numeric" required /></Field>
          <Field label="Date of birth (YYYY-MM-DD)"><input value={f.date_of_birth} onChange={(e) => setF({ ...f, date_of_birth: e.target.value })} required /></Field>
          <Field label="Purpose (shown to the student)"><input value={f.purpose} onChange={(e) => setF({ ...f, purpose: e.target.value })} minLength={10} required /></Field>
          <div><button type="submit">Send request</button></div>
        </form>
        <ErrorBox error={err} />
      </section>
      <section className="card flat"><table>
        <thead><tr><th>Purpose</th><th>Sent</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {list.data?.length === 0 && <tr><td colSpan={4} className="muted">No requests yet.</td></tr>}
          {list.data?.map((r) => (
            <tr key={r.id}><td>{r.purpose}</td><td className="small">{fmtDate(r.created_at)}<div className="muted">expires {fmtDate(r.expires_at)}</div></td>
              <td><Badge v={r.status} /></td>
              <td>{r.status === "APPROVED" ? <button className="small" onClick={() => result(r.id)}>View result</button>
                : <button className="small secondary" onClick={() => result(r.id)}>Check result</button>}
                {results[r.id] && (results[r.id].error ? <p className="small" style={{ color: "var(--red)" }}>{results[r.id].error}</p> : (
                  <div className="small" style={{ marginTop: 6 }}>
                    <strong>{results[r.id].name}</strong> · <span className="mono">{results[r.id].apaar_id_masked}</span> · registry {results[r.id].registry_status.status} <Badge v="SIMULATED" />
                    {results[r.id].enrolments.map((e: any, i: number) => <div key={i}>{e.institution} · {e.programme} · {e.academic_year} · {e.status}</div>)}
                  </div>))}
              </td></tr>
          ))}
        </tbody></table></section>
    </div>
  );
}
