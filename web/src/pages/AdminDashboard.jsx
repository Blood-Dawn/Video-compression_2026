import { useEffect, useState } from "react";
import { supabase } from "../lib/supabase";
import Card from "../components/ui/Card";
import JobRow from "../components/JobRow";
import RoleBadge from "../components/ui/RoleBadge";

// Admin-only view: every user's jobs. Reachable only through
// <RequireRole roles={["admin"]}> in App.jsx, but the real guarantee is
// server-side — RLS policy "jobs: admin reads all" in supabase/schema.sql
// is what actually lets this query see other users' rows; the route guard
// is just so a non-admin isn't shown a confusing empty page.
export default function AdminDashboard() {
  const [jobs, setJobs] = useState([]);
  const [users, setUsers] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
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
      if (cancelled) return;
      if (jobsError || usersError) setError((jobsError || usersError).message);
      else {
        setJobs(jobRows);
        setUsers(userRows);
      }
      setLoading(false);
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div className="space-y-8">
      <div>
        <h1 className="mb-4 text-lg font-semibold text-slate-900">All users</h1>
        <Card className="p-4">
          {loading && <p className="text-sm text-slate-500">Loading…</p>}
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
                    <td className="py-2 pr-4 text-sm text-slate-700">{u.display_name}</td>
                    <td className="py-2 pr-4">
                      <RoleBadge role={u.role} />
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
