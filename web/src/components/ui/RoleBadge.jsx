const STYLES = {
  admin: "bg-purple-100 text-purple-700",
  operator: "bg-brand-100 text-brand-700",
  guest: "bg-slate-100 text-slate-600",
};

export default function RoleBadge({ role }) {
  return (
    <span className={`rounded-full px-2.5 py-0.5 text-xs font-medium ${STYLES[role] || STYLES.guest}`}>
      {role || "unknown"}
    </span>
  );
}
