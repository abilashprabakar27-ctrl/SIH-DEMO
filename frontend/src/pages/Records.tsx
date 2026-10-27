import { FormEvent, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { useApi } from "../api";
import { useAuth } from "../App";
import { Apaar, Badge, ErrorBox, Loading, Pager } from "../components/ui";

export default function Records() {
  const { user } = useAuth();
  const [sp, setSp] = useSearchParams();
  const [q, setQ] = useState(sp.get("q") || "");
  const params = new URLSearchParams(sp);
  if (!params.get("page_size")) params.set("page_size", "25");
  const page = Number(sp.get("page") || 1);
  const r = useApi<any>(`/api/v1/enrolments?${params.toString()}`, [sp.toString()]);
  const insts = useApi<any[]>(user?.role.startsWith("AICTE") ? "/api/v1/institutions" : null);
  const set = (k: string, v: string) => {
    const n = new URLSearchParams(sp);
    if (v) n.set(k, v);
    else n.delete(k);
    if (k !== "page") n.delete("page");
    setSp(n);
  };
  const search = (e: FormEvent) => {
    e.preventDefault();
    set("q", q.trim());
  };
  const sort = sp.get("sort") || "name";
  const sortBy = (k: string) => set("sort", sort === k ? `-${k}` : k);
  const arrow = (k: string) => (sort === k ? " ▲" : sort === `-${k}` ? " ▼" : "");

  return (
    <div className="stack">
      <div className="pagehead"><div><h1>Student records</h1>
        <p className="muted">Search by name or roll number, or an exact 12-digit APAAR ID (partial APAAR search is not supported).</p></div></div>
      <section className="card">
        <form className="inline" onSubmit={search}>
          <div className="field" style={{ flex: "2 1 240px" }}><label htmlFor="q">Search</label>
            <input id="q" value={q} onChange={(e) => setQ(e.target.value)} placeholder="Name, roll number or full APAAR ID" /></div>
          {insts.data && (
            <div className="field"><label>Institution</label>
              <select value={sp.get("institution_id") || ""} onChange={(e) => set("institution_id", e.target.value)}>
                <option value="">All institutions</option>{insts.data.map((i) => <option key={i.id} value={i.id}>{i.name}</option>)}</select></div>
          )}
          <div className="field"><label>Year</label>
            <select value={sp.get("academic_year") || ""} onChange={(e) => set("academic_year", e.target.value)}>
              <option value="">All</option><option>2026-27</option><option>2025-26</option></select></div>
          <div className="field"><label>Programme code</label>
            <input value={sp.get("programme_code") || ""} onChange={(e) => set("programme_code", e.target.value)} style={{ width: 130 }} /></div>
          <div className="field"><label>Status</label>
            <select value={sp.get("status") || ""} onChange={(e) => set("status", e.target.value)}>
              <option value="">Any</option>{["ACTIVE", "PROVISIONAL", "WITHDRAWN", "TRANSFERRED_OUT", "GRADUATED", "CANCELLED"].map((s) => <option key={s}>{s}</option>)}</select></div>
          <div className="field"><label>APAAR check</label>
            <select value={sp.get("apaar_status") || ""} onChange={(e) => set("apaar_status", e.target.value)}>
              <option value="">Any</option>{["VERIFIED", "MISMATCH", "UNVERIFIED", "PENDING_EXEMPT"].map((s) => <option key={s}>{s}</option>)}</select></div>
          <button type="submit">Search records</button>
        </form>
      </section>
      <ErrorBox error={r.error} onRetry={() => r.reload()} />
      {r.loading && !r.data && <Loading what="Searching" />}
      {r.data && (
        <section className="card flat">
          <div className="tablewrap scrollbox"><table>
            <thead><tr>
              <th><button className="link" onClick={() => sortBy("name")}>Name{arrow("name")}</button></th>
              <th><button className="link" onClick={() => sortBy("roll")}>Roll{arrow("roll")}</button></th>
              <th>APAAR ID</th>
              <th><button className="link" onClick={() => sortBy("programme")}>Programme{arrow("programme")}</button></th>
              <th>Year</th><th>Seat</th>
              <th><button className="link" onClick={() => sortBy("status")}>Status{arrow("status")}</button></th>
              {user?.role.startsWith("AICTE") && <th>Institution</th>}
            </tr></thead>
            <tbody>
              {r.data.items.length === 0 && <tr><td colSpan={8} className="muted">No records match. Clear a filter or check the spelling.</td></tr>}
              {r.data.items.map((e: any) => (
                <tr key={e.id}>
                  <td><Link to={`/records/${e.id}`}>{e.student.full_name}</Link></td>
                  <td className="mono">{e.institution_student_id}</td>
                  <td><Apaar value={e.student.apaar_id} status={e.student.apaar_status} /></td>
                  <td>{e.programme_code}</td><td>{e.academic_year}</td><td className="small">{e.seat_category}</td>
                  <td><Badge v={e.status} /></td>
                  {user?.role.startsWith("AICTE") && <td className="small">{e.institution_name}</td>}
                </tr>
              ))}
            </tbody>
          </table></div>
          <Pager page={page} pageSize={25} total={r.data.total} onPage={(p) => set("page", String(p))} />
        </section>
      )}
    </div>
  );
}
