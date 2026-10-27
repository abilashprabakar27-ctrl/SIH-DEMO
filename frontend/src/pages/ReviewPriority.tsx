import { useState } from "react";
import { ApiError, CURRENT_YEAR, download, useApi, YEARS } from "../api";
import { Badge, ErrorBox, Loading } from "../components/ui";

export default function ReviewPriority() {
  const [year, setYear] = useState(CURRENT_YEAR);
  const d = useApi<any>(`/api/v1/dashboard/review-priority?academic_year=${year}`, [year]);
  const [open, setOpen] = useState<string | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  if (d.loading && !d.data) return <Loading />;
  if (d.error) return <ErrorBox error={d.error} onRetry={() => d.reload()} />;
  return (
    <div className="stack">
      <div className="pagehead"><div><h1>Review priority</h1><p className="muted">Where to look first, with the reason for every point.</p></div>
        <div className="row">
          <select aria-label="Academic year" style={{ width: "auto" }} value={year} onChange={(e) => setYear(e.target.value)}>{YEARS.map((y) => <option key={y}>{y}</option>)}</select>
          <button className="secondary" onClick={() => download(`/api/v1/reports/review-priority.csv?academic_year=${year}`, `review_priority_${year}.csv`).catch(setErr)}>Download CSV</button>
        </div></div>
      <div className="banner warn"><strong>{d.data.disclaimer}</strong></div>
      <ErrorBox error={err} />
      {d.data.items.map((r: any) => (
        <section className="card" key={r.institution_id}>
          <div className="row between">
            <div><strong>{r.institution_name}</strong> <span className="muted small">{r.aicte_code} · {r.state} · {r.institution_type.toLowerCase()}</span></div>
            <div className="row"><span style={{ fontSize: 22, fontWeight: 700 }}>{r.score}</span><Badge v={r.band}>{r.band.toLowerCase()} priority</Badge></div>
          </div>
          {r.signals.length === 0 ? <p className="muted small">No signals.</p> : (
            <table style={{ marginTop: 8 }}><tbody>{r.signals.map((s: any) => (
              <tr key={s.key}><td className="num" style={{ width: 50 }}><strong>+{s.points}</strong></td><td><strong>{s.label}</strong><div className="small">{s.sentence}</div></td></tr>
            ))}</tbody></table>
          )}
          <button className="link small" onClick={() => setOpen(open === r.institution_id ? null : r.institution_id)} aria-expanded={open === r.institution_id}>
            {open === r.institution_id ? "Hide" : "Show"} peer statistics</button>
          {open === r.institution_id && (
            <div className="small" style={{ marginTop: 6 }}>
              <p className="muted">Compared with {r.peer_basis}. Robust z-score = (value − median) ÷ (1.4826 × MAD); |z| above 3.5 adds 8 points.</p>
              <table><thead><tr><th>Measure</th><th className="num">This institution</th><th className="num">Peer median</th><th className="num">Robust z</th></tr></thead>
                <tbody>{r.peer_stats.map((p: any) => (
                  <tr key={p.metric}><td>{p.label}</td><td className="num">{(p.value * 100).toFixed(1)}%</td><td className="num">{(p.peer_median * 100).toFixed(1)}%</td>
                    <td className="num">{p.z === null ? "n/a (no spread)" : p.z}</td></tr>))}</tbody></table>
            </div>
          )}
        </section>
      ))}
    </div>
  );
}
