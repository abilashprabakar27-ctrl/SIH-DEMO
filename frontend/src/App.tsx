import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { HashRouter, Link, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, fmtDateTime, hasToken, setToken, useApi, User } from "./api";
import { Loading } from "./components/ui";
import Login from "./pages/Login";
import InstDashboard from "./pages/InstDashboard";
import Upload from "./pages/Upload";
import ImportDetail from "./pages/ImportDetail";
import Records from "./pages/Records";
import RecordDetail from "./pages/RecordDetail";
import { IssueDetail, IssueList } from "./pages/Issues";
import Corrections from "./pages/Corrections";
import SeatCheck from "./pages/SeatCheck";
import Reports from "./pages/Reports";
import National from "./pages/National";
import ReviewPriority from "./pages/ReviewPriority";
import Identity from "./pages/Identity";
import Rules from "./pages/Rules";
import Integrations from "./pages/Integrations";
import Audit from "./pages/Audit";
import Verify from "./pages/Verify";
import VerifierRequests from "./pages/VerifierRequests";
import MyRecord from "./pages/MyRecord";
import AddStudent from "./pages/AddStudent";
import SystemAccess from "./pages/SystemAccess";
import IntakeAdmin from "./pages/IntakeAdmin";

type Auth = { user: User | null; signIn: (token: string, user: User) => void; signOut: () => void };
const AuthCtx = createContext<Auth>({ user: null, signIn: () => {}, signOut: () => {} });
export const useAuth = () => useContext(AuthCtx);

const NAV: Record<string, [string, string][]> = {
  INST_ADMIN: [["/inst", "Dashboard"], ["/inst/upload", "Upload records"], ["/inst/add", "Add a student"], ["/records", "Student records"],
    ["/issues", "Flags"], ["/corrections", "Correction requests"], ["/seat-check", "Seat check"], ["/reports", "Reports"],
    ["/inst/system-access", "System access"]],
  INST_STAFF: [["/inst", "Dashboard"], ["/inst/upload", "Upload records"], ["/inst/add", "Add a student"], ["/records", "Student records"], ["/issues", "Flags"],
    ["/corrections", "Correction requests"], ["/seat-check", "Seat check"], ["/reports", "Reports"]],
  AICTE_ADMIN: [["/aicte", "National register"], ["/aicte/priority", "Review priority"], ["/issues", "Review queue"],
    ["/aicte/intakes", "Intake and caps"],
    ["/aicte/identity", "Identity candidates"], ["/records", "Student records"], ["/aicte/rules", "Rules"],
    ["/aicte/integrations", "Integrations"], ["/audit", "Audit trail"], ["/reports", "Reports"]],
  AICTE_ANALYST: [["/aicte", "National register"], ["/aicte/priority", "Review priority"], ["/issues", "Review queue"],
    ["/aicte/identity", "Identity candidates"], ["/records", "Student records"], ["/aicte/rules", "Rules"],
    ["/aicte/integrations", "Integrations"], ["/reports", "Reports"]],
  AUDITOR: [["/audit", "Audit trail"], ["/issues", "Flags (read-only)"], ["/aicte/integrations", "Integrations"]],
  VERIFIER: [["/verify", "Verify a record"], ["/verifier/requests", "Request verification"]],
  STUDENT: [["/me", "My record"]],
};

export function homeFor(role: string) {
  return { INST_ADMIN: "/inst", INST_STAFF: "/inst", AICTE_ADMIN: "/aicte", AICTE_ANALYST: "/aicte", AUDITOR: "/audit",
    VERIFIER: "/verify", STUDENT: "/me" }[role] || "/login";
}

function Logo() {
  // Original mark (not the AICTE logo or the State Emblem): an open register with a check.
  return (
    <svg width="54" height="54" viewBox="0 0 54 54" aria-hidden="true">
      <circle cx="27" cy="27" r="25" fill="#fff" stroke="#12387a" strokeWidth="3" />
      <circle cx="27" cy="27" r="20" fill="none" stroke="#f37021" strokeWidth="1.5" strokeDasharray="2 3" />
      <path d="M14 18 L27 21 L40 18 L40 36 L27 39 L14 36 Z" fill="#12387a" />
      <path d="M27 21 L27 39" stroke="#fff" strokeWidth="1.5" />
      <path d="M20 29 L24 33 L34 24" fill="none" stroke="#f37021" strokeWidth="3" strokeLinecap="round" strokeLinejoin="round" />
    </svg>
  );
}

const FONT_SIZES: [string, string][] = [["14px", "A−"], ["16px", "A"], ["18px", "A+"]];

function GovBar() {
  const [fs, setFs] = useState<string>(() => {
    try { return localStorage.getItem("apaar.fs") || "16px"; } catch { return "16px"; }
  });
  useEffect(() => {
    document.documentElement.style.setProperty("--fs", fs);
    try { localStorage.setItem("apaar.fs", fs); } catch { /* storage unavailable */ }
  }, [fs]);
  return (
    <div className="govbar">
      <div className="wrap">
        <span>SIH26263 prototype for AICTE · synthetic data · not an official website</span>
        <span className="row" style={{ gap: 0 }}>
          <a href="#main" onClick={(e) => { e.preventDefault(); document.getElementById("main")?.focus(); }}>Skip to main content</a>
          <span className="sep">|</span>
          <span className="fs" role="group" aria-label="Text size">
            {FONT_SIZES.map(([v, l]) => (
              <button key={v} className={fs === v ? "on" : ""} aria-pressed={fs === v} onClick={() => setFs(v)}
                title={`Text size ${l}`}>{l}</button>
            ))}
          </span>
        </span>
      </div>
    </div>
  );
}

function WhatsNew() {
  const { user } = useAuth();
  const n = useApi<any[]>(user ? "/api/v1/notifications" : null, [user?.id]);
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);
  if (!user || !n.data || n.data.length === 0) return null;
  const latest = n.data[0];
  const linkFor = (l: string | null) => (l ? `#${l}` : undefined);
  return (
    <div className="whatsnew" style={{ position: "relative" }}>
      <div className="wrap">
        <span className="tag">What's new</span>
        <span style={{ flex: 1, minWidth: 0 }}>{latest.link ? <a href={linkFor(latest.link)}>{latest.message}</a> : latest.message}
          <span className="small muted"> · {fmtDateTime(latest.created_at)}</span></span>
        <button className="link small" aria-expanded={open} onClick={() => setOpen(!open)}>All updates ({n.data.length})</button>
      </div>
      {open && (
        <div className="notes" role="dialog" aria-label="Updates">
          <ul>{n.data.map((x) => (
            <li key={x.id}>{x.link ? <a href={linkFor(x.link)}>{x.message}</a> : x.message}<div className="muted">{fmtDateTime(x.created_at)}</div></li>
          ))}</ul>
        </div>
      )}
    </div>
  );
}

function Shell({ children }: { children: ReactNode }) {
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);
  const items: [string, string][] = user ? NAV[user.role] || [] : [["/login", "Sign in"], ["/verify", "Verify a record"]];
  return (
    <>
      <GovBar />
      <div className="tricolour" />
      <header className="mast">
        <div className="wrap">
          <a className="brandline" href={user ? `#${homeFor(user.role)}` : "#/login"}>
            <Logo />
            <span>
              <span className="hi" lang="hi">एपीएएआर छात्र रजिस्टर</span><br />
              <span className="en">APAAR Student Register</span><br />
              <span className="sub">Student enrolment register for AICTE-approved institutions</span>
            </span>
          </a>
          <div className="user">
            <span className="pill sim" title="APAAR registry checks run against a synthetic registry; all data is synthetic">
              APAAR checks simulated · synthetic data
            </span>
            {user && (
              <>
                <span className="nm hide-sm"><strong>{user.full_name}</strong><br />{user.role.replace("_", " ")}{user.institution_code ? ` · ${user.institution_code}` : ""}</span>
                <button className="secondary small" onClick={signOut}>Sign out</button>
              </>
            )}
          </div>
        </div>
      </header>
      <div className="mainnav">
        <div className="wrap">
          <button className="small menu-btn" onClick={() => setOpen(!open)} aria-expanded={open}>Menu</button>
          <nav aria-label="Main navigation" className={open ? "open" : ""}>
            {items.map(([to, label]) => (
              <NavLink key={to} to={to} end={to === "/inst" || to === "/aicte"}>{label}</NavLink>
            ))}
          </nav>
        </div>
      </div>
      <WhatsNew />
      <main className="content" id="main" tabIndex={-1}>{children}</main>
      <footer className="footer">
        <div className="cols">
          <div>
            <h3>About this register</h3>
            <p>A prototype national register of student enrolments keyed to APAAR ID, built for Smart India Hackathon problem statement SIH26263 (AICTE).</p>
          </div>
          <div>
            <h3>Quick links</h3>
            <ul>
              <li><Link to="/verify">Verify a student record</Link></li>
              {user ? <li><Link to={homeFor(user.role)}>My home page</Link></li> : <li><Link to="/login">Sign in</Link></li>}
              <li><a href="/api/docs">API documentation</a></li>
            </ul>
          </div>
          <div>
            <h3>Data notice</h3>
            <p>All people, institutions and APAAR IDs shown are synthetic. APAAR registry checks are simulated; no official APAAR interface is used.</p>
          </div>
        </div>
        <div className="bottom">Prototype for demonstration only. Not an official website of AICTE or the Government of India.</div>
      </footer>
    </>
  );
}

function Guard({ roles, children }: { roles?: string[]; children: ReactNode }) {
  const { user } = useAuth();
  if (!user) return <Navigate to="/login" replace />;
  if (roles && !roles.includes(user.role)) return <Navigate to={homeFor(user.role)} replace />;
  return <>{children}</>;
}

const INST = ["INST_ADMIN", "INST_STAFF"];
const AICTE = ["AICTE_ADMIN", "AICTE_ANALYST"];

function AppRoutes() {
  const { user } = useAuth();
  const nav = useNavigate();
  useEffect(() => {
    const h = () => nav("/login");
    window.addEventListener("apaar:signedout", h);
    return () => window.removeEventListener("apaar:signedout", h);
  }, [nav]);
  return (
    <Shell>
      <Routes>
        <Route path="/login" element={user ? <Navigate to={homeFor(user.role)} replace /> : <Login />} />
        <Route path="/verify" element={<Verify />} />
        <Route path="/inst" element={<Guard roles={INST}><InstDashboard /></Guard>} />
        <Route path="/inst/upload" element={<Guard roles={INST}><Upload /></Guard>} />
        <Route path="/inst/add" element={<Guard roles={INST}><AddStudent /></Guard>} />
        <Route path="/inst/system-access" element={<Guard roles={["INST_ADMIN"]}><SystemAccess /></Guard>} />
        <Route path="/aicte/intakes" element={<Guard roles={["AICTE_ADMIN"]}><IntakeAdmin /></Guard>} />
        <Route path="/inst/imports/:id" element={<Guard roles={INST}><ImportDetail /></Guard>} />
        <Route path="/records" element={<Guard roles={[...INST, ...AICTE]}><Records /></Guard>} />
        <Route path="/records/:id" element={<Guard roles={[...INST, ...AICTE]}><RecordDetail /></Guard>} />
        <Route path="/issues" element={<Guard roles={[...INST, ...AICTE, "AUDITOR"]}><IssueList /></Guard>} />
        <Route path="/issues/:id" element={<Guard roles={[...INST, ...AICTE, "AUDITOR"]}><IssueDetail /></Guard>} />
        <Route path="/corrections" element={<Guard roles={INST}><Corrections /></Guard>} />
        <Route path="/seat-check" element={<Guard roles={INST}><SeatCheck /></Guard>} />
        <Route path="/reports" element={<Guard roles={[...INST, ...AICTE]}><Reports /></Guard>} />
        <Route path="/aicte" element={<Guard roles={AICTE}><National /></Guard>} />
        <Route path="/aicte/priority" element={<Guard roles={AICTE}><ReviewPriority /></Guard>} />
        <Route path="/aicte/identity" element={<Guard roles={AICTE}><Identity /></Guard>} />
        <Route path="/aicte/rules" element={<Guard roles={AICTE}><Rules /></Guard>} />
        <Route path="/aicte/integrations" element={<Guard roles={[...AICTE, "AUDITOR"]}><Integrations /></Guard>} />
        <Route path="/audit" element={<Guard roles={["AUDITOR", "AICTE_ADMIN"]}><Audit /></Guard>} />
        <Route path="/verifier/requests" element={<Guard roles={["VERIFIER"]}><VerifierRequests /></Guard>} />
        <Route path="/me" element={<Guard roles={["STUDENT"]}><MyRecord /></Guard>} />
        <Route path="*" element={<Navigate to={user ? homeFor(user.role) : "/login"} replace />} />
      </Routes>
    </Shell>
  );
}

export default function App() {
  const [user, setUser] = useState<User | null>(null);
  const [ready, setReady] = useState(!hasToken());
  useEffect(() => {
    if (!hasToken()) return;
    api<User>("/api/v1/auth/me").then(setUser).catch(() => setToken(null)).finally(() => setReady(true));
  }, []);
  const auth: Auth = {
    user,
    signIn: (t, u) => {
      setToken(t);
      setUser(u);
    },
    signOut: () => {
      setToken(null);
      setUser(null);
      window.location.hash = "#/login";
    },
  };
  if (!ready) return <div className="content"><Loading /></div>;
  return (
    <AuthCtx.Provider value={auth}>
      <HashRouter>
        <AppRoutes />
      </HashRouter>
    </AuthCtx.Provider>
  );
}
