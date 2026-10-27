import { FormEvent, useState } from "react";
import { api, ApiError, CURRENT_YEAR, useApi } from "../api";
import { ErrorBox, Field } from "../components/ui";

export default function SeatCheck() {
  const progs = useApi<any[]>(`/api/v1/programmes?academic_year=${CURRENT_YEAR}`);
  const [f, setF] = useState({ programme_code: "", seat_category: "REGULAR", count: 1 });
  const [res, setRes] = useState<any>(null);
  const [err, setErr] = useState<ApiError | null>(null);
  async function submit(e: FormEvent) {
    e.preventDefault();
    setErr(null);
    try {
      setRes(await api("/api/v1/seat-check", { body: { ...f, programme_code: f.programme_code || progs.data?.[0]?.code, academic_year: CURRENT_YEAR } }));
    } catch (ex) {
      setErr(ex as ApiError);
    }
  }
  return (
    <div className="stack">
      <div className="pagehead"><div><h1>Seat check</h1>
        <p className="muted">Before confirming an admission, check whether it stays within approved intake or the category cap. Your admission software can call the same check through the API.</p></div></div>
      <section className="card">
        <form className="inline" onSubmit={submit}>
          <Field label="Programme"><select value={f.programme_code} onChange={(e) => setF({ ...f, programme_code: e.target.value })}>
            {progs.data?.map((p) => <option key={p.code} value={p.code}>{p.code} — {p.name}</option>)}</select></Field>
          <Field label="Seat category"><select value={f.seat_category} onChange={(e) => setF({ ...f, seat_category: e.target.value })}>
            {["REGULAR", "NRI", "SN_FN_OCI", "SN_CIWG", "SN_TFW", "SN_OTHER"].map((s) => <option key={s}>{s}</option>)}</select></Field>
          <Field label="Number of admissions"><input type="number" min={1} max={1000} value={f.count} onChange={(e) => setF({ ...f, count: Number(e.target.value) })} style={{ width: 110 }} /></Field>
          <button type="submit">Check seats</button>
        </form>
      </section>
      <ErrorBox error={err} />
      {res && (
        <section className={`banner ${res.allowed_within_rules ? "ok" : "error"}`} aria-live="polite">
          <h2>{res.allowed_within_rules ? "Within the rules" : "Would exceed the rules"}</h2>
          <p>{res.message}</p>
          <p className="small">Counts against: {res.counts_against}. Within intake: {res.within_intake.occupied} of {res.within_intake.approved} occupied, {res.within_intake.after} after.
            {res.category && ` Category: ${res.category.occupied} of ${res.category.cap} used, ${res.category.after} after.`}</p>
        </section>
      )}
    </div>
  );
}
