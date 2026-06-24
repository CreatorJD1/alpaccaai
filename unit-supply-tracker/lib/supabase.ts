// Supabase client — the single cloud connection for the whole app.
//
// Keys come from EXPO_PUBLIC_* env vars (see .env.example). The anon key is safe to
// ship in the bundle: it grants NOTHING on its own because every table is behind
// RLS (see supabase/migrations/0001_init.sql) — data is only reachable by an
// authenticated, unit-scoped, invited account. We persist the session in
// AsyncStorage so a soldier stays logged in between app opens.

import AsyncStorage from "@react-native-async-storage/async-storage";
import { createClient } from "@supabase/supabase-js";
import "react-native-url-polyfill/auto";

const url = process.env.EXPO_PUBLIC_SUPABASE_URL ?? "";
const anonKey = process.env.EXPO_PUBLIC_SUPABASE_ANON_KEY ?? "";

if (!url || !anonKey) {
  // Fail loud in dev rather than silently pointing at nothing.
  console.warn(
    "[supply-tracker] Missing EXPO_PUBLIC_SUPABASE_URL / _ANON_KEY. " +
      "Copy .env.example to .env and fill in your Supabase project values.",
  );
}

export const supabase = createClient(url, anonKey, {
  auth: {
    storage: AsyncStorage,
    autoRefreshToken: true,
    persistSession: true,
    detectSessionInUrl: false, // native app — no URL-based auth
  },
});
