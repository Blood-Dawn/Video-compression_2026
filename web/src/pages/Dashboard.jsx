import { useEffect, useState } from "react";
import { supabase } from "../lib/supabase";
import { useAuth } from "../context/AuthContext";
import Card from "../components/ui/Card";
import JobRow from "../components/JobRow";

// The operator's own view: every job THEY synced, newest first. RLS (see
// supabase/schema.sql, policy "jobs: read own") already guarantees this
// query can only ever return this user's own rows — there is no separate
// client-side filter to get wrong.
export default function Dashboard() {
  const { profile } = useAuth();
  const [jobs, setJobs] = useState([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState("");

  useEffect(() => {
    let cancelled = false;
    async function load() {
      const { data, error } = await supabase
        .from("jobs")
        .select("*")
        .order("received_at", { ascending: false })
        .limit(100);
      if (cancelled) return;
      if (error) setError(error.message);
      else setJobs(data);
      setLoading(false);
    }
    load();
    return () => {
      cancelled = true;
    };
  }, []);

  return (
    <div>
      <h1 className="mb-1 text-lg font-semibold text-slate-900">Your compression jobs</h1>
      <p className="mb-6 text-sm text-slate-500">
        Synced automatically from the SVCS desktop app on{" "}
        {profile?.display_name ? `${profile.display_name}'s` : "your"} machine(s), once you point
        its Webhook settings at your ingest link — see Settings.
      </p>
      <Card className="p-4">
        {loading && <p className="text-sm text-slate-500">Loading…</p>}
        {error && <p className="text-sm text-red-600">{error}</p>}
        {!loading && !error && jobs.length === 0 && (
          <p className="text-sm text-slate-500">
            No jobs synced yet. Head to Settings to connect a desktop app.
          </p>
        )}
        {jobs.length > 0 && (
          <table className="w-full text-left">
            <thead>
              <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                <th className="pb-2 pr-4 font-medium">Job</th>
                <th className="pb-2 pr-4 font-medium">Finished</th>
                <th className="pb-2 pr-4 font-medium">Status</th>
                <th className="pb-2 pr-4 font-medium">Size</th>
                <th className="pb-2 font-medium">Elapsed</th>
              </tr>
            </thead>
            <tbody>
              {jobs.map((job) => (
                <JobRow key={job.id} job={job} />
              ))}
            </tbody>
          </table>
        )}
      </Card>
    </div>
  );
}
