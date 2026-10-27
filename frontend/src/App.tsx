import { createContext, ReactNode, useContext, useEffect, useState } from "react";
import { HashRouter, Navigate, NavLink, Route, Routes, useLocation, useNavigate } from "react-router-dom";
import { api, hasToken, setToken, User } from "./api";
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

type Auth = { user: User | null; signIn: (token: string, user: User) => void; signOut: () => void };
const AuthCtx = createContext<Auth>({ user: null, signIn: () => {}, signOut: () => {} });
export const useAuth = () => useContext(AuthCtx);

const NAV: Record<string, [string, string][]> = {
  INST_ADMIN: [["/inst", "Dashboard"], ["/inst/upload", "Upload records"], ["/records", "Student records"], ["/issues", "Flags"],
    ["/corrections", "Correction requests"], ["/seat-check", "Seat check"], ["/reports", "Reports"]],
  INST_STAFF: [["/inst", "Dashboard"], ["/inst/upload", "Upload records"], ["/records", "Student records"], ["/issues", "Flags"],
    ["/corrections", "Correction requests"], ["/seat-check", "Seat check"], ["/reports", "Reports"]],
  AICTE_ADMIN: [["/aicte", "National register"], ["/aicte/priority", "Review priority"], ["/issues", "Review queue"],
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

function Shell({ children }: { children: ReactNode }) {
  const { user, signOut } = useAuth();
  const [open, setOpen] = useState(false);
  const loc = useLocation();
  useEffect(() => setOpen(false), [loc.pathname]);
  if (!user) return <>{children}</>;
  return (
    <div className="shell">
      <aside className={`side${open ? " open" : ""}`} aria-label="Main navigation">
        <div className="brand">APAAR Student Register<small>AICTE · SIH26263 prototype</small></div>
        <nav>
          {(NAV[user.role] || []).map(([to, label]) => (
            <NavLink key={to} to={to} end={to === "/inst" || to === "/aicte"}>{label}</NavLink>
          ))}
        </nav>
        <div className="who">
          {user.full_name}<br />{user.role.replace("_", " ")}{user.institution_name ? <><br />{user.institution_name}</> : null}
        </div>
      </aside>
      <div className="main">
        <header className="top">
          <div className="left">
            <button className="secondary small menu-btn" onClick={() => setOpen(!open)} aria-expanded={open}>Menu</button>
            <span className="pill sim" title="APAAR registry checks run against a synthetic registry; all data is synthetic">
              APAAR checks simulated · synthetic data
            </span>
          </div>
          <div className="row">
            <span className="small muted hide-sm">{user.email}</span>
            <button className="secondary small" onClick={signOut}>Sign out</button>
          </div>
        </header>
        <main className="content" id="main">{children}</main>
      </div>
    </div>
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
        <Route path="/verify" element={user ? <Verify /> : <div className="content" style={{ margin: "0 auto" }}><Verify publicView /></div>} />
        <Route path="/inst" element={<Guard roles={INST}><InstDashboard /></Guard>} />
        <Route path="/inst/upload" element={<Guard roles={INST}><Upload /></Guard>} />
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
