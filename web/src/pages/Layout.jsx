import { Link, Outlet } from "react-router-dom";
import { useAuth } from "../context/AuthContext";
import RoleBadge from "../components/ui/RoleBadge";
import Button from "../components/ui/Button";

export default function Layout() {
  const { profile, role, signOut } = useAuth();
  return (
    <div className="min-h-screen bg-slate-50">
      <header className="border-b border-slate-200 bg-white">
        <div className="mx-auto flex max-w-5xl items-center justify-between px-6 py-3">
          <div className="flex items-center gap-6">
            <Link to="/" className="font-semibold text-slate-900">
              SVCS Web
            </Link>
            <Link to="/" className="text-sm text-slate-600 hover:text-slate-900">
              Jobs
            </Link>
            {role === "admin" && (
              <Link to="/admin" className="text-sm text-slate-600 hover:text-slate-900">
                All users
              </Link>
            )}
            <Link to="/settings" className="text-sm text-slate-600 hover:text-slate-900">
              Settings
            </Link>
          </div>
          <div className="flex items-center gap-3">
            <span className="text-sm text-slate-600">{profile?.display_name}</span>
            <RoleBadge role={role} />
            <Button variant="ghost" onClick={signOut}>
              Sign out
            </Button>
          </div>
        </div>
      </header>
      <main className="mx-auto max-w-5xl px-6 py-8">
        <Outlet />
      </main>
    </div>
  );
}
