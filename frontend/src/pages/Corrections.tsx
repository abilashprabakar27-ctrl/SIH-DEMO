import { useState } from "react";
import { Link, useNavigate } from "react-router-dom";
import { api, ApiError, fmtDate, useApi } from "../api";
import { Badge, Empty, ErrorBox, Loading, useToast } from "../components/ui";

export default function Corrections() {
  const [status, setStatus] = useState("OPEN");
  const r = useApi<any[]>(`/api/v1/correction-requests?status=${status}`, [status]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [err, setErr] = useState<ApiError | null>(null);
  const [toast, show] = useToast();
  const nav = useNavigate();
  async function act(c: any, action: string) {
    setErr(null);
    try {
      const res = await api<any>(`/api/v1/correction-requests/${c.id}/actions`, { body: { action, note: notes[c.id] || "" } });
      if (action === "ACCEPT") {
        const p = res.prefill;
        nav(`/records/${p.enrolment_id}?field=${p.field}&value=${encodeURIComponent(p.value)}&cr=${p.correction_request_id}`);
      } else {
        show("Request rejected; the student sees your note.");
        r.reload(true);
      }
    } catch (e) {
      setErr(e as ApiError);
    }
  }
  return (
    <div className="stack">
      <div className="pagehead"><div><h1>Student correction requests</h1>
        <p className="muted">Students can ask for their record to be corrected. Respond within 14 days; overdue requests are visible to AICTE.</p></div>
        <select style={{ width: "auto" }} value={status} onChange={(e) => setStatus(e.target.value)} aria-label="Status">
          <option value="OPEN">Open</option><option value="ACCEPTED,REJECTED">Decided</option></select></div>
      {toast}
      <ErrorBox error={err || r.error} />
      {r.loading && !r.data && <Loading />}
      {r.data?.length === 0 && <Empty>No requests here.</Empty>}
      {r.data?.map((c) => (
        <section className="card" key={c.id}>
          <div className="row between"><strong>{c.record?.student.full_name} · <Link to={`/records/${c.enrolment_id}`}>{c.record?.institution_student_id}</Link></strong>
            <span>{c.overdue ? <Badge v="ERROR">Overdue</Badge> : <Badge v={c.status} />} <span className="small muted">due {fmtDate(c.due_at)}</span></span></div>
          <p>Change <strong>{c.field}</strong> to <strong>{c.requested_value}</strong></p>
          <p className="small muted">Student's explanation: {c.explanation}</p>
          {c.resolution_note && <p className="small">Note: {c.resolution_note}</p>}
          {c.status === "OPEN" && (
            <div className="inline">
              <div className="field" style={{ flex: "1 1 260px" }}><label>Note to the student</label>
                <input value={notes[c.id] || ""} onChange={(e) => setNotes({ ...notes, [c.id]: e.target.value })} /></div>
              <button onClick={() => act(c, "ACCEPT")}>Accept and open correction form</button>
              <button className="secondary" onClick={() => act(c, "REJECT")} disabled={(notes[c.id] || "").trim().length < 5}>Reject with note</button>
            </div>
          )}
        </section>
      ))}
    </div>
  );
}
