import { FormEvent, useState } from "react";
import { Link } from "react-router-dom";
import { api, ApiError, User, useApi } from "../api";
import { useAuth } from "../App";
import { ErrorBox, Field } from "../components/ui";

const ROLE_LABEL: Record<string, string> = {
  AICTE_ADMIN: "AICTE monitoring officer", AICTE_ANALYST: "AICTE policy analyst", AUDITOR: "Auditor",
  INST_ADMIN: "Institution nodal officer", INST_STAFF: "Institution data-entry staff", STUDENT: "Student", VERIFIER: "Employer / verifier",
};

export default function Login() {
  const { signIn } = useAuth();
  const [email, setEmail] = useState("");
  const [password, setPassword] = useState("");
  const [err, setErr] = useState<ApiError | null>(null);
  const [busy, setBusy] = useState(false);
  const accounts = useApi<{ email: string; full_name: string; role: string }[]>("/api/v1/auth/demo-accounts");

  async function submit(e?: FormEvent, override?: { email: string }) {
    e?.preventDefault();
    setBusy(true);
    setErr(null);
    try {
      const r = await api<{ access_token: string; user: User }>("/api/v1/auth/login", {
        body: { email: override?.email ?? email, password: override ? "Demo@2026" : password },
      });
      signIn(r.access_token, r.user);
    } catch (ex) {
      setErr(ex as ApiError);
    } finally {
      setBusy(false);
    }
  }

  return (
    <div className="login">
      <section className="card">
        <p className="pill sim" style={{ marginBottom: 12 }}>APAAR checks simulated · synthetic data</p>
        <h1>APAAR Student Register</h1>
        <p className="muted">A register of student enrolments for AICTE-approved institutions, keyed to APAAR ID. Prototype for SIH26263.</p>
        <form onSubmit={submit} style={{ marginTop: 16 }}>
          <Field label="Email"><input type="email" autoComplete="username" value={email} onChange={(e) => setEmail(e.target.value)} required /></Field>
          <Field label="Password"><input type="password" autoComplete="current-password" value={password} onChange={(e) => setPassword(e.target.value)} required /></Field>
          <ErrorBox error={err} />
          <button type="submit" disabled={busy}>{busy ? "Signing in…" : "Sign in"}</button>
        </form>
        <p style={{ marginTop: 20 }}><Link to="/verify">Verify a record without signing in →</Link></p>
      </section>
      <section className="card">
        <h2>Demo accounts</h2>
        <p className="muted small">All accounts are synthetic and use the password <code>Demo@2026</code>. Choose one to sign in.</p>
        {accounts.loading && <p className="muted">Loading accounts…</p>}
        <ErrorBox error={accounts.error} onRetry={() => accounts.reload()} />
        {accounts.data?.map((a) => (
          <button key={a.email} className="acct" onClick={() => submit(undefined, { email: a.email })} disabled={busy}>
            <span><strong>{ROLE_LABEL[a.role] || a.role}</strong><br /><span className="small muted">{a.email}</span></span>
            <span className="small muted">Sign in →</span>
          </button>
        ))}
      </section>
    </div>
  );
}
