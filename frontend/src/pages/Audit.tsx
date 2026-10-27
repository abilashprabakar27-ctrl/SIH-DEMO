import { useState } from "react";
import { api, ApiError, download, fmtDateTime, useApi } from "../api";
import { Badge, ErrorBox, Loading, Pager } from "../components/ui";

export default function Audit() {
  const [f, setF] = useState({ action: "", outcome: "", actor_role: "" });
  const [page, setPage] = useState(1);
  const q = new URLSearchParams({ ...f, page: String(page), page_size: "50" }).toString();
  const r = useApi<any>(`/api/v1/audit?${q}`, [q]);
  const [chain, setChain] = useState<any>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const set = (k: string, v: string) => { setF({ ...f, [k]: v }); setPage(1); };
  async function verify() {
    setErr(null);
    try {
      setChain(await api("/api/v1/audit/verify-chain"));
    } catch (e) {
      setErr(e as ApiError);
    }
  }
  return (
    <div className="stack">
      <div className="pagehead"><div><h1>Audit trail</h1><p className="muted">Every write, sign-in, export and denied access, in a hash chain: each event's hash covers the one before it. APAAR IDs appear only as pseudonyms.</p></div>
        <div className="row"><button onClick={verify}>Verify chain integrity</button>
          <button className="secondary" onClick={() => download("/api/v1/audit/export.csv", "audit.csv").catch(setErr)}>Export (CSV)</button></div></div>
      <ErrorBox error={err} />
      {chain && (chain.valid
        ? <div className="banner ok">Chain intact: {chain.events_checked} events verified. Head hash <code>{chain.head_hash?.slice(0, 16)}…</code></div>
        : <div className="banner error">Chain broken at event #{chain.first_broken_seq}. {chain.events_checked} events before it verified. That event or an earlier one was altered or removed.</div>)}
      <section className="card inline">
        <div className="field"><label>Action starts with</label><input value={f.action} onChange={(e) => set("action", e.target.value)} placeholder="e.g. import." /></div>
        <div className="field"><label>Outcome</label><select value={f.outcome} onChange={(e) => set("outcome", e.target.value)}>
          <option value="">Any</option><option>SUCCESS</option><option>DENIED</option><option>FAILED</option></select></div>
        <div className="field"><label>Actor role</label><select value={f.actor_role} onChange={(e) => set("actor_role", e.target.value)}>
          <option value="">Any</option>{["AICTE_ADMIN", "AICTE_ANALYST", "INST_ADMIN", "INST_STAFF", "VERIFIER", "STUDENT", "AUDITOR", "INTEGRATION_CLIENT", "ANONYMOUS"].map((x) => <option key={x}>{x}</option>)}</select></div>
      </section>
      {r.loading && !r.data && <Loading />}
      {r.data && (
        <section className="card flat"><div className="tablewrap scrollbox"><table>
          <thead><tr><th className="num">#</th><th>When</th><th>Actor</th><th>Action</th><th>Entity</th><th>Outcome</th><th>Detail</th><th>Hash</th></tr></thead>
          <tbody>{r.data.items.map((e: any) => (
            <tr key={e.seq}><td className="num">{e.seq}</td><td className="small">{fmtDateTime(e.at)}</td><td className="small">{e.actor_role || "—"}</td>
              <td><code>{e.action}</code></td><td className="small">{e.entity_type}</td><td><Badge v={e.outcome === "SUCCESS" ? "VALID" : e.outcome === "DENIED" ? "ERROR" : "WARNING"}>{e.outcome}</Badge></td>
              <td className="small mono" style={{ maxWidth: 280, overflow: "hidden", textOverflow: "ellipsis", whiteSpace: "nowrap" }} title={JSON.stringify(e.detail)}>{JSON.stringify(e.detail)}</td>
              <td className="mono small">{e.hash.slice(0, 10)}…</td></tr>))}</tbody></table></div>
          <Pager page={page} pageSize={50} total={r.data.total} onPage={setPage} /></section>
      )}
    </div>
  );
}
