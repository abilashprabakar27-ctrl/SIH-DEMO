import { useState } from "react";
import { Link, useParams, useSearchParams } from "react-router-dom";
import { api, ApiError, download, fmtDateTime, useApi, useLiveEvents } from "../api";
import { useAuth } from "../App";
import SeatStrip from "../components/SeatStrip";
import { Badge, ErrorBox, Field, Loading, Pager, useToast } from "../components/ui";

const ACTION_LABEL: Record<string, string> = {
  REQUEST_CLARIFICATION: "Request clarification", RESPOND: "Send response", RESOLVE: "Resolve flag", DISMISS: "Dismiss flag", REOPEN: "Reopen flag",
};

export function IssueList() {
  const [sp, setSp] = useSearchParams();
  const { user } = useAuth();
  const status = sp.get("status") ?? "OPEN,CLARIFICATION_REQUESTED,RESPONDED";
  const rule = sp.get("rule_id") || "";
  const page = Number(sp.get("page") || 1);
  const r = useApi<any>(`/api/v1/issues?status=${status}&rule_id=${rule}&page=${page}&page_size=50`, [status, rule, page]);
  const [err, setErr] = useState<ApiError | null>(null);
  useLiveEvents(() => r.reload(true), user?.role !== "AUDITOR");
  const set = (k: string, v: string) => { const n = new URLSearchParams(sp); n.set(k, v); if (k !== "page") n.delete("page"); setSp(n); };
  return (
    <div className="stack">
      <div className="pagehead">
        <div><h1>{user?.role.startsWith("AICTE") ? "Review queue" : "Flags"}</h1>
          <p className="muted">A flag means a person should look. It is not a finding of wrongdoing.</p></div>
        <button className="secondary" onClick={() => download(`/api/v1/issues/export.csv?status=${status}&rule_id=${rule}`, "flags.csv").catch(setErr)}>Export flags (CSV)</button>
      </div>
      <ErrorBox error={err} />
      <section className="card inline">
        <div className="field"><label>Status</label>
          <select value={status} onChange={(e) => set("status", e.target.value)}>
            <option value="OPEN,CLARIFICATION_REQUESTED,RESPONDED">Needs attention</option><option value="OPEN">Open</option>
            <option value="CLARIFICATION_REQUESTED">Clarification requested</option><option value="RESPONDED">Responded</option>
            <option value="RESOLVED,DISMISSED">Closed</option><option value="">All</option></select></div>
        <div className="field"><label>Rule</label><input value={rule} onChange={(e) => set("rule_id", e.target.value)} placeholder="e.g. C001_EXCESS_INTAKE" /></div>
      </section>
      <ErrorBox error={r.error} onRetry={() => r.reload()} />
      {r.loading && !r.data && <Loading />}
      {r.data && (
        <section className="card flat"><div className="tablewrap scrollbox"><table>
          <thead><tr><th>Rule</th><th>What was found</th><th>Institution</th><th>Year</th><th>Status</th><th>Opened</th></tr></thead>
          <tbody>
            {r.data.items.length === 0 && <tr><td colSpan={6} className="muted">No flags here.</td></tr>}
            {r.data.items.map((i: any) => (
              <tr key={i.id}><td><Link to={`/issues/${i.id}`}><code>{i.rule_id}</code></Link><div><Badge v={i.severity} /></div></td>
                <td>{i.message}</td><td className="small">{i.institution_name || "—"}</td><td>{i.academic_year}</td>
                <td><Badge v={i.status} /></td><td className="small">{fmtDateTime(i.created_at)}</td></tr>
            ))}
          </tbody></table></div>
          <Pager page={page} pageSize={50} total={r.data.total} onPage={(p) => set("page", String(p))} />
        </section>
      )}
    </div>
  );
}

function Evidence({ ev }: { ev: any }) {
  return (
    <div className="stack">
      {ev.position && <div><h3>Seat position ({ev.programme_code} {ev.academic_year})</h3><SeatStrip pos={ev.position} /></div>}
      {ev.sides && (
        <div className="tablewrap scrollbox"><table><thead><tr><th>Side</th><th>Institution</th><th>Roll / record</th><th>Programme</th><th>Year</th><th>Status</th></tr></thead>
          <tbody>{ev.sides.map((s: any, i: number) => (
            <tr key={i}><td>{s.own ? <Badge v="VALID">Your institution</Badge> : <Badge v="PREVIEW">Other</Badge>}</td>
              <td>{s.institution_name || s.institution || "—"}</td>
              <td>{s.enrolment_id ? <Link to={`/records/${s.enrolment_id}`}>{s.institution_student_id || "Open record"}</Link> : "—"}{s.student_name && <div className="small muted">{s.student_name}</div>}</td>
              <td>{s.programme_code || "—"}</td><td>{s.academic_year || "—"}</td><td>{s.status ? <Badge v={s.status} /> : "—"}</td></tr>
          ))}</tbody></table></div>
      )}
      {ev.weights && (
        <div><h3>Why we think these match (score {ev.score})</h3>
          <table><tbody>{ev.weights.map((w: any, i: number) => <tr key={i}><td>{w.factor}</td><td className="num">{w.weight > 0 ? "+" : ""}{w.weight}</td></tr>)}</tbody></table></div>
      )}
      {ev.finding && <p className="small"><code>{ev.finding.rule_id}</code> {ev.finding.message}</p>}
    </div>
  );
}

export function IssueDetail() {
  const { id } = useParams();
  const d = useApi<any>(`/api/v1/issues/${id}`, [id]);
  const [note, setNote] = useState("");
  const [busy, setBusy] = useState(false);
  const [err, setErr] = useState<ApiError | null>(null);
  const [toast, show] = useToast();
  useLiveEvents((t, data) => { if (t === "poll" || data.issue_id === id) d.reload(true); });
  if (d.loading && !d.data) return <Loading />;
  if (d.error) return <ErrorBox error={d.error} onRetry={() => d.reload()} />;
  const i = d.data;
  async function act(action: string) {
    setBusy(true);
    setErr(null);
    try {
      d.setData(await api(`/api/v1/issues/${id}/actions`, { body: { action, note } }));
      setNote("");
      show(`${ACTION_LABEL[action]}: done.`);
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }
  return (
    <div className="stack">
      <div className="pagehead"><div><p className="small"><Link to="/issues">← All flags</Link></p>
        <h1><code style={{ fontSize: 20 }}>{i.rule_id}</code> <Badge v={i.status} /></h1>
        <p className="muted">{i.institution_name} · {i.academic_year} · opened {fmtDateTime(i.created_at)}</p></div></div>
      {toast}
      <section className="card"><p style={{ fontSize: 16 }}>{i.message}</p><p className="small muted">How to fix: {i.remediation}</p>
        {i.resolution_note && <p className="banner ok small">Closing note: {i.resolution_note}</p>}</section>
      <section className="card"><h2>Evidence</h2><Evidence ev={i.evidence} /></section>
      {i.allowed_actions.length > 0 && (
        <section className="card">
          <h2>Take action</h2>
          <ErrorBox error={err} />
          <Field label="Note (required, kept in the history)"><textarea value={note} onChange={(e) => setNote(e.target.value)} /></Field>
          <div className="row">{i.allowed_actions.map((a: string) => (
            <button key={a} className={a === "DISMISS" ? "secondary" : ""} disabled={busy || !note.trim()} onClick={() => act(a)}>{ACTION_LABEL[a]}</button>
          ))}</div>
        </section>
      )}
      <section className="card"><h2>History</h2><ul className="timeline">
        {i.history.map((h: any, k: number) => (
          <li key={k}><strong>{h.action.replace(/_/g, " ").toLowerCase()}</strong> by {h.actor_role === "SYSTEM" ? "the system" : h.actor_role.replace("_", " ")}{h.by_you ? " (you)" : ""} · <span className="small muted">{fmtDateTime(h.at)}</span>{h.note && <div className="small">{h.note}</div>}</li>
        ))}
      </ul></section>
    </div>
  );
}
