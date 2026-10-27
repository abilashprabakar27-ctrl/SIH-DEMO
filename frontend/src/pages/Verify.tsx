import { useEffect, useState } from "react";
import { Link, useSearchParams } from "react-router-dom";
import { api, ApiError, fmtDate } from "../api";
import { Badge, ErrorBox, Field } from "../components/ui";

export default function Verify({ publicView = false }: { publicView?: boolean }) {
  const [sp] = useSearchParams();
  const [token, setToken] = useState(sp.get("t") || "");
  const [res, setRes] = useState<any>(null);
  const [status, setStatus] = useState<any>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const [tampered, setTampered] = useState(false);

  async function verify(t = token) {
    setBusy(true);
    setErr(null);
    try {
      setRes(await api("/api/v1/verification/verify-token", { body: { token: t.trim() } }));
    } catch (e) {
      setErr(e as ApiError);
    } finally {
      setBusy(false);
    }
  }
  async function tamper(mode: string) {
    try {
      const r = await api<any>("/api/v1/verification/tamper-demo", { body: { token, mode } });
      setToken(r.token);
      setTampered(true);
      verify(r.token);
    } catch (e) {
      setErr(e as ApiError);
    }
  }
  useEffect(() => {
    const cid = sp.get("cid");
    if (cid) api(`/api/v1/verification/credentials/${cid}`).then(setStatus).catch((e) => setErr(e));
    if (sp.get("t")) verify(sp.get("t")!);
    // eslint-disable-next-line react-hooks/exhaustive-deps
  }, []);

  return (
    <div className="stack" style={publicView ? { maxWidth: 820, margin: "24px auto" } : {}}>
      {publicView && <p className="row between"><span className="pill sim">APAAR checks simulated · synthetic data</span><Link to="/login">Sign in</Link></p>}
      <div className="pagehead"><div><h1>Verify a student record</h1>
        <p className="muted">Paste the record token the student shared. Only the details they chose to share are shown. Presenting the token is the student's consent.</p></div></div>
      {status && (
        <section className={`banner ${status.status === "ACTIVE" ? "ok" : "error"}`}>
          <strong>Record {status.id.slice(0, 8)}: {status.status.toLowerCase()}</strong>
          {status.status === "REVOKED" && <> — revoked on {fmtDate(status.revoked_at)}: {status.revocation_reason}</>}
          <div className="small">Issued {fmtDate(status.issued_at)}, valid until {fmtDate(status.valid_until)}. This QR code confirms status only; ask the student for a token to see details, or <Link to="/verifier/requests">request verification with consent</Link>.</div>
        </section>
      )}
      <section className="card">
        <Field label="Record token"><textarea value={token} onChange={(e) => { setToken(e.target.value); setTampered(false); }} rows={5} className="mono" /></Field>
        <div className="row">
          <button disabled={!token.trim() || busy} onClick={() => verify()}>{busy ? "Checking…" : "Verify record"}</button>
          {res?.valid && !tampered && <>
            <button className="secondary" onClick={() => tamper("disclosure")}>Demo: tamper with this record (edit a value)</button>
            <button className="secondary" onClick={() => tamper("payload")}>Demo: tamper with the signed part</button></>}
        </div>
        {tampered && <p className="small muted" style={{ marginTop: 8 }}>The token above was edited without re-signing, to show what a forged record looks like.</p>}
      </section>
      <ErrorBox error={err} />
      {res && (
        <section className="card" aria-live="polite">
          <div className={`banner ${res.valid ? "ok" : "error"}`}><strong>{res.valid ? "Genuine and current" : "Do not rely on this record"}</strong>
            {!res.valid && " — one or more checks failed."}</div>
          {res.checks.map((c: any) => (
            <div className="check" key={c.check}>
              <span className={`ico ${c.result}`} aria-hidden>{c.result === "pass" ? "✓" : c.result === "fail" ? "✕" : "–"}</span>
              <div><strong>{c.label}</strong> <span className="sr-only">{c.result}</span><div className="small">{c.sentence}</div></div>
            </div>
          ))}
          {res.notes?.map((n: string) => <p key={n} className="banner warn small" style={{ marginTop: 10 }}>{n}</p>)}
          {Object.keys(res.claims).length > 0 && (
            <>
              <h2 style={{ marginTop: 14 }}>Details the student shared</h2>
              <table><tbody>
                {Object.entries(res.claims).map(([k, v]) => <tr key={k}><td className="muted">{res.claim_labels[k]}</td><td>{String(v)}</td></tr>)}
                {!res.apaar_disclosed && res.apaar_display && <tr><td className="muted">APAAR ID</td><td className="mono">{res.apaar_display} <span className="small muted">(masked; not shared)</span></td></tr>}
              </tbody></table>
              <p className="small muted">APAAR registry check mode: <Badge v="SIMULATED" /></p>
            </>
          )}
        </section>
      )}
    </div>
  );
}
