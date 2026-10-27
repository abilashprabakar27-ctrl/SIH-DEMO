import { useCallback, useEffect, useRef, useState } from "react";

export type User = {
  id: string;
  email: string;
  full_name: string;
  role: string;
  institution_id: string | null;
  institution_name: string | null;
  institution_code: string | null;
  student_id: string | null;
  organisation: string | null;
};

export class ApiError extends Error {
  status: number;
  data: Record<string, any>;
  constructor(status: number, message: string, data: Record<string, any>) {
    super(message);
    this.status = status;
    this.data = data;
  }
}

const KEY = "apaar.session";
let token: string | null = null;
try {
  token = sessionStorage.getItem(KEY);
} catch {
  token = null;
}

export function setToken(t: string | null) {
  token = t;
  try {
    if (t) sessionStorage.setItem(KEY, t);
    else sessionStorage.removeItem(KEY);
  } catch {
    /* storage unavailable: keep in memory */
  }
}
export const hasToken = () => !!token;

type Opts = { method?: string; body?: unknown; form?: FormData; headers?: Record<string, string> };

export async function api<T = any>(path: string, opts: Opts = {}): Promise<T> {
  const headers: Record<string, string> = { ...(opts.headers || {}) };
  if (token) headers.Authorization = `Bearer ${token}`;
  let body: BodyInit | undefined;
  if (opts.form) body = opts.form;
  else if (opts.body !== undefined) {
    headers["Content-Type"] = "application/json";
    body = JSON.stringify(opts.body);
  }
  let res: Response;
  try {
    res = await fetch(path, { method: opts.method || (body ? "POST" : "GET"), headers, body });
  } catch {
    throw new ApiError(0, "Cannot reach the server. Check your connection and try again.", {});
  }
  const ct = res.headers.get("content-type") || "";
  const data = ct.includes("application/json") ? await res.json() : await res.text();
  if (!res.ok) {
    const err = (data && (data as any).error) || {};
    if (res.status === 401 && token && !path.endsWith("/auth/login")) {
      setToken(null);
      window.dispatchEvent(new Event("apaar:signedout"));
    }
    throw new ApiError(res.status, err.message || `Request failed (${res.status}).`, err);
  }
  return data as T;
}

async function fetchBlob(path: string): Promise<Blob> {
  const res = await fetch(path, { headers: token ? { Authorization: `Bearer ${token}` } : {} });
  if (!res.ok) {
    let msg = `Download failed (${res.status}).`;
    try {
      msg = (await res.json()).error.message;
    } catch {
      /* not json */
    }
    throw new ApiError(res.status, msg, {});
  }
  return res.blob();
}

export async function download(path: string, filename: string) {
  const blob = await fetchBlob(path);
  const url = URL.createObjectURL(blob);
  const a = document.createElement("a");
  a.href = url;
  a.download = filename;
  document.body.appendChild(a);
  a.click();
  a.remove();
  setTimeout(() => URL.revokeObjectURL(url), 2000);
}

export async function openDocument(path: string) {
  const blob = await fetchBlob(path);
  const url = URL.createObjectURL(new Blob([blob], { type: "text/html" }));
  window.open(url, "_blank", "noopener");
}

export function useApi<T = any>(path: string | null, deps: unknown[] = []) {
  const [data, setData] = useState<T | null>(null);
  const [error, setError] = useState<ApiError | null>(null);
  const [loading, setLoading] = useState<boolean>(!!path);
  const seq = useRef(0);
  const load = useCallback(
    async (quiet = false) => {
      if (!path) return;
      const n = ++seq.current;
      if (!quiet) setLoading(true);
      try {
        const d = await api<T>(path);
        if (n === seq.current) {
          setData(d);
          setError(null);
        }
      } catch (e) {
        if (n === seq.current) setError(e as ApiError);
      } finally {
        if (n === seq.current) setLoading(false);
      }
    },
    // eslint-disable-next-line react-hooks/exhaustive-deps
    [path, ...deps],
  );
  useEffect(() => {
    load();
  }, [load]);
  return { data, error, loading, reload: load, setData };
}

/** Subscribe to server-sent events; calls onEvent(type, data). Reconnects with backoff. */
export function useLiveEvents(onEvent: (type: string, data: any) => void, enabled = true) {
  const cb = useRef(onEvent);
  cb.current = onEvent;
  const [connected, setConnected] = useState(false);
  useEffect(() => {
    if (!enabled || typeof EventSource === "undefined") return;
    let es: EventSource | null = null;
    let stopped = false;
    let retry = 1000;
    const connect = async () => {
      try {
        const { token: t } = await api<{ token: string }>("/api/v1/auth/stream-token", { method: "POST" });
        if (stopped) return;
        es = new EventSource(`/api/v1/events?token=${encodeURIComponent(t)}`);
        es.addEventListener("ready", () => {
          setConnected(true);
          retry = 1000;
        });
        for (const kind of ["seat.changed", "issue.opened", "issue.updated"]) {
          es.addEventListener(kind, (ev) => cb.current(kind, JSON.parse((ev as MessageEvent).data)));
        }
        es.onerror = () => {
          setConnected(false);
          es?.close();
          if (!stopped) setTimeout(connect, (retry = Math.min(retry * 2, 30000)));
        };
      } catch {
        if (!stopped) setTimeout(connect, (retry = Math.min(retry * 2, 30000)));
      }
    };
    connect();
    return () => {
      stopped = true;
      es?.close();
    };
  }, [enabled]);
  return connected;
}

export const fmtDate = (s?: string | null) =>
  s ? new Date(s.length === 10 ? s + "T00:00:00" : s).toLocaleDateString("en-IN", { day: "numeric", month: "short", year: "numeric" }) : "—";
export const fmtDateTime = (s?: string | null) =>
  s ? new Date(s).toLocaleString("en-IN", { day: "numeric", month: "short", hour: "2-digit", minute: "2-digit" }) : "—";
export const CURRENT_YEAR = "2026-27";
export const YEARS = ["2026-27", "2025-26"];
