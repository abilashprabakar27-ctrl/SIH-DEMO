import { useApi } from "../api";
import { Badge, ErrorBox, Loading } from "../components/ui";

export default function Integrations() {
  const r = useApi<any>("/api/v1/integration/status");
  if (r.loading && !r.data) return <Loading />;
  return (
    <div className="stack">
      <div className="pagehead"><div><h1>Integrations</h1><p className="muted">Each integration is labelled honestly: live, simulated, or not implemented.</p></div></div>
      <ErrorBox error={r.error} />
      <section className="card flat"><table>
        <thead><tr><th>Integration</th><th>State</th><th>Details</th></tr></thead>
        <tbody>{r.data?.integrations.map((i: any) => (
          <tr key={i.name}><td><strong>{i.name}</strong></td><td><Badge v={i.state === "NOT_IMPLEMENTED" ? "CANCELLED" : i.state}>{i.state.replace("_", " ").toLowerCase()}</Badge></td>
            <td className="small">{i.detail}{i.subscribers !== undefined && ` ${i.subscribers} live connection(s).`}{i.available === false && " Currently unavailable."}</td></tr>
        ))}</tbody></table></section>
    </div>
  );
}
