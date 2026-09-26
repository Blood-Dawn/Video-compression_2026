function formatBytes(n) {
  if (!n) return "0 B";
  const units = ["B", "KB", "MB", "GB", "TB"];
  let i = 0;
  let v = n;
  while (v >= 1024 && i < units.length - 1) {
    v /= 1024;
    i++;
  }
  return `${v.toFixed(v < 10 && i > 0 ? 1 : 0)} ${units[i]}`;
}

const STATUS_STYLES = {
  completed: "text-emerald-700 bg-emerald-50",
  stopped: "text-amber-700 bg-amber-50",
  error: "text-red-700 bg-red-50",
};

// One row in a jobs table. Shared by the operator dashboard (that user's
// own jobs) and the admin dashboard (every user's jobs, with an extra
// owner column the admin page passes in via `ownerLabel`).
export default function JobRow({ job, ownerLabel }) {
  const saved = job.bytes_in && job.bytes_out ? 1 - job.bytes_out / job.bytes_in : null;
  return (
    <tr className="border-b border-slate-100 last:border-0">
      <td className="py-2 pr-4 text-sm text-slate-700">{job.label || job.kind}</td>
      {ownerLabel !== undefined && (
        <td className="py-2 pr-4 text-sm text-slate-500">{ownerLabel}</td>
      )}
      <td className="py-2 pr-4 text-sm text-slate-500">
        {job.ended_at ? new Date(job.ended_at).toLocaleString() : "—"}
      </td>
      <td className="py-2 pr-4">
        <span
          className={`rounded px-2 py-0.5 text-xs font-medium ${STATUS_STYLES[job.status] || ""}`}
        >
          {job.status}
        </span>
      </td>
      <td className="py-2 pr-4 text-sm text-slate-500">
        {formatBytes(job.bytes_in)} → {formatBytes(job.bytes_out)}
        {saved !== null && saved > 0 && (
          <span className="ml-1 text-emerald-600">({Math.round(saved * 100)}% saved)</span>
        )}
      </td>
      <td className="py-2 text-sm text-slate-400">{job.elapsed_s ? `${job.elapsed_s}s` : "—"}</td>
    </tr>
  );
}
