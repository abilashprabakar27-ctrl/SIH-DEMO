import { FormEvent, useState } from "react";
import { api, ApiError, fmtDate, useApi } from "../api";
import { Badge, Confirm, ErrorBox, Field, useToast } from "../components/ui";

export default function SystemAccess() {
  const list = useApi<any[]>("/api/v1/integration/clients");
  const [name, setName] = useState("");
  const [scopes, setScopes] = useState<Record<string, boolean>>({ "enrolments:write": true, "seat:check": true });
  const [created, setCreated] = useState<any>(null);
  const [revoke, setRevoke] = useState<any>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  const [toast, show] = useToast();

  async function create(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      setCreated(await api("/api/v1/integration/clients", { body: { name, scopes: Object.keys(scopes).filter((k) => scopes[k]) } }));
      setName("");
      list.reload(true);
    } catch (ex) {
      setErr(ex as ApiError);
    }
  }
  async function doRevoke() {
    try {
      await api(`/api/v1/integration/clients/${revoke.id}/revoke`, { method: "POST" });
      show(`Key ${revoke.key_prefix} revoked. Systems using it are refused from now on.`);
      setRevoke(null);
      list.reload(true);
    } catch (ex) {
      setErr(ex as ApiError);
    }
  }
  return (
    <div className="stack">
      <div className="pagehead"><div><h1>System access</h1>
        <p className="muted">API keys let your admission or ERP system push enrolments and run seat checks. Only a hash of each key is stored.</p></div></div>
      {toast}
      <ErrorBox error={err} />
      {created && (
        <div className="banner warn" role="alert">
          <strong>Copy this key now. It is shown only once.</strong>
          <div className="token" style={{ margin: "8px 0" }}>{created.api_key}</div>
          <button className="small" onClick={() => navigator.clipboard?.writeText(created.api_key).then(() => show("Key copied."))}>Copy key</button>{" "}
          <button className="small secondary" onClick={() => setCreated(null)}>I have stored it</button>
        </div>
      )}
      <form className="card" onSubmit={create}>
        <h2>Create a key</h2>
        <div className="inline">
          <div className="field" style={{ flex: "1 1 260px" }}><label>System name</label><input value={name} onChange={(e) => setName(e.target.value)} placeholder="e.g. Admission ERP" required minLength={3} /></div>
          {Object.keys(scopes).map((s) => (
            <label key={s} style={{ fontWeight: 400, display: "flex", gap: 6, alignItems: "center", marginBottom: 8 }}>
              <input type="checkbox" style={{ width: "auto" }} checked={scopes[s]} onChange={(e) => setScopes({ ...scopes, [s]: e.target.checked })} />{s}
            </label>
          ))}
          <button type="submit" disabled={!Object.values(scopes).some(Boolean)}>Create API key</button>
        </div>
      </form>
      <section className="card flat"><table>
        <thead><tr><th>System</th><th>Key prefix</th><th>Scopes</th><th>Created</th><th>Status</th><th></th></tr></thead>
        <tbody>
          {list.data?.length === 0 && <tr><td colSpan={6} className="muted">No keys yet.</td></tr>}
          {list.data?.map((c) => (
            <tr key={c.id}><td>{c.name}</td><td className="mono">{c.key_prefix}</td><td className="small">{c.scopes.join(", ")}</td>
              <td>{fmtDate(c.created_at)}</td><td>{c.active ? <Badge v="ACTIVE" /> : <Badge v="REVOKED" />}</td>
              <td>{c.active && <button className="small danger" onClick={() => setRevoke(c)}>Revoke key</button>}</td></tr>
          ))}
        </tbody></table></section>
      <section className="card"><h2>How a system calls the register</h2>
        <p className="small">Send <code>X-API-Key</code> with every request. Enrolment pushes also need an <code>Idempotency-Key</code> so a retry never creates duplicates. See <a href="/api/docs">API documentation</a>.</p>
        <Field label="Example"><div className="token">POST /api/v1/seat-check {"{"}"programme_code":"BTECH-CSE","seat_category":"REGULAR","count":1{"}"}</div></Field>
      </section>
      {revoke && (
        <Confirm title={`Revoke key ${revoke.key_prefix}?`} confirmLabel="Revoke key" danger onCancel={() => setRevoke(null)} onConfirm={doRevoke}>
          <p>{revoke.name} will be refused immediately. This cannot be undone; create a new key if needed.</p>
        </Confirm>
      )}
    </div>
  );
}
