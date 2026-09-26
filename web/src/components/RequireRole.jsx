import { Navigate } from "react-router-dom";
import { useAuth } from "../context/AuthContext";

// Wrap a page that only some roles may see (e.g. the admin dashboard).
// Signed-in users of the wrong role are bounced to their own dashboard
// rather than shown a bare "forbidden" page.
export default function RequireRole({ roles, children }) {
  const { role, loading } = useAuth();
  if (loading) return <div className="p-8 text-slate-500">Loading…</div>;
  if (!roles.includes(role)) return <Navigate to="/" replace />;
  return children;
}
