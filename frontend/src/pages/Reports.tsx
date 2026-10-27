import { useState } from "react";
import { ApiError, CURRENT_YEAR, download, YEARS } from "../api";
import { useAuth } from "../App";
import { ErrorBox, useToast } from "../components/ui";

export default function Reports() {
  const { user } = useAuth();
  const [year, setYear] = useState(CURRENT_YEAR);
  const [err, setErr] = useState<ApiError | null>(null);
  const [toast, show] = useToast();
  const aicte = user?.role.startsWith("AICTE");
  const reports: [string, string, string][] = [
    ["intake-utilisation", "Intake utilisation", "Approved intake, regular, NRI, excess and each supernumerary category per programme."],
    ["nationality", "Nationality and seat category", "Enrolled students by nationality status and seat category per programme."],
    ...(aicte ? [["review-priority", "Review priority", "Institutions ranked for review attention, with each signal's reason."] as [string, string, string]] : []),
  ];
  const get = (key: string) =>
    download(`/api/v1/reports/${key}.csv?academic_year=${year}`, `${key}_${year}.csv`).then(() => show("Report downloaded. The export is recorded in the audit trail.")).catch(setErr);
  return (
    <div className="stack">
      <div className="pagehead"><div><h1>Reports</h1><p className="muted">CSV exports computed from the register{aicte ? "" : " (your institution only)"}. Cells are protected against spreadsheet formula injection.</p></div>
        <select style={{ width: "auto" }} value={year} onChange={(e) => setYear(e.target.value)} aria-label="Academic year">{YEARS.map((y) => <option key={y}>{y}</option>)}</select></div>
      {toast}
      <ErrorBox error={err} />
      <div className="grid g3">
        {reports.map(([k, t, d]) => (
          <section className="card" key={k}><h2>{t}</h2><p className="small muted">{d}</p><button onClick={() => get(k)}>Download {t.toLowerCase()} CSV</button></section>
        ))}
      </div>
    </div>
  );
}
