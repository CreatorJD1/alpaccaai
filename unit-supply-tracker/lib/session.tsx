// Session context — tracks the Supabase auth session + the signed-in user's
// profile (role/unit). The whole app keys off this: no profile => no access
// (invite-only), and the role decides what each screen lets you do.

import React, { createContext, useContext, useEffect, useState } from "react";
import type { Session } from "@supabase/supabase-js";
import { supabase } from "./supabase";
import { fetchMyProfile, Profile } from "./queries";

interface SessionState {
  loading: boolean;
  session: Session | null;
  profile: Profile | null;
  isAdmin: boolean; // supply_clerk or supply_sergeant
  refreshProfile: () => Promise<void>;
  signOut: () => Promise<void>;
}

const Ctx = createContext<SessionState | undefined>(undefined);

export function SessionProvider({ children }: { children: React.ReactNode }) {
  const [loading, setLoading] = useState(true);
  const [session, setSession] = useState<Session | null>(null);
  const [profile, setProfile] = useState<Profile | null>(null);

  async function loadProfile() {
    try {
      setProfile(await fetchMyProfile());
    } catch {
      setProfile(null); // no profile / not invited => locked out
    }
  }

  useEffect(() => {
    let active = true;
    supabase.auth.getSession().then(async ({ data }) => {
      if (!active) return;
      setSession(data.session);
      if (data.session) await loadProfile();
      setLoading(false);
    });

    const { data: sub } = supabase.auth.onAuthStateChange(async (_event, sess) => {
      setSession(sess);
      if (sess) await loadProfile();
      else setProfile(null);
    });
    return () => {
      active = false;
      sub.subscription.unsubscribe();
    };
  }, []);

  const value: SessionState = {
    loading,
    session,
    profile,
    isAdmin:
      profile?.role === "supply_clerk" || profile?.role === "supply_sergeant",
    refreshProfile: loadProfile,
    signOut: async () => {
      await supabase.auth.signOut();
    },
  };

  return <Ctx.Provider value={value}>{children}</Ctx.Provider>;
}

export function useSession(): SessionState {
  const v = useContext(Ctx);
  if (!v) throw new Error("useSession must be used within SessionProvider");
  return v;
}
