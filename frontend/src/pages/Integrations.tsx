import { useApi } from "../api";
import { Badge, ErrorBox, Loading } from "../components/ui";

export default function Integrations() {
  const r = useApi<any>("/api/v1/integration/status");
  const system = useApi<any>("/api/v1/integration/system/status");
  if (r.loading && !r.data) return <Loading />;
  return (
    <div className="stack">
      <div className="pagehead"><div><h1>Integrations</h1><p className="muted">Each integration is labelled honestly: live, simulated, or not implemented.</p></div></div>
      <ErrorBox error={r.error} />
      <ErrorBox error={system.error} />
      <section className="card flat"><table>
        <thead><tr><th>Integration</th><th>State</th><th>Details</th></tr></thead>
        <tbody>{r.data?.integrations.map((i: any) => (
          <tr key={i.name}><td><strong>{i.name}</strong></td><td><Badge v={i.state === "NOT_IMPLEMENTED" ? "CANCELLED" : i.state}>{i.state.replace("_", " ").toLowerCase()}</Badge></td>
            <td className="small">{i.detail}{i.subscribers !== undefined && ` ${i.subscribers} live connection(s).`}{i.available === false && " Currently unavailable."}</td></tr>
      ))}</tbody></table></section>
      {system.data && <section className="card flat">
        <h2>System status</h2>
        <p><Badge v="SIMULATED">Registry simulated</Badge> No official APAAR API contract or credentials are configured.</p>
        <p>Capacity rule sources: <strong>{system.data.capacity_rules.source_verification.toLowerCase()}</strong>.</p>
        <p>Audit trail: <strong>tamper-evident</strong>. Database-level update/delete protection is not configured.</p>
        <p><strong>Production ready: no.</strong> {system.data.production_blockers.join(" ")}</p>
        <h3>Prototype implementation status</h3>
        <div className="tablewrap"><table><thead><tr><th>Feature</th><th>Status</th><th>Current behavior</th></tr></thead><tbody>
          {system.data.prototype_features?.map((f: any) => <tr key={f.feature}><td>{f.feature}</td><td><Badge v={f.state.includes("IMPLEMENTED") || f.state.includes("VERIFIED") ? "VALID" : "REVIEW"}>{f.state.replaceAll("_", " ").toLowerCase()}</Badge></td><td className="small">{f.detail}</td></tr>)}
        </tbody></table></div>
      </section>}
    </div>
  );
}
