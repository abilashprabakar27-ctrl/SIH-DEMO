import { useState } from "react";
import { api, ApiError, CURRENT_YEAR, useApi, YEARS } from "../api";
import { ErrorBox, Loading, useToast } from "../components/ui";

const CATS = ["SN_FN_OCI", "SN_CIWG", "SN_TFW", "SN_OTHER"];

export default function IntakeAdmin() {
  const [year, setYear] = useState(CURRENT_YEAR);
  const [inst, setInst] = useState("");
  const insts = useApi<any[]>("/api/v1/institutions");
  const progs = useApi<any[]>(`/api/v1/programmes?academic_year=${year}${inst ? `&institution_id=${inst}` : ""}`, [year, inst]);
  const [edit, setEdit] = useState<Record<string, { intake: string; ref: string }>>({});
  const [cap, setCap] = useState<{ intakeId: string; cat: string; seats: string; source: string } | null>(null);
  const [err, setErr] = useState<ApiError | null>(null);
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
      <ErrorBox error={err || progs.error} />
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
