import { useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, fmtDate, useApi } from "../api";
import { useAuth } from "../App";
import { Apaar, Badge, Empty, ErrorBox, Loading, useToast } from "../components/ui";

function Side({ s }: { s: any }) {
  return (
    <div>
      <strong>{s.student.full_name}</strong>
      <div className="small">DOB {fmtDate(s.student.date_of_birth)} · {s.student.gender}</div>
      <div className="small"><Apaar value={s.student.apaar_id} status={s.student.apaar_status} /></div>
      {s.enrolments.map((e: any) => (
        <div key={e.id} className="small muted"><Link to={`/records/${e.id}`}>{e.institution_name}</Link> · {e.programme_code} {e.academic_year} · {e.status}</div>
      ))}
    </div>
  );
}

export default function Identity() {
  const { user } = useAuth();
  const [decided, setDecided] = useState("false");
  const r = useApi<any[]>(`/api/v1/identity/candidates?decided=${decided}`, [decided]);
  const [notes, setNotes] = useState<Record<string, string>>({});
  const [err, setErr] = useState<ApiError | null>(null);
  const [toast, show] = useToast();
  async function decide(id: string, decision: string) {
    setErr(null);
    try {
      await api(`/api/v1/identity/candidates/${id}/decision`, { body: { decision, note: notes[id] || "" } });
      show(decision === "SAME_PERSON" ? "Recorded as the same person. Records are not merged automatically." : "Recorded as different people; the flag is dismissed.");
      r.reload(true);
    } catch (e) {
      setErr(e as ApiError);
    }
  }
  return (
    <div className="stack">
      <div className="pagehead"><div><h1>Identity candidates</h1>
        <p className="muted">Pairs of records that may be the same person under a different spelling or ID. Score 9 or more opens a review flag; 6 to 9 is listed here only. Nothing is merged automatically.</p></div>
        <select style={{ width: "auto" }} value={decided} onChange={(e) => setDecided(e.target.value)} aria-label="Show"><option value="false">Awaiting decision</option><option value="true">Decided</option></select></div>
      {toast}
      <ErrorBox error={err || r.error} />
      {r.loading && !r.data && <Loading />}
      {r.data?.length === 0 && <Empty>No candidate pairs here.</Empty>}
      {r.data?.map((c) => (
        <section className="card" key={c.id}>
          <div className="row between"><span><strong>Score {c.score}</strong> <Badge v={c.band === "REVIEW" ? "REVIEW" : "OPEN"}>{c.band === "REVIEW" ? "review flag" : "listed"}</Badge></span>
            {c.decision && <Badge v="RESOLVED">{c.decision.replace("_", " ").toLowerCase()}</Badge>}</div>
          <div className="grid g2" style={{ marginTop: 10 }}><Side s={c.a} /><Side s={c.b} /></div>
          <h3 style={{ marginTop: 12 }}>Why we think these match</h3>
          <table><tbody>{c.weights.map((w: any, i: number) => <tr key={i}><td>{w.factor}</td><td className="num">{w.weight > 0 ? "+" : ""}{w.weight}</td></tr>)}</tbody></table>
          {c.decision_note && <p className="small muted">Decision note: {c.decision_note}</p>}
          {!c.decision && user?.role === "AICTE_ADMIN" && (
            <div className="inline" style={{ marginTop: 10 }}>
              <div className="field" style={{ flex: "1 1 260px" }}><label>Reviewer note</label><input value={notes[c.id] || ""} onChange={(e) => setNotes({ ...notes, [c.id]: e.target.value })} /></div>
              <button disabled={(notes[c.id] || "").trim().length < 3} onClick={() => decide(c.id, "SAME_PERSON")}>Same person</button>
              <button className="secondary" disabled={(notes[c.id] || "").trim().length < 3} onClick={() => decide(c.id, "DIFFERENT_PEOPLE")}>Different people</button>
            </div>
          )}
        </section>
      ))}
    </div>
  );
}
