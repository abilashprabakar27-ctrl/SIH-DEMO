import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, CURRENT_YEAR, fmtDate, fmtDateTime, useApi, useLiveEvents, liveLabel, YEARS } from "../api";
import { useAuth } from "../App";
import SeatStrip, { SeatLegend } from "../components/SeatStrip";
import { Badge, Confirm, Empty, ErrorBox, Figure, Loading, useToast } from "../components/ui";

export default function InstDashboard() {
  const { user } = useAuth();
  const [year, setYear] = useState(CURRENT_YEAR);
  const d = useApi<any>(`/api/v1/dashboard/institution?academic_year=${year}`, [year]);
  const [updated, setUpdated] = useState<string | null>(null);
  const [confirm, setConfirm] = useState<any>(null);
  const [busy, setBusy] = useState(false);
  const [toast, show] = useToast();
  const live = useLiveEvents(() => {
    d.reload(true);
    setUpdated(new Date().toLocaleTimeString());
  });

  async function declare(p: any) {
    setBusy(true);
    try {
      await api(`/api/v1/intakes/${p.intake_id}/submit`, { method: "POST" });
      show(`Submission declared complete for ${p.programme_code} ${year}.`);
      setConfirm(null);
      d.reload(true);
    } catch (e) {
      show((e as ApiError).message, "error");
    } finally {
      setBusy(false);
    }
  }

  if (d.loading && !d.data) return <Loading what="Loading dashboard" />;
  if (d.error) return <ErrorBox error={d.error} onRetry={() => d.reload()} />;
  const x = d.data;
  const f = x.figures;
  return (
    <div className="stack">
      <div className="pagehead">
        <div>
          <h1>{x.institution.name}</h1>
          <p className="muted">AICTE code {x.institution.aicte_code} · {x.institution.state} · submission deadline {fmtDate(x.submission.deadline)}</p>
        </div>
        <div className="row">
          <span className="live">{liveLabel(live)}{updated && ` · updated ${updated}`}</span>
          <select aria-label="Academic year" value={year} onChange={(e) => setYear(e.target.value)} style={{ width: "auto" }}>
            {YEARS.map((y) => <option key={y}>{y}</option>)}
          </select>
          <Link className="btn" to="/inst/upload">Upload records</Link>
        </div>
      </div>
      {toast}
      <div className="figs">
        <Figure k="Approved intake" v={f.approved_intake} />
        <Figure k="Within intake (regular + NRI)" v={f.within_intake_enrolled} />
        <Figure k="Seats over intake" v={f.excess_over_intake} tone={f.excess_over_intake ? "bad" : undefined} />
        <Figure k="Supernumerary enrolled" v={f.supernumerary_enrolled} />
        <Figure k="Open flags" v={x.open_flags.total} tone={x.open_flags.total ? "warn" : undefined} />
        <Figure k="Correction requests open" v={x.correction_requests.open} tone={x.correction_requests.overdue ? "bad" : undefined} />
      </div>
      <section className="card">
        <div className="row between"><h2>Seat position by programme · {year}</h2><SeatLegend /></div>
        {x.programmes.length === 0 && <Empty>No approved intake for {year}.</Empty>}
        <div className="prog-grid">
        {x.programmes.map((p: any) => (
          <div key={p.programme_id}>
            <div className="row between">
              <strong>{p.programme_code} <span className="muted" style={{ fontWeight: 400 }}>{p.programme_name}</span></strong>
              <span className="row">
                {p.submitted_at ? <Badge v="COMMITTED">Submission declared {fmtDate(p.submitted_at)}</Badge>
                  : user?.role === "INST_ADMIN" && year === CURRENT_YEAR
                    ? <button className="secondary small" onClick={() => setConfirm(p)}>Declare submission complete</button>
                    : <Badge v="PREVIEW">Submission open</Badge>}
                <Link className="small" to={`/records?programme_code=${p.programme_code}&academic_year=${year}`}>Records</Link>
              </span>
            </div>
            <SeatStrip pos={p} />
          </div>
        ))}
        </div>
      </section>
      <div className="grid g2">
        <section className="card">
          <h2>Recent uploads</h2>
          {x.recent_uploads.length === 0 ? <Empty>No uploads yet. <Link to="/inst/upload">Upload your first file</Link>.</Empty> : (
            <div className="scrollbox short"><table><thead><tr><th>File</th><th>Status</th><th className="num">Rows</th><th>When</th></tr></thead><tbody>
              {x.recent_uploads.map((j: any) => (
                <tr key={j.id}><td><Link to={`/inst/imports/${j.id}`}>{j.filename}</Link></td><td><Badge v={j.status} /></td>
                  <td className="num">{j.committed_rows}/{j.total_rows}</td><td className="small">{fmtDateTime(j.created_at)}</td></tr>
              ))}
            </tbody></table></div>
          )}
        </section>
        <section className="card">
          <h2>Open flags</h2>
          {x.open_flags.total === 0 ? <Empty>No open flags.</Empty> : (
            <table><tbody>{Object.entries(x.open_flags.by_rule).map(([r, n]) => (
              <tr key={r}><td><Link to={`/issues?rule_id=${r}`}><code>{r}</code></Link></td><td className="num">{n as number}</td></tr>
            ))}</tbody></table>
          )}
          <h3 style={{ marginTop: 14 }}>Student correction requests</h3>
          {x.correction_requests.open === 0 ? <p className="muted small">None open.</p> : (
            <p><Link to="/corrections">{x.correction_requests.open} open</Link>{x.correction_requests.overdue > 0 && <> · <Badge v="ERROR">{x.correction_requests.overdue} overdue</Badge></>}</p>
          )}
        </section>
      </div>
      {confirm && (
        <Confirm title={`Declare ${confirm.programme_code} ${year} complete?`} confirmLabel="Declare submission complete" busy={busy}
          onCancel={() => setConfirm(null)} onConfirm={() => declare(confirm)}>
          <p>You confirm that all admitted students for {confirm.programme_code} in {year} are in the register
            ({confirm.within_intake_enrolled} within intake, {confirm.supernumerary_enrolled} supernumerary).</p>
          <p className="muted small">Changes after this declaration are still allowed but are visible to AICTE as late changes.</p>
        </Confirm>
      )}
    </div>
  );
}
