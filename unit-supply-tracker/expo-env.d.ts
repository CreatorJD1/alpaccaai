/// <reference types="expo/types" />

// Ambient typings for the EXPO_PUBLIC_* env vars we read in lib/supabase.ts.
declare namespace NodeJS {
  interface ProcessEnv {
    EXPO_PUBLIC_SUPABASE_URL: string;
    EXPO_PUBLIC_SUPABASE_ANON_KEY: string;
  }
}
