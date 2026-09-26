import { useEffect, useState } from "react";
import { supabase } from "../lib/supabase";
import { useAuth } from "../context/AuthContext";
import Card from "../components/ui/Card";
import JobRow from "../components/JobRow";
import RoleBadge from "../components/ui/RoleBadge";

const ROLES = ["admin", "operator", "guest"];

// Admin-only view: every user's jobs, and a role picker per user. Reachable
// only through <RequireRole roles={["admin"]}> in App.jsx, but the real
// guarantee is server-side — RLS policy "jobs: admin reads all" lets this
// query see other users' rows, and admin_set_role() (supabase/schema.sql)
// is the only way the role change below can actually take effect: it is a
// SECURITY DEFINER function that re-checks the CALLER is an admin itself,
// so a non-admin somehow reaching this page could not use it to promote
// anyone, themselves included (see web/supabase/tests/rls/01_adversarial.sql
// and web/SECURITY.md SVCS-WEB-002 for why a direct UPDATE of profiles.role
// is not how this works instead).
export default function AdminDashboard() {
  const { user: currentUser } = useAuth();
  const [jobs, setJobs] = useState([]);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");
  const [roleError, setRoleError] = useState("");
  const [savingRoleFor, setSavingRoleFor] = useState(null);

  async function load() {
    const [{ data: jobRows, error: jobsError }, { data: userRows, error: usersError }] =
      await Promise.all([
        supabase
          .from("jobs")
          .select("*, profiles:user_id (display_name, role)")
          .order("received_at", { ascending: false })
          .limit(200),
        supabase.from("profiles").select("id, display_name, role, created_at"),
      ]);
    if (jobsError || usersError) setError((jobsError || usersError).message);
    else {
      setJobs(jobRows);
      setUsers(userRows);
    }
    setLoading(false);
  }

  useEffect(() => {
    load();
  }, []);

  async function handleRoleChange(targetUser, newRole) {
    if (newRole === targetUser.role) return;
    const isSelf = targetUser.id === currentUser?.id;
    const confirmed = window.confirm(
      isSelf
        ? `Change YOUR OWN role from ${targetUser.role} to ${newRole}? If you remove your own admin access you will need another admin to restore it.`
        : `Change ${targetUser.display_name || "this user"}'s role from ${targetUser.role} to ${newRole}?`,
    );
    if (!confirmed) return;

    setRoleError("");
    setSavingRoleFor(targetUser.id);
    const { error: rpcError } = await supabase.rpc("admin_set_role", {
      target_user: targetUser.id,
      new_role: newRole,
    });
    setSavingRoleFor(null);
    if (rpcError) {
      setRoleError(rpcError.message);
      return;
    }
    setUsers((prev) => prev.map((u) => (u.id === targetUser.id ? { ...u, role: newRole } : u)));
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="mb-4 text-lg font-semibold text-slate-900">All users</h1>
        <Card className="p-4">
          {loading && <p className="text-sm text-slate-500">Loading…</p>}
          {roleError && <p className="mb-2 text-sm text-red-600">{roleError}</p>}
          {!loading && (
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                  <th className="pb-2 pr-4 font-medium">User</th>
                  <th className="pb-2 pr-4 font-medium">Role</th>
                  <th className="pb-2 font-medium">Joined</th>
                </tr>
              </thead>
              <tbody>
                {users.map((u) => (
                  <tr key={u.id} className="border-b border-slate-100 last:border-0">
                    <td className="py-2 pr-4 text-sm text-slate-700">
                      {u.display_name}
                      {u.id === currentUser?.id && (
                        <span className="ml-1 text-xs text-slate-400">(you)</span>
                      )}
                    </td>
                    <td className="py-2 pr-4">
                      <div className="flex items-center gap-2">
                        <RoleBadge role={u.role} />
                        <select
                          aria-label={`Change role for ${u.display_name || u.id}`}
                          value={u.role}
                          disabled={savingRoleFor === u.id}
                          onChange={(e) => handleRoleChange(u, e.target.value)}
                          className="rounded-md border border-slate-300 bg-white px-2 py-1 text-xs text-slate-700 disabled:opacity-50"
                        >
                          {ROLES.map((r) => (
                            <option key={r} value={r}>
                              {r}
                            </option>
                          ))}
                        </select>
                        {savingRoleFor === u.id && (
                          <span className="text-xs text-slate-400">saving…</span>
                        )}
                      </div>
                    </td>
                    <td className="py-2 text-sm text-slate-400">
                      {new Date(u.created_at).toLocaleDateString()}
                    </td>
                  </tr>
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>

      <div>
        <h2 className="mb-4 text-lg font-semibold text-slate-900">All jobs</h2>
        <Card className="p-4">
          {error && <p className="text-sm text-red-600">{error}</p>}
          {!loading && !error && (
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                  <th className="pb-2 pr-4 font-medium">Job</th>
                  <th className="pb-2 pr-4 font-medium">Owner</th>
                  <th className="pb-2 pr-4 font-medium">Finished</th>
                  <th className="pb-2 pr-4 font-medium">Status</th>
                  <th className="pb-2 pr-4 font-medium">Size</th>
                  <th className="pb-2 font-medium">Elapsed</th>
                </tr>
              </thead>
              <tbody>
                {jobs.map((job) => (
                  <JobRow key={job.id} job={job} ownerLabel={job.profiles?.display_name || "?"} />
                ))}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );
}
