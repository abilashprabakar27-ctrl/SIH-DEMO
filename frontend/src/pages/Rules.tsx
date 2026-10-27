import { useState } from "react";
import { api, ApiError, useApi } from "../api";
import { useAuth } from "../App";
import { Badge, ErrorBox, Loading, useToast } from "../components/ui";

export default function Rules() {
  const { user } = useAuth();
  const r = useApi<any[]>("/api/v1/rules");
  const metrics = useApi<any>("/api/v1/rules/metrics");
  const history = useApi<any[]>("/api/v1/rules/history");
  const [err, setErr] = useState<ApiError | null>(null);
  const [toast, show] = useToast();
  const admin = user?.role === "AICTE_ADMIN";
  async function patch(id: string, body: any) {
    setErr(null);
    try {
      await api(`/api/v1/rules/${id}`, { method: "PATCH", body });
      show(`${id} updated. The change is in the audit trail.`);
      r.reload(true);
    } catch (e) {
      setErr(e as ApiError);
    }
  }
  if (r.loading && !r.data) return <Loading />;
  return (
    <div className="stack">
      <div className="pagehead"><div><h1>Validation rules</h1><p className="muted">{r.data?.length} rules with stable IDs. ERROR blocks a row, WARNING commits with a note, REVIEW commits and opens a flag. Locked rules protect data integrity.</p></div></div>
      {toast}
      <ErrorBox error={err || r.error} />
      <section className="card"><h2>Flag outcomes</h2><p className="small muted">Flags are review prompts. Outcome rates help spot rules that may need tuning; they do not establish misconduct.</p>
        {metrics.error ? <ErrorBox error={metrics.error} /> : <div className="tablewrap"><table><thead><tr><th>Rule</th><th>Opened</th><th>Resolved</th><th>False positive</th><th>Median close time</th></tr></thead><tbody>
          {(metrics.data?.items || []).map((m: any) => <tr key={m.rule_id}><td><code>{m.rule_id}</code></td><td>{m.opened}</td><td>{m.resolved}</td><td>{m.false_positive_percent == null ? "—" : `${m.false_positive_percent}% (${m.false_positive})`}</td><td>{m.median_resolution_hours == null ? "—" : `${m.median_resolution_hours} h`}</td></tr>)}
          {(metrics.data?.items || []).length === 0 && <tr><td colSpan={5} className="muted">No flag outcome data yet.</td></tr>}</tbody></table></div>}
      </section>
      <section className="card"><h2>Rule configuration history</h2><p className="small muted">Each change creates a numbered snapshot for later review.</p>
        {history.error ? <ErrorBox error={history.error} /> : <div className="tablewrap"><table><thead><tr><th>Version</th><th>Reason</th><th>Changed</th><th>Rules captured</th></tr></thead><tbody>
          {(history.data || []).map((h: any) => <tr key={h.id}><td>v{h.version}</td><td>{h.reason}</td><td>{new Date(h.created_at).toLocaleString()}</td><td>{Object.keys(h.rules).length}</td></tr>)}
          {(history.data || []).length === 0 && <tr><td colSpan={4} className="muted">No rule snapshots yet.</td></tr>}</tbody></table></div>}
      </section>
      <section className="card flat"><div className="tablewrap"><table>
        <thead><tr><th>Rule</th><th>What it checks</th><th>Stage</th><th>Severity</th><th>Enabled</th></tr></thead>
        <tbody>{r.data?.map((x) => (
          <tr key={x.rule_id}><td><code>{x.rule_id}</code>{x.locked && <div><Badge v="CANCELLED">locked</Badge></div>}</td>
            <td><strong>{x.title}</strong><div className="small muted">{x.description}</div><div className="small">Fix: {x.remediation}</div></td>
            <td className="small">{x.stage.toLowerCase()}</td>
            <td>{admin && !x.locked ? (
              <select aria-label={`Severity of ${x.rule_id}`} value={x.severity} onChange={(e) => patch(x.rule_id, { severity: e.target.value })} style={{ width: "auto" }}>
                {["ERROR", "WARNING", "REVIEW"].map((s) => <option key={s}>{s}</option>)}</select>) : <Badge v={x.severity} />}</td>
            <td>{admin && !x.locked ? <input type="checkbox" aria-label={`Enable ${x.rule_id}`} checked={x.enabled} onChange={(e) => patch(x.rule_id, { enabled: e.target.checked })} style={{ width: "auto" }} />
              : x.enabled ? "Yes" : "No"}</td></tr>
        ))}</tbody></table></div></section>
    </div>
  );
}
