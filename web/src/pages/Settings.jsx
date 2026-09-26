import { useEffect, useState } from "react";
import { supabase } from "../lib/supabase";
import { useAuth } from "../context/AuthContext";
import Card from "../components/ui/Card";
import Button from "../components/ui/Button";

function randomSecret() {
  // 32 bytes of crypto-quality randomness, hex-encoded — same entropy class
  // as SVCS's own device tokens (src/gui/device_tokens.py: 256-bit).
  const bytes = crypto.getRandomValues(new Uint8Array(32));
  return Array.from(bytes)
    .map((b) => b.toString(16).padStart(2, "0"))
    .join("");
}

// Supabase's Edge Function invocation URL: <project>.functions.supabase.co/<fn>.
// Derived from VITE_SUPABASE_URL so nobody has to type it in twice.
function ingestFunctionUrl() {
  const base = import.meta.env.VITE_SUPABASE_URL || "";
  const host = base.replace("https://", "").replace(".supabase.co", "");
  return `https://${host}.functions.supabase.co/ingest-job`;
}

export default function Settings() {
  const { profile, user } = useAuth();
  const [displayName, setDisplayName] = useState(profile?.display_name || "");
  const [savingName, setSavingName] = useState(false);
  const [nameNotice, setNameNotice] = useState("");

  const [tokens, setTokens] = useState([]);
  const [loadingTokens, setLoadingTokens] = useState(true);
  const [newSecret, setNewSecret] = useState(""); // shown once, right after generating
  const [label, setLabel] = useState("My desktop app");

  async function loadTokens() {
    const { data } = await supabase
      .from("ingest_tokens")
      .select("id, label, created_at, last_used_at")
      .order("created_at", { ascending: false });
    setTokens(data || []);
    setLoadingTokens(false);
  }

  useEffect(() => {
    loadTokens();
  }, []);

  async function handleSaveName(e) {
    e.preventDefault();
    setSavingName(true);
    const { error } = await supabase
      .from("profiles")
      .update({ display_name: displayName })
      .eq("id", user.id);
    setSavingName(false);
    setNameNotice(error ? error.message : "Saved.");
  }

  async function handleGenerateToken(e) {
    e.preventDefault();
    const secret = randomSecret();
    const { error } = await supabase.from("ingest_tokens").insert({
      user_id: user.id,
      label,
      secret,
    });
    if (error) {
      setNewSecret("");
      return;
    }
    setNewSecret(secret);
    loadTokens();
  }

  async function handleDeleteToken(id) {
    await supabase.from("ingest_tokens").delete().eq("id", id);
    loadTokens();
  }

  return (
    <div className="space-y-8">
      <div>
        <h1 className="mb-4 text-lg font-semibold text-slate-900">Profile</h1>
        <Card className="p-4">
          <form onSubmit={handleSaveName} className="flex items-end gap-3">
            <div className="flex-1">
              <label
                htmlFor="settings-display-name"
                className="mb-1 block text-sm font-medium text-slate-700"
              >
                Display name
              </label>
              <input
                id="settings-display-name"
                value={displayName}
                onChange={(e) => setDisplayName(e.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
              />
            </div>
            <Button type="submit" disabled={savingName}>
              Save
            </Button>
          </form>
          {nameNotice && <p className="mt-2 text-sm text-slate-500">{nameNotice}</p>}
        </Card>
      </div>

      <div>
        <h1 className="mb-1 text-lg font-semibold text-slate-900">Connect a desktop app</h1>
        <p className="mb-4 text-sm text-slate-500">
          In the SVCS desktop app: Settings → Webhook. Turn it on, paste the URL below into
          &quot;Webhook URL&quot;, and paste the generated secret into &quot;Secret&quot;. Every
          finished job then syncs here automatically — nothing else in the desktop app changes.
        </p>
        <Card className="p-4">
          <div className="mb-4 rounded-md bg-slate-50 p-3 font-mono text-sm text-slate-700">
            {ingestFunctionUrl()}
          </div>

          <form onSubmit={handleGenerateToken} className="mb-4 flex items-end gap-3">
            <div className="flex-1">
              <label
                htmlFor="ingest-token-label"
                className="mb-1 block text-sm font-medium text-slate-700"
              >
                Label
              </label>
              <input
                id="ingest-token-label"
                value={label}
                onChange={(e) => setLabel(e.target.value)}
                className="w-full rounded-md border border-slate-300 px-3 py-2 text-sm focus:border-brand-500 focus:outline-none"
              />
            </div>
            <Button type="submit">Generate a new secret</Button>
          </form>

          {newSecret && (
            <div className="mb-4 rounded-md border border-amber-300 bg-amber-50 p-3">
              <p className="mb-1 text-sm font-medium text-amber-800">
                Copy this now — paste it into the desktop app&apos;s Webhook secret field.
              </p>
              <code className="break-all text-sm text-amber-900">{newSecret}</code>
            </div>
          )}

          {loadingTokens ? (
            <p className="text-sm text-slate-500">Loading…</p>
          ) : (
            <table className="w-full text-left">
              <thead>
                <tr className="border-b border-slate-200 text-xs uppercase tracking-wide text-slate-400">
                  <th className="pb-2 pr-4 font-medium">Label</th>
                  <th className="pb-2 pr-4 font-medium">Created</th>
                  <th className="pb-2 pr-4 font-medium">Last used</th>
                  <th className="pb-2 font-medium"></th>
                </tr>
              </thead>
              <tbody>
                {tokens.map((t) => (
                  <tr key={t.id} className="border-b border-slate-100 last:border-0">
                    <td className="py-2 pr-4 text-sm text-slate-700">{t.label}</td>
                    <td className="py-2 pr-4 text-sm text-slate-500">
                      {new Date(t.created_at).toLocaleDateString()}
                    </td>
                    <td className="py-2 pr-4 text-sm text-slate-500">
                      {t.last_used_at ? new Date(t.last_used_at).toLocaleString() : "never"}
                    </td>
                    <td className="py-2">
                      <Button variant="danger" onClick={() => handleDeleteToken(t.id)}>
                        Revoke
                      </Button>
                    </td>
                  </tr>
                ))}
                {tokens.length === 0 && (
                  <tr>
                    <td colSpan={4} className="py-2 text-sm text-slate-500">
                      No desktop apps connected yet.
                    </td>
                  </tr>
                )}
              </tbody>
            </table>
          )}
        </Card>
      </div>
    </div>
  );
}
