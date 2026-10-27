import { useState } from "react";
import { Link } from "react-router-dom";
import { CURRENT_YEAR, fmtDate, useApi, useLiveEvents, YEARS } from "../api";
import SeatStrip, { SeatLegend } from "../components/SeatStrip";
import { Badge, Empty, ErrorBox, Figure, Loading } from "../components/ui";

const NAT_LABEL: Record<string, string> = { INDIAN: "Indian", NRI: "NRI", OCI: "OCI / PIO", FN: "Foreign national" };

function Bars({ rows }: { rows: { label: string; value: number; max: number; over?: boolean; note?: string }[] }) {
  return (
    <table><tbody>{rows.map((r) => (
      <tr key={r.label}><td style={{ width: "34%" }}>{r.label}</td>
        <td><div className={`bar${r.over ? " over" : ""}`} role="img" aria-label={`${r.label}: ${r.value}`}>
          <span style={{ width: `${r.max ? Math.min(100, (100 * r.value) / r.max) : 0}%` }} /></div></td>
        <td className="num" style={{ width: 110 }}>{r.value}{r.note ? <span className="muted small"> {r.note}</span> : null}</td></tr>
    ))}</tbody></table>
  );
}

export default function National() {
  const [year, setYear] = useState(CURRENT_YEAR);
  const [state, setState] = useState("");
  const [disc, setDisc] = useState("");
  const d = useApi<any>(`/api/v1/dashboard/national?academic_year=${year}&state=${encodeURIComponent(state)}&discipline=${disc}`, [year, state, disc]);
  const [updated, setUpdated] = useState<string | null>(null);
  const live = useLiveEvents(() => { d.reload(true); setUpdated(new Date().toLocaleTimeString()); });
  if (d.loading && !d.data) return <Loading what="Loading national register" />;
  if (d.error) return <ErrorBox error={d.error} onRetry={() => d.reload()} />;
  const x = d.data;
  const f = x.figures;
  const natTotal = Object.values(x.nationality as Record<string, number>).reduce((a, b) => a + b, 0);
  const cov = x.apaar_coverage.by_status as Record<string, number>;
  const covTotal = Object.values(cov).reduce((a, b) => a + b, 0);
  const maxState = Math.max(1, ...x.by_state.map((s: any) => Math.max(s.approved_intake, s.within_intake_enrolled)));
  return (
    <div className="stack">
      <div className="pagehead">
        <div><h1>National register</h1><p className="muted">All figures computed from student-level records. Academic year {year}.</p></div>
        <div className="row">
          <span className="live">{live ? "● Live" : "○ Connecting"}{updated && ` · updated ${updated}`}</span>
          <select aria-label="Academic year" style={{ width: "auto" }} value={year} onChange={(e) => setYear(e.target.value)}>{YEARS.map((y) => <option key={y}>{y}</option>)}</select>
          <select aria-label="State" style={{ width: "auto" }} value={state} onChange={(e) => setState(e.target.value)}><option value="">All states</option>{x.states.map((s: string) => <option key={s}>{s}</option>)}</select>
          <select aria-label="Discipline" style={{ width: "auto" }} value={disc} onChange={(e) => setDisc(e.target.value)}>
            <option value="">All disciplines</option><option value="ENGINEERING">Engineering</option><option value="MANAGEMENT">Management</option><option value="COMPUTER_APPLICATIONS">Computer applications</option></select>
        </div>
      </div>
      <div className="figs">
        <Figure k="Institutions" v={f.institutions} />
        <Figure k="Programmes" v={f.programmes} />
        <Figure k="Approved intake" v={f.approved_intake} />
        <Figure k="Within intake (regular + NRI)" v={f.within_intake_enrolled} />
        <Figure k="Utilisation" v={f.utilisation_pct != null ? `${f.utilisation_pct}%` : "—"} />
        <Figure k="Supernumerary" v={f.supernumerary_enrolled} />
        <Figure k="Seats over intake" v={f.excess_over_intake} tone={f.excess_over_intake ? "bad" : undefined} />
        <Figure k="Programmes over a cap" v={f.programmes_over_cap} tone={f.programmes_over_cap ? "bad" : undefined} />
      </div>
      <section className="card">
        <div className="row between"><h2>Excess alerts</h2><SeatLegend /></div>
        {x.excess_alerts.length === 0 ? <Empty>No programme is over intake or over a supernumerary cap.</Empty> : x.excess_alerts.map((p: any) => (
          <div key={p.programme_id} style={{ borderTop: "1px solid var(--line-2)", paddingTop: 10, marginTop: 10 }}>
            <div className="row between"><strong>{p.institution_name} · {p.programme_code}</strong>
              <Link className="small" to={`/issues?rule_id=C001_EXCESS_INTAKE,C002_SUPERNUMERARY_CAP`}>See flags</Link></div>
            <SeatStrip pos={p} />
          </div>
        ))}
      </section>
      <div className="grid g2">
        <section className="card"><h2>By state (within intake vs approved)</h2>
          <Bars rows={x.by_state.map((s: any) => ({ label: s.state, value: s.within_intake_enrolled, max: maxState, over: s.excess_over_intake > 0, note: `/ ${s.approved_intake}` }))} /></section>
        <section className="card"><h2>Nationality</h2>
          <Bars rows={Object.entries(x.nationality).map(([k, v]) => ({ label: NAT_LABEL[k] || k, value: v as number, max: natTotal }))} /></section>
        <section className="card"><h2>APAAR coverage <Badge v="SIMULATED" /></h2>
          <p className="small muted">{x.apaar_coverage.verified_pct ?? "—"}% of enrolled students have an APAAR ID that matched the (simulated) registry.</p>
          <Bars rows={Object.entries(cov).map(([k, v]) => ({ label: k.replace("_", " ").toLowerCase(), value: v, max: covTotal }))} /></section>
        <section className="card"><h2>Open flags by rule</h2>
          {Object.keys(x.open_flags_by_rule).length === 0 ? <p className="muted">None.</p> : (
            <table><tbody>{Object.entries(x.open_flags_by_rule).map(([r, n]) => (
              <tr key={r}><td><Link to={`/issues?rule_id=${r}`}><code>{r}</code></Link></td><td className="num">{n as number}</td></tr>))}</tbody></table>)}</section>
      </div>
      <section className="card"><h2>Submission status</h2>
        <table><thead><tr><th>Institution</th><th>Code</th><th className="num">Programmes declared</th><th>Status</th></tr></thead><tbody>
          {x.submission_status.map((s: any) => (
            <tr key={s.institution_id}><td>{s.institution_name}</td><td className="mono">{s.aicte_code}</td><td className="num">{s.submitted}/{s.programmes}</td>
              <td>{s.complete ? <Badge v="COMMITTED">Complete</Badge> : <Badge v="PREVIEW">Open</Badge>}</td></tr>))}
        </tbody></table></section>
      <section className="card flat"><div style={{ padding: 16, paddingBottom: 0 }}><h2>Programmes</h2></div>
        <div className="tablewrap"><table>
          <thead><tr><th>Institution</th><th>Programme</th><th className="num">Intake</th><th className="num">Regular</th><th className="num">NRI</th>
            <th className="num">Over intake</th><th className="num">Utilisation</th><th>FN/OCI</th><th>CIWG</th><th>TFW</th><th>Declared</th></tr></thead>
          <tbody>{x.programmes.map((p: any) => (
            <tr key={p.programme_id}><td className="small">{p.institution_name}</td><td>{p.programme_code}</td><td className="num">{p.approved_intake}</td>
              <td className="num">{p.regular}</td><td className="num">{p.nri}</td>
              <td className="num" style={p.excess_over_intake ? { color: "var(--red)", fontWeight: 700 } : {}}>{p.excess_over_intake || "—"}</td>
              <td className="num">{p.utilisation_pct ?? "—"}%</td>
              {["SN_FN_OCI", "SN_CIWG", "SN_TFW"].map((c) => <td key={c} className="small" style={p.supernumerary[c].excess ? { color: "var(--red)", fontWeight: 700 } : {}}>{p.supernumerary[c].enrolled}/{p.supernumerary[c].cap}</td>)}
              <td className="small">{p.submitted_at ? fmtDate(p.submitted_at) : "—"}</td></tr>))}
          </tbody></table></div></section>
    </div>
  );
}
