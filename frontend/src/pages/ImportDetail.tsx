import { useState } from "react";
import { Link, useParams } from "react-router-dom";
import { api, ApiError, download, useApi } from "../api";
import SeatStrip from "../components/SeatStrip";
import { Badge, Confirm, ErrorBox, Field, Finding, Findings, Loading, Pager, useToast } from "../components/ui";

const TABS = ["ALL", "ERROR", "REVIEW", "WARNING", "VALID", "COMMITTED", "EXCLUDED"];
const FIELDS: [string, string, string[]?][] = [
  ["apaar_id", "APAAR ID"], ["institution_student_id", "Roll number"], ["full_name", "Full name"],
  ["date_of_birth", "Date of birth (YYYY-MM-DD)"], ["gender", "Gender", ["M", "F", "T", "O"]],
  ["nationality_status", "Nationality status", ["INDIAN", "NRI", "OCI", "FN"]], ["citizenship_country", "Citizenship country"],
  ["programme_code", "Programme code"], ["academic_year", "Academic year"],
  ["seat_category", "Seat category", ["REGULAR", "NRI", "SN_FN_OCI", "SN_CIWG", "SN_TFW", "SN_OTHER"]],
  ["admission_date", "Admission date"], ["social_category", "Social category", ["", "GEN", "EWS", "OBC", "SC", "ST"]],
  ["email", "Email"], ["apaar_pending_reason", "APAAR pending reason", ["", "FOREIGN_NATIONAL", "APPLIED_AWAITING_ID", "OTHER_DOCUMENTED"]],
];

export default function ImportDetail() {
  const { id } = useParams();
  const [tab, setTab] = useState("ALL");
  const [page, setPage] = useState(1);
  const q = tab === "ALL" ? "" : `&status=${tab}`;
  const job = useApi<any>(`/api/v1/imports/${id}?page=${page}&page_size=50${q}`, [tab, page]);
  const [editing, setEditing] = useState<any>(null);
  const [draft, setDraft] = useState<Record<string, string>>({});
  const [busy, setBusy] = useState(false);
  const [confirm, setConfirm] = useState(false);
  const [bulk, setBulk] = useState({ field: "programme_code", from: "", to: "" });
  const [toast, show] = useToast();
  const [err, setErr] = useState<ApiError | null>(null);

  if (job.loading && !job.data) return <Loading what="Loading upload" />;
  if (job.error) return <ErrorBox error={job.error} onRetry={() => job.reload()} />;
  const j = job.data;
  const c = j.summary.counts || {};
  const locked = ["COMMITTED", "DISCARDED", "COMMITTING"].includes(j.status);

  async function run(fn: () => Promise<any>, ok?: string) {
    setBusy(true);
    setErr(null);
    try {
      const r = await fn();
      if (ok) show(ok);
      await job.reload(true);
      return r;
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }

  function startEdit(row: any) {
    setEditing(row);
    setDraft({ ...row.data });
  }
  async function saveEdit() {
    const changes: Record<string, string> = {};
    for (const [k] of FIELDS) if ((draft[k] ?? "") !== (editing.data[k] ?? "")) changes[k] = draft[k] ?? "";
    if (!Object.keys(changes).length) return setEditing(null);
    const r = await run(() => api(`/api/v1/imports/${id}/rows/${editing.row_no}`, { method: "PATCH", body: { changes } }));
    if (r) {
      setEditing(r.row.status === "VALID" ? null : r.row);
      setDraft({ ...r.row.data });
      show(`Row ${r.row.spreadsheet_row} is now ${r.row.status}.`);
    }
  }
  const useSuggestion = (row: any) => (f: Finding) =>
    run(() => api(`/api/v1/imports/${id}/rows/${row.row_no}`, { method: "PATCH", body: { changes: { [f.suggestion!.field]: f.suggestion!.value } } }),
      `Row ${row.spreadsheet_row}: APAAR ID replaced with the suggestion.`);
  const exclude = (row: any, excluded: boolean) =>
    run(() => api(`/api/v1/imports/${id}/rows/${row.row_no}/exclude`, { body: { excluded } }),
      excluded ? `Row ${row.spreadsheet_row} left out of this upload.` : `Row ${row.spreadsheet_row} restored.`);

  async function commit() {
    const r = await run(() => api(`/api/v1/imports/${id}/commit`, { method: "POST" }));
    setConfirm(false);
    if (r) show(r.message);
  }
  const flagged = new Set((editing?.findings || []).filter((f: Finding) => f.severity === "ERROR" || f.severity === "REVIEW").map((f: Finding) => f.field));
  const committable = j.summary.committable || 0;

  return (
    <div className="stack">
      <div className="pagehead">
        <div>
          <h1>{j.filename}</h1>
          <p className="muted">{j.academic_year} · <Badge v={j.status} /> · {j.total_rows} rows · {j.committed_rows} committed</p>
        </div>
        <div className="row">
          <button className="secondary" onClick={() => download(`/api/v1/imports/${id}/report.csv`, "check_report.csv").catch(setErr)}>Download check report (CSV)</button>
          {!locked && <button className="secondary" onClick={() => run(() => api(`/api/v1/imports/${id}/discard`, { method: "POST" }), "Upload discarded.")}>Discard upload</button>}
          {!locked && <button disabled={!committable || busy} onClick={() => setConfirm(true)}>Commit {committable} row{committable === 1 ? "" : "s"}</button>}
        </div>
      </div>
      {toast}
      <ErrorBox error={err} />
      {(j.summary.file_findings || []).map((f: Finding, i: number) => <div key={i} className="banner warn"><code>{f.rule_id}</code> {f.message}</div>)}
      {j.status === "COMMITTED" && <div className="banner ok">All rows are committed or left out. <Link to="/inst">Back to dashboard</Link></div>}
      <div className="figs">
        {["VALID", "WARNING", "REVIEW", "ERROR", "COMMITTED", "EXCLUDED"].map((s) => (
          <div className={`fig ${s === "ERROR" && c[s] ? "bad" : s === "REVIEW" && c[s] ? "warn" : ""}`} key={s}><div className="k">{s.toLowerCase()}</div><div className="v">{c[s] ?? 0}</div></div>
        ))}
      </div>
      {(j.summary.projection || []).length > 0 && (
        <section className="card">
          <h2>What committing will do to seat positions</h2>
          {j.summary.projection.map((p: any) => (
            <div key={p.programme_id} className="grid g2" style={{ borderTop: "1px solid var(--line-2)", paddingTop: 10, marginTop: 10 }}>
              <div><strong>{p.programme_code}</strong> now<SeatStrip pos={p.current} compact /></div>
              <div><strong>{p.programme_code}</strong> after commit ({p.change_within_intake >= 0 ? "+" : ""}{p.change_within_intake} within intake)
                <SeatStrip pos={p.after} />
                <p className={p.exceeds ? "" : "muted small"} style={p.exceeds ? { color: "var(--red)", fontWeight: 700 } : {}}>{p.message}</p></div>
            </div>
          ))}
        </section>
      )}
      {!locked && (
        <section className="card">
          <h3>Fix the same problem in every row</h3>
          <div className="inline">
            <Field label="Field"><select value={bulk.field} onChange={(e) => setBulk({ ...bulk, field: e.target.value })}>{FIELDS.map(([k, l]) => <option key={k} value={k}>{l}</option>)}</select></Field>
            <Field label="Current value"><input value={bulk.from} onChange={(e) => setBulk({ ...bulk, from: e.target.value })} /></Field>
            <Field label="Replace with"><input value={bulk.to} onChange={(e) => setBulk({ ...bulk, to: e.target.value })} /></Field>
            <button className="secondary" disabled={busy || !bulk.to} onClick={async () => {
              const r = await run(() => api(`/api/v1/imports/${id}/bulk-fix`, { body: bulk }));
              if (r) show(`Updated ${r.updated_rows} row(s).`);
            }}>Apply to all matching rows</button>
          </div>
        </section>
      )}
      <section className="card flat">
        <div className="tabs" role="tablist" style={{ padding: "0 10px" }}>
          {TABS.map((t) => <button key={t} role="tab" aria-selected={tab === t} className={tab === t ? "on" : ""} onClick={() => { setTab(t); setPage(1); }}>
            {t === "ALL" ? "All rows" : t.toLowerCase()} {t !== "ALL" && `(${c[t] ?? 0})`}</button>)}
        </div>
        <div className="tablewrap scrollbox">
          <table>
            <thead><tr><th>Row</th><th>Status</th><th>Roll</th><th>Name</th><th>Programme</th><th>Seat</th><th>Findings and how to fix</th><th></th></tr></thead>
            <tbody>
              {j.rows.length === 0 && <tr><td colSpan={8} className="muted">No rows with this status.</td></tr>}
              {j.rows.map((r: any) => (
                <tr key={r.row_no} className={editing?.row_no === r.row_no ? "sel" : ""}>
                  <td className="num">{r.spreadsheet_row}</td><td><Badge v={r.status} />{r.corrected && <div className="small muted">corrected</div>}</td>
                  <td className="mono">{r.data.institution_student_id}</td><td>{r.data.full_name}</td><td>{r.data.programme_code}</td><td className="small">{r.data.seat_category}</td>
                  <td style={{ minWidth: 280 }}><Findings items={r.findings} onUseSuggestion={!locked && r.status !== "COMMITTED" ? useSuggestion(r) : undefined} /></td>
                  <td style={{ whiteSpace: "nowrap" }}>
                    {!locked && !["COMMITTED", "EXCLUDED"].includes(r.status) && <>
                      <button className="small secondary" onClick={() => startEdit(r)}>Edit row</button>{" "}
                      <button className="small secondary" onClick={() => exclude(r, true)}>Leave out</button></>}
                    {!locked && r.status === "EXCLUDED" && <button className="small secondary" onClick={() => exclude(r, false)}>Restore</button>}
                    {r.enrolment_id && <Link className="small" to={`/records/${r.enrolment_id}`}>Record</Link>}
                  </td>
                </tr>
              ))}
            </tbody>
          </table>
        </div>
        <Pager page={page} pageSize={50} total={j.total} onPage={setPage} />
      </section>
      {editing && (
        <section className="card" aria-label="Edit row">
          <div className="row between"><h2>Edit spreadsheet row {editing.spreadsheet_row}</h2><button className="secondary small" onClick={() => setEditing(null)}>Close editor</button></div>
          <Findings items={editing.findings} onUseSuggestion={useSuggestion(editing)} />
          <div className="grid g3" style={{ marginTop: 12 }}>
            {FIELDS.map(([k, label, opts]) => (
              <Field key={k} label={label} flagged={flagged.has(k)}>
                {opts ? (
                  <select value={draft[k] ?? ""} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })}>
                    {!opts.includes(draft[k] ?? "") && <option value={draft[k]}>{draft[k]} (invalid)</option>}
                    {opts.map((o) => <option key={o} value={o}>{o || "(blank)"}</option>)}
                  </select>
                ) : <input value={draft[k] ?? ""} onChange={(e) => setDraft({ ...draft, [k]: e.target.value })} />}
              </Field>
            ))}
          </div>
          <button onClick={saveEdit} disabled={busy}>{busy ? "Checking…" : "Save and re-check row"}</button>
        </section>
      )}
      {confirm && (
        <Confirm title={`Commit ${committable} rows to the register?`} confirmLabel={`Commit ${committable} rows`} busy={busy}
          onCancel={() => setConfirm(false)} onConfirm={commit}>
          <p>{c.VALID ?? 0} valid, {c.WARNING ?? 0} with warnings and {c.REVIEW ?? 0} needing review will be saved.
            {c.REVIEW ? ` ${c.REVIEW} flag(s) will open for AICTE review.` : ""}</p>
          {(c.ERROR ?? 0) > 0 && <p>{c.ERROR} row(s) with errors stay here for you to fix and commit later.</p>}
          {(j.summary.projection || []).some((p: any) => p.exceeds) && <p style={{ color: "var(--red)", fontWeight: 700 }}>Committing will exceed approved capacity. Records are still accepted and AICTE is flagged.</p>}
        </Confirm>
      )}
    </div>
  );
}
