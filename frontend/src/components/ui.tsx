import { ReactNode, useEffect, useRef, useState } from "react";
import { ApiError } from "../api";

export function Loading({ what = "Loading" }: { what?: string }) {
  return <p className="muted" role="status">{what}…</p>;
}

export function ErrorBox({ error, onRetry }: { error: ApiError | Error | null; onRetry?: () => void }) {
  if (!error) return null;
  return (
    <div className="banner error" role="alert">
      {error.message}
      {onRetry && (
        <> <button className="link" onClick={onRetry}>Try again</button></>
      )}
    </div>
  );
}

export function Empty({ children }: { children: ReactNode }) {
  return <div className="banner info">{children}</div>;
}

const TONE: Record<string, string> = {
  VALID: "green", ACTIVE: "green", VERIFIED: "green", COMMITTED: "green", RESOLVED: "green", APPROVED: "green", ACCEPTED: "green", LOW: "green", pass: "green", LIVE: "green",
  WARNING: "amber", REVIEW: "amber", PENDING_EXEMPT: "amber", PROVISIONAL: "amber", MEDIUM: "amber", CLARIFICATION_REQUESTED: "amber", RESPONDED: "blue", PENDING_CONSENT: "amber", PARTIALLY_COMMITTED: "amber", SIMULATED: "amber", UNVERIFIED: "amber", MISMATCH: "amber",
  ERROR: "red", HIGH: "red", REVOKED: "red", NOT_FOUND: "red", DENIED: "red", fail: "red", CANCELLED: "grey", REJECTED: "grey",
  OPEN: "blue", PREVIEW: "blue", COMMITTING: "blue", NO_MATCH: "amber",
};

export function Badge({ v, children }: { v?: string | null; children?: ReactNode }) {
  if (!v && !children) return null;
  return <span className={`badge b-${TONE[v || ""] || "grey"}`}>{children ?? (v || "").replace(/_/g, " ")}</span>;
}

export function Apaar({ value, status, masked }: { value?: string | null; status?: string; masked?: boolean }) {
  return (
    <span className="row" style={{ gap: 6, display: "inline-flex" }}>
      <span className="mono">{value || "—"}</span>
      {status && <Badge v={status} />}
      <span className="badge b-amber" title="APAAR registry checks run against a synthetic registry">SIMULATED</span>
      {masked && <span className="sr-only">masked</span>}
    </span>
  );
}

export function Confirm({ title, children, confirmLabel, danger, onConfirm, onCancel, busy }: {
  title: string; children: ReactNode; confirmLabel: string; danger?: boolean; busy?: boolean;
  onConfirm: () => void; onCancel: () => void;
}) {
  const ref = useRef<HTMLButtonElement>(null);
  useEffect(() => {
    ref.current?.focus();
    const esc = (e: KeyboardEvent) => e.key === "Escape" && onCancel();
    window.addEventListener("keydown", esc);
    return () => window.removeEventListener("keydown", esc);
  }, [onCancel]);
  return (
    <div className="overlay" role="dialog" aria-modal="true" aria-labelledby="dlg-title">
      <div className="dialog">
        <h2 id="dlg-title">{title}</h2>
        <div style={{ marginBottom: 16 }}>{children}</div>
        <div className="row" style={{ justifyContent: "flex-end" }}>
          <button className="secondary" onClick={onCancel}>Cancel</button>
          <button ref={ref} className={danger ? "danger" : ""} onClick={onConfirm} disabled={busy}>
            {busy ? "Working…" : confirmLabel}
          </button>
        </div>
      </div>
    </div>
  );
}

export function Pager({ page, pageSize, total, onPage }: { page: number; pageSize: number; total: number; onPage: (p: number) => void }) {
  const pages = Math.max(1, Math.ceil(total / pageSize));
  return (
    <div className="row between small" style={{ padding: "8px 10px" }}>
      <span className="muted">{total} result{total === 1 ? "" : "s"} · page {page} of {pages}</span>
      <span className="row">
        <button className="secondary small" disabled={page <= 1} onClick={() => onPage(page - 1)}>Previous page</button>
        <button className="secondary small" disabled={page >= pages} onClick={() => onPage(page + 1)}>Next page</button>
      </span>
    </div>
  );
}

export type Finding = { rule_id: string; severity: string; field: string | null; message: string; evidence?: any; suggestion?: { field: string; value: string; reason: string } };

export function Findings({ items, onUseSuggestion }: { items: Finding[]; onUseSuggestion?: (f: Finding) => void }) {
  if (!items?.length) return <span className="muted small">No findings</span>;
  return (
    <ul className="findings">
      {items.map((f, i) => (
        <li key={i}>
          <Badge v={f.severity} /> <code>{f.rule_id}</code> {f.field && <span className="muted">({f.field})</span>} {f.message}
          {f.suggestion && onUseSuggestion && (
            <div style={{ marginTop: 4 }}>
              Did you mean <span className="mono">{f.suggestion.value}</span>? <span className="muted">({f.suggestion.reason})</span>{" "}
              <button className="small" onClick={() => onUseSuggestion(f)}>Use this</button>
            </div>
          )}
        </li>
      ))}
    </ul>
  );
}

export function Field({ label, children, hint, error, flagged }: { label: string; children: ReactNode; hint?: string; error?: string; flagged?: boolean }) {
  return (
    <div className={`field${flagged ? " flag" : ""}`}>
      <label>{label}</label>
      {children}
      {hint && <div className="hint">{hint}</div>}
      {error && <div className="err">{error}</div>}
    </div>
  );
}

export function useToast(): [ReactNode, (msg: string, tone?: string) => void] {
  const [msg, setMsg] = useState<{ text: string; tone: string } | null>(null);
  useEffect(() => {
    if (!msg) return;
    const t = setTimeout(() => setMsg(null), 6000);
    return () => clearTimeout(t);
  }, [msg]);
  const node = msg ? <div className={`banner ${msg.tone}`} role="status">{msg.text}</div> : null;
  return [node, (text, tone = "ok") => setMsg({ text, tone })];
}

export function Figure({ k, v, tone }: { k: string; v: ReactNode; tone?: "bad" | "warn" }) {
  return (
    <div className={`fig ${tone || ""}`}>
      <div className="k">{k}</div>
      <div className="v">{v}</div>
    </div>
  );
}
