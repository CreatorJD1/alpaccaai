// Typed data access — the only place screens talk to Supabase. Keeping every read
// and write here (instead of scattered through screens) means the access pattern,
// and the unit-scoping, is reviewable in one file. The math still lives in calc.ts;
// this file just fetches rows and hands them off.

import { supabase } from "./supabase";
import {
  RationCount,
  RationInventory,
  Role,
  Section,
  Soldier,
} from "./types";

export interface Profile {
  id: string;
  unit_id: string;
  role: Role;
  section_id: string | null;
  full_name: string | null;
}

/** The signed-in user's profile (role + unit). Null if they have no profile yet
 *  (i.e. not invited) — the app treats that as "no access". */
export async function fetchMyProfile(): Promise<Profile | null> {
  const { data: auth } = await supabase.auth.getUser();
  if (!auth.user) return null;
  const { data, error } = await supabase
    .from("profiles")
    .select("id, unit_id, role, section_id, full_name")
    .eq("id", auth.user.id)
    .maybeSingle();
  if (error) throw error;
  return (data as Profile) ?? null;
}

export async function fetchSections(unitId: string): Promise<Section[]> {
  const { data, error } = await supabase
    .from("sections")
    .select("id, unit_id, name, sort_order")
    .eq("unit_id", unitId)
    .order("sort_order");
  if (error) throw error;
  return (data ?? []) as Section[];
}

export async function fetchRoster(unitId: string): Promise<Soldier[]> {
  const { data, error } = await supabase
    .from("soldiers")
    .select("id, unit_id, section_id, rank, last_name, first_initial, duty_status, notes")
    .eq("unit_id", unitId)
    .order("last_name");
  if (error) throw error;
  return (data ?? []) as Soldier[];
}

export async function upsertSoldier(s: Partial<Soldier> & { unit_id: string; section_id: string }): Promise<void> {
  const { error } = await supabase.from("soldiers").upsert({
    ...s,
    updated_at: new Date().toISOString(),
  });
  if (error) throw error;
}

export async function setDutyStatus(id: string, duty_status: Soldier["duty_status"]): Promise<void> {
  const { error } = await supabase
    .from("soldiers")
    .update({ duty_status, updated_at: new Date().toISOString() })
    .eq("id", id);
  if (error) throw error;
}

export async function deleteSoldier(id: string): Promise<void> {
  const { error } = await supabase.from("soldiers").delete().eq("id", id);
  if (error) throw error;
}

export async function fetchMreInventory(unitId: string): Promise<RationInventory | null> {
  const { data, error } = await supabase
    .from("ration_inventory")
    .select("*")
    .eq("unit_id", unitId)
    .eq("item", "MRE")
    .maybeSingle();
  if (error) throw error;
  return (data as RationInventory) ?? null;
}

export async function saveMreInventory(inv: RationInventory): Promise<void> {
  const { error } = await supabase.from("ration_inventory").upsert({
    ...inv,
    updated_at: new Date().toISOString(),
  });
  if (error) throw error;
}

export async function fetchRecentRationCounts(unitId: string, sinceDate: string): Promise<RationCount[]> {
  const { data, error } = await supabase
    .from("ration_counts")
    .select("id, unit_id, section_id, meal_date, meal, headcount_fed, source, entered_by")
    .eq("unit_id", unitId)
    .gte("meal_date", sinceDate)
    .order("meal_date", { ascending: false });
  if (error) throw error;
  return (data ?? []) as RationCount[];
}

/** Log a chow count for one section at one meal. The caller separately applies the
 *  MRE deduction to inventory (calc.applyMealToInventory) and saves it. */
export async function logRationCount(c: Omit<RationCount, "id">): Promise<void> {
  const { error } = await supabase.from("ration_counts").insert(c);
  if (error) throw error;
}
