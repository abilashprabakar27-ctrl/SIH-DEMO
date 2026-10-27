import { useState } from "react";
import { api, ApiError, CURRENT_YEAR, useApi, YEARS } from "../api";
import { ErrorBox, Loading, useToast } from "../components/ui";

const CATS = ["SN_FN_OCI", "SN_CIWG", "SN_TFW", "SN_OTHER"];

export default function IntakeAdmin() {
  const [year, setYear] = useState(CURRENT_YEAR);
  const [inst, setInst] = useState("");
  const insts = useApi<any[]>("/api/v1/institutions");
  const progs = useApi<any[]>(`/api/v1/programmes?academic_year=${year}${inst ? `&institution_id=${inst}` : ""}`, [year, inst]);
  const rules = useApi<any[]>("/api/v1/rule-sets");
  const [edit, setEdit] = useState<Record<string, { intake: string; ref: string }>>({});
  const [cap, setCap] = useState<{ intakeId: string; cat: string; seats: string; source: string } | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [impact, setImpact] = useState<any>(null);
  const [activationReason, setActivationReason] = useState("");
  const [toast, show] = useToast();

  async function saveIntake(p: any) {
    const e = edit[p.id];
    setErr(null);
    try {
      const r = await api<any>("/api/v1/intakes", { body: { programme_id: p.id, academic_year: year,
        approved_intake: Number(e.intake), approval_reference: e.ref } });
      show(`${p.code} ${year}: intake set to ${r.approved_intake}. Default caps re-derived and capacity checks re-run.`);
      setEdit({ ...edit, [p.id]: undefined as any });
      progs.reload(true);
    } catch (ex) {
      setErr(ex as ApiError);
    }
  }
  async function saveCap() {
    if (!cap) return;
    setErr(null);
    try {
      await api(`/api/v1/intakes/${cap.intakeId}/quotas/${cap.cat}`, { method: "PATCH", body: { cap_seats: Number(cap.seats), rule_source: cap.source } });
      show(`${cap.cat} cap set to ${cap.seats}. Capacity checks re-run.`);
      setCap(null);
      progs.reload(true);
    } catch (ex) {
      setErr(ex as ApiError);
    }
  }
  async function previewImpact(ruleSet: any) {
    setErr(null);
    try {
      const result = await api<any>(`/api/v1/rule-sets/${ruleSet.id}/impact`, { method: "POST" });
      setImpact({ ruleSet, result });
      setActivationReason("");
    } catch (ex) { setErr(ex as ApiError); }
  }
  async function activateRuleSet() {
    if (!impact || activationReason.trim().length < 5) return;
    setErr(null);
    try {
      await api(`/api/v1/rule-sets/${impact.ruleSet.id}/activate`, { method: "POST", body: { reason: activationReason } });
      show(`${impact.ruleSet.code} v${impact.ruleSet.version} activated. Unlocked programme caps were recalculated and reviewed.`);
      setImpact(null);
      rules.reload(true);
      progs.reload(true);
    } catch (ex) { setErr(ex as ApiError); }
  }
  return (
    <div className="stack">
      <div className="pagehead"><div><h1>Intake and caps</h1>
        <p className="muted">Approved intake per programme-year. Supernumerary caps are derived from intake with their rule source; a cap set here is kept when intake changes.</p></div>
        <div className="row">
          <select aria-label="Institution" style={{ width: "auto" }} value={inst} onChange={(e) => setInst(e.target.value)}>
            <option value="">All institutions</option>{insts.data?.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}</select>
          <select aria-label="Academic year" style={{ width: "auto" }} value={year} onChange={(e) => setYear(e.target.value)}>{YEARS.map((y) => <option key={y}>{y}</option>)}</select>
        </div></div>
      {toast}
      <ErrorBox error={err || progs.error || rules.error} />
      <section className="card flat">
        <h2>Versioned capacity rules</h2>
        <p className="muted">Sources and effective years are recorded with each version. “Unverified” means the source still needs confirmation.</p>
        {rules.loading && !rules.data ? <Loading /> : <div className="tablewrap scrollbox"><table>
          <thead><tr><th>Rule set</th><th>Academic years</th><th>Source</th><th>Status</th><th></th></tr></thead>
          <tbody>{rules.data?.map((rs: any) => <tr key={rs.id}>
            <td><strong>{rs.code} v{rs.version}</strong><div className="small muted">{rs.verification_status.toLowerCase()}</div></td>
            <td>{rs.academic_year_from}–{rs.academic_year_to}</td><td className="small">{rs.source_type}: {rs.source_ref}</td>
            <td>{rs.status}</td><td>{rs.status === "DRAFT" && <button className="small secondary" onClick={() => previewImpact(rs)}>Preview impact</button>}</td>
          </tr>)}</tbody>
        </table></div>}
      </section>
      {impact && <section className="card">
        <h2>Impact preview: {impact.ruleSet.code} v{impact.ruleSet.version}</h2>
        <p>This activation will supersede any overlapping active rule set and recalculate unlocked programme-years. Overridden caps stay in place. The source status is {impact.ruleSet.verification_status.toLowerCase()}.</p>
        <p><strong>{impact.result.programmes.length}</strong> programme-years change. Review each proposed cap and any signal that opens or closes before activating.</p>
        <div className="tablewrap scrollbox"><table><thead><tr><th>Programme</th><th>Year</th><th>Cap changes</th><th>Flags</th></tr></thead>
          <tbody>{impact.result.programmes.map((p: any) => <tr key={`${p.programme_id}-${p.academic_year}`}>
            <td>{p.programme_code}</td><td>{p.academic_year}</td>
            <td>{Object.entries(p.changes).map(([cat, values]: [string, any]) => `${cat}: ${values.current} → ${values.proposed}`).join("; ")}</td>
            <td>{p.locked ? "Locked year, unchanged" : p.flags_open ? "A capacity signal may open" : p.flags_close ? "A capacity signal may close" : "No flag-state change"}</td>
          </tr>)}</tbody></table></div>
        <div className="inline" style={{ marginTop: 16 }}>
          <div className="field" style={{ flex: "1 1 320px" }}><label>Reason for activation</label><input value={activationReason} onChange={(e) => setActivationReason(e.target.value)} /></div>
          <button disabled={activationReason.trim().length < 5} onClick={activateRuleSet}>Activate rule set</button>
          <button className="secondary" onClick={() => setImpact(null)}>Cancel</button>
        </div>
      </section>}
      {progs.loading && !progs.data && <Loading />}
      {progs.data && (
        <section className="card flat"><div className="tablewrap scrollbox"><table>
          <thead><tr><th>Institution</th><th>Programme</th><th className="num">Approved intake</th>{CATS.map((c) => <th key={c}>{c.replace("SN_", "").replace("_", "/")} cap</th>)}<th></th></tr></thead>
          <tbody>{progs.data.map((p) => {
            const e = edit[p.id];
            const q = Object.fromEntries((p.intake?.quotas || []).map((x: any) => [x.seat_category, x]));
            return (
              <tr key={p.id}>
                <td className="small">{p.institution_name}</td><td><strong>{p.code}</strong><div className="small muted">{p.level} · {p.discipline.toLowerCase()}</div></td>
                <td className="num">{e ? (
                  <div className="stack" style={{ minWidth: 180 }}>
                    <input aria-label="Approved intake" type="number" min={0} value={e.intake} onChange={(ev) => setEdit({ ...edit, [p.id]: { ...e, intake: ev.target.value } })} />
                    <input aria-label="Approval reference" value={e.ref} onChange={(ev) => setEdit({ ...edit, [p.id]: { ...e, ref: ev.target.value } })} placeholder="Approval reference" />
                  </div>) : p.intake ? p.intake.approved_intake : <span className="muted">not set</span>}</td>
                {CATS.map((c) => (
                  <td key={c} className="small" title={q[c]?.rule_source}>{p.intake ? (
                    <button className="link" onClick={() => setCap({ intakeId: p.intake.id, cat: c, seats: String(q[c]?.cap_seats ?? 0), source: "" })}>
                      {q[c]?.cap_seats ?? 0}{q[c]?.rule_source?.startsWith("CONFIGURED") ? " (set)" : ""}</button>) : "—"}</td>
                ))}
                <td style={{ whiteSpace: "nowrap" }}>{e ? (<>
                  <button className="small" disabled={e.ref.trim().length < 3 || e.intake === ""} onClick={() => saveIntake(p)}>Save intake</button>{" "}
                  <button className="small secondary" onClick={() => setEdit({ ...edit, [p.id]: undefined as any })}>Cancel</button></>) : (
                  <button className="small secondary" onClick={() => setEdit({ ...edit, [p.id]: { intake: String(p.intake?.approved_intake ?? ""), ref: p.intake?.approval_reference ?? "" } })}>
                    {p.intake ? "Change intake" : "Set intake"}</button>)}</td>
              </tr>
            );
          })}</tbody></table></div></section>
      )}
      {cap && (
        <section className="card">
          <h2>Set {cap.cat} cap</h2>
          <div className="inline">
            <div className="field"><label>Cap (seats)</label><input type="number" min={0} value={cap.seats} onChange={(e) => setCap({ ...cap, seats: e.target.value })} style={{ width: 120 }} /></div>
            <div className="field" style={{ flex: "1 1 320px" }}><label>Rule source (recorded with the cap)</label><input value={cap.source} onChange={(e) => setCap({ ...cap, source: e.target.value })} placeholder="e.g. AICTE approval letter ref …" /></div>
            <button disabled={cap.source.trim().length < 5} onClick={saveCap}>Save cap</button>
            <button className="secondary" onClick={() => setCap(null)}>Cancel</button>
          </div>
        </section>
      )}
    </div>
  );
}
