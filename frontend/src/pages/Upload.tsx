import { FormEvent, useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, CURRENT_YEAR, download, fmtDateTime, useApi, YEARS } from "../api";
import { Badge, ErrorBox, Field } from "../components/ui";

export default function Upload() {
  const nav = useNavigate();
  const [year, setYear] = useState(CURRENT_YEAR);
  const [file, setFile] = useState<File | null>(null);
  const [err, setErr] = useState<ApiError | Error | null>(null);
  const [busy, setBusy] = useState(false);
  const jobs = useApi<any[]>("/api/v1/imports");

  async function submit(e: FormEvent) {
    e.preventDefault();
    if (!file) return;
    setBusy(true);
    setErr(null);
    const form = new FormData();
    form.append("file", file);
    form.append("academic_year", year);
    try {
      const job = await api<any>("/api/v1/imports", { form });
      nav(`/inst/imports/${job.id}`);
    } catch (ex) {
      setErr(ex as ApiError);
    } finally {
      setBusy(false);
    }
  }

  const dl = (path: string, name: string) => download(path, name).catch((e) => setErr(e));

  return (
    <div className="stack">
      <div className="pagehead"><div><h1>Upload student records</h1>
        <p className="muted">Three steps: upload → fix what is flagged → commit. Nothing is saved to the register until you commit.</p></div></div>
      <div className="grid g2">
        <section className="card">
          <h2>1. Get the template</h2>
          <p className="small muted">The Excel template has drop-down lists for gender, nationality, seat category, pending reason and your own programme codes.</p>
          <div className="row">
            <button onClick={() => dl(`/api/v1/imports/template.xlsx?academic_year=${year}`, "student_template.xlsx")}>Download Excel template</button>
            <button className="secondary" onClick={() => dl("/api/v1/imports/template.csv", "student_template.csv")}>Download CSV template</button>
          </div>
        </section>
        <section className="card">
          <h2>2. Upload your file</h2>
          <form onSubmit={submit}>
            <Field label="Academic year">
              <select value={year} onChange={(e) => setYear(e.target.value)}>{YEARS.map((y) => <option key={y}>{y}</option>)}</select>
            </Field>
            <Field label="File (.xlsx or .csv, up to 2 MB and 5,000 rows)">
              <input type="file" accept=".csv,.xlsx" onChange={(e) => setFile(e.target.files?.[0] || null)} />
            </Field>
            <ErrorBox error={err} />
            <button type="submit" disabled={!file || busy}>{busy ? "Checking rows…" : "Upload and check"}</button>
          </form>
        </section>
      </div>
      <section className="card flat">
        <div style={{ padding: 16, paddingBottom: 0 }}><h2>Your uploads</h2></div>
        {jobs.data && jobs.data.length === 0 && <p className="muted" style={{ padding: 16 }}>No uploads yet.</p>}
        {jobs.data && jobs.data.length > 0 && (
          <div className="tablewrap"><table><thead><tr><th>File</th><th>Year</th><th>Status</th><th className="num">Committed / rows</th><th>Uploaded</th></tr></thead>
            <tbody>{jobs.data.map((j) => (
              <tr key={j.id}><td><Link to={`/inst/imports/${j.id}`}>{j.filename}</Link></td><td>{j.academic_year}</td><td><Badge v={j.status} /></td>
                <td className="num">{j.committed_rows} / {j.total_rows}</td><td className="small">{fmtDateTime(j.created_at)}</td></tr>
            ))}</tbody></table></div>
        )}
      </section>
    </div>
  );
}
