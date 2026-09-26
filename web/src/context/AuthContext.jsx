// src/context/AuthContext.jsx — signed-in user + their profile (role),
// available everywhere via useAuth(). Loads the profiles row once a
// session exists, and keeps both in sync with Supabase's own auth state
// changes (sign-in, sign-out, token refresh).
import { createContext, useContext, useEffect, useState } from "react";
import { supabase } from "../lib/supabase";

const AuthContext = createContext(null);

export function AuthProvider({ children }) {
  const [session, setSession] = useState(null);
  const [profile, setProfile] = useState(null);
  const [loading, setLoading] = useState(true);

  async function loadProfile(userId) {
    if (!userId) {
      setProfile(null);
      return;
    }
    const { data, error } = await supabase
      .from("profiles")
      .select("id, display_name, role, created_at")
      .eq("id", userId)
      .single();
    if (error) {
      // A brand-new user's profile row is created by a database trigger
      // (see supabase/schema.sql) right after sign-up; if this races it,
      // treat it as "still loading" rather than an error.
      setProfile(null);
      return;
    }
    setProfile(data);
  }

  useEffect(() => {
    supabase.auth.getSession().then(async ({ data: { session } }) => {
      setSession(session);
      await loadProfile(session?.user?.id);
      setLoading(false);
    });

    const { data: listener } = supabase.auth.onAuthStateChange(async (_event, session) => {
      setSession(session);
      setLoading(true);
      await loadProfile(session?.user?.id);
      setLoading(false);
    });

    return () => listener.subscription.unsubscribe();
  }, []);

  const value = {
    session,
    user: session?.user ?? null,
    profile,
    role: profile?.role ?? null,
    loading,
    signOut: () => supabase.auth.signOut(),
  };

  return <AuthContext.Provider value={value}>{children}</AuthContext.Provider>;
}

export function useAuth() {
  const ctx = useContext(AuthContext);
  if (!ctx) throw new Error("useAuth must be used inside <AuthProvider>");
  return ctx;
}
