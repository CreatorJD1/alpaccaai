// Shared domain types for the Unit Supply & Rations Tracker.
//
// These mirror the Supabase schema (see supabase/migrations) but are kept here as
// plain TypeScript so the pure calc layer (lib/calc.ts) and its tests never need a
// database or network — the math is provable in isolation. We deliberately model
// ONLY what a 92Y needs for accountability: who is in what section, whether they
// are present, and how much chow is on hand. There is intentionally no SSN / DoD
// ID / contact field anywhere in the type system — that absence is a feature.

/** Duty status drives present-for-duty rollups and the PERSTAT report. */
export type DutyStatus =
  | "present" // present for duty
  | "leave" // ordinary / emergency leave, pass
  | "tdy" // TDY / schools / temporary duty away
  | "sick" // sick call / quarters / profile non-available
  | "appointment" // medical/admin appointment
  | "details" // on detail / tasking away from the section
  | "awol"; // unaccounted for

/** The fixed sections of a field artillery battery (seeded for C/2-218th FA). */
export type SectionName =
  | "GUN 1"
  | "GUN 2"
  | "GUN 3"
  | "AMMO"
  | "FDC"
  | "HEADQUARTERS";

/** App roles. Access is enforced server-side by Supabase RLS, not just here. */
export type Role = "supply_clerk" | "supply_sergeant" | "section_chief" | "viewer";

export interface Section {
  id: string;
  unit_id: string;
  name: SectionName;
  sort_order: number;
}

export interface Soldier {
  id: string;
  unit_id: string;
  section_id: string;
  rank: string;
  last_name: string;
  first_initial: string;
  duty_status: DutyStatus;
  notes?: string | null;
}

/** Class I (subsistence) on-hand. We track MREs by case + loose meals. */
export interface RationInventory {
  id: string;
  unit_id: string;
  item: "MRE" | "A_RATION" | "UGR";
  on_hand_cases: number;
  meals_per_case: number; // MRE default = 12 meals/case
  loose_meals: number; // partial case / individually issued
  reorder_point_meals: number;
  updated_at?: string;
}

export type MealSlot = "B" | "L" | "D" | "Midnight";

/** One section's headcount fed at one meal. MRE-sourced counts deduct stock. */
export interface RationCount {
  id: string;
  unit_id: string;
  section_id: string;
  meal_date: string; // ISO date (YYYY-MM-DD)
  meal: MealSlot;
  headcount_fed: number;
  source: "MRE" | "hot";
  entered_by?: string;
}

/** Result of rolling the roster up by section for the headcount board. */
export interface SectionRollup {
  section_id: string;
  name: string;
  assigned: number;
  present: number;
  absent: number;
}

export interface StrengthReport {
  sections: SectionRollup[];
  total_assigned: number;
  total_present: number;
  total_absent: number;
  /** Absent broken out by reason, for the PERSTAT remarks line. */
  absent_by_status: Record<Exclude<DutyStatus, "present">, number>;
}
