// Pure accountability math — no I/O, no database, no network.
//
// Everything a 92Y needs to *trust* the numbers lives here as plain functions so it
// can be unit-tested without Supabase or a phone (mirrors the "pure logic, fully
// testable" convention from the sibling Alpecca project). The screens call these;
// they never re-implement the math inline. If a number on the board looks wrong,
// it is debuggable here in isolation.

import {
  DutyStatus,
  RationCount,
  RationInventory,
  Section,
  Soldier,
  SectionRollup,
  StrengthReport,
} from "./types";

/** A soldier counts as "present for duty" only when explicitly present. */
export function isPresent(s: Pick<Soldier, "duty_status">): boolean {
  return s.duty_status === "present";
}

/**
 * Roll the roster up by section: assigned / present / absent per section plus a
 * battalion (battery) total, and a breakdown of *why* people are absent for the
 * PERSTAT remarks. Sections with zero soldiers still appear (so an empty GUN 3
 * shows as 0/0, not as missing) — that's why sections are passed in explicitly.
 */
export function buildStrengthReport(
  sections: Section[],
  soldiers: Soldier[],
): StrengthReport {
  const bySection = new Map<string, SectionRollup>();
  const ordered = [...sections].sort((a, b) => a.sort_order - b.sort_order);
  for (const sec of ordered) {
    bySection.set(sec.id, {
      section_id: sec.id,
      name: sec.name,
      assigned: 0,
      present: 0,
      absent: 0,
    });
  }

  const absentByStatus: Record<string, number> = {
    leave: 0,
    tdy: 0,
    sick: 0,
    appointment: 0,
    details: 0,
    awol: 0,
  };

  for (const sol of soldiers) {
    const roll = bySection.get(sol.section_id);
    if (!roll) continue; // soldier in a section we weren't given — skip defensively
    roll.assigned += 1;
    if (isPresent(sol)) {
      roll.present += 1;
    } else {
      roll.absent += 1;
      absentByStatus[sol.duty_status] = (absentByStatus[sol.duty_status] ?? 0) + 1;
    }
  }

  const rollups = ordered.map((sec) => bySection.get(sec.id)!);
  const total_assigned = rollups.reduce((n, r) => n + r.assigned, 0);
  const total_present = rollups.reduce((n, r) => n + r.present, 0);

  return {
    sections: rollups,
    total_assigned,
    total_present,
    total_absent: total_assigned - total_present,
    absent_by_status: absentByStatus as StrengthReport["absent_by_status"],
  };
}

/** Total MRE meals on hand = full cases × meals/case + loose meals. */
export function mealsOnHand(inv: Pick<RationInventory, "on_hand_cases" | "meals_per_case" | "loose_meals">): number {
  return Math.max(0, Math.round(inv.on_hand_cases * inv.meals_per_case + inv.loose_meals));
}

/**
 * Days of MRE supply at the *planned* burn: present troops × meals/day on the MRE
 * cycle. Returns Infinity only when nobody is eating MREs (so the UI can show "—").
 * Rounded down to whole days — you never want to over-promise chow.
 */
export function daysOfSupply(
  meals: number,
  presentTroops: number,
  mealsPerDayOnMRE: number,
): number {
  const dailyBurn = presentTroops * mealsPerDayOnMRE;
  if (dailyBurn <= 0) return Infinity;
  return Math.floor(meals / dailyBurn);
}

/**
 * Observed burn rate (MRE meals/day) over the most recent `windowDays` of logged
 * meal counts. Only MRE-sourced counts burn stock — hot meals don't touch the box
 * inventory. Used for the forecast so the projection reflects how the unit is
 * *actually* eating, not just the plan.
 */
export function burnRate(
  counts: RationCount[],
  windowDays: number,
  today: Date = new Date(),
): number {
  if (windowDays <= 0) return 0;
  const cutoff = new Date(today);
  cutoff.setDate(cutoff.getDate() - (windowDays - 1));
  const cutoffStr = cutoff.toISOString().slice(0, 10);

  let mealsBurned = 0;
  const days = new Set<string>();
  for (const c of counts) {
    if (c.source !== "MRE") continue;
    if (c.meal_date < cutoffStr) continue;
    mealsBurned += Math.max(0, c.headcount_fed);
    days.add(c.meal_date);
  }
  const observedDays = days.size || 0;
  if (observedDays === 0) return 0;
  return mealsBurned / observedDays;
}

/** Forecast days remaining at the observed burn rate (falls back to planned). */
export function forecastDaysRemaining(
  meals: number,
  observedBurnPerDay: number,
  plannedBurnPerDay: number,
): number {
  const burn = observedBurnPerDay > 0 ? observedBurnPerDay : plannedBurnPerDay;
  if (burn <= 0) return Infinity;
  return Math.floor(meals / burn);
}

/** Are we at/under the reorder point? Drives the low-stock alert + request helper. */
export function isLowStock(inv: Pick<RationInventory, "on_hand_cases" | "meals_per_case" | "loose_meals" | "reorder_point_meals">): boolean {
  return mealsOnHand(inv) <= inv.reorder_point_meals;
}

/**
 * Suggested resupply in *cases* to carry the unit `targetDays` forward at the
 * given daily burn, accounting for what's already on hand. Rounds up — you order
 * whole cases, and short chow is worse than a little extra.
 */
export function suggestedResupplyCases(
  meals: number,
  burnPerDay: number,
  targetDays: number,
  mealsPerCase: number,
): number {
  if (mealsPerCase <= 0) return 0;
  const needed = burnPerDay * targetDays - meals;
  if (needed <= 0) return 0;
  return Math.ceil(needed / mealsPerCase);
}

/**
 * Apply a logged MRE meal count to inventory, returning the *new* inventory
 * (immutable-style — we never mutate the passed object, so callers/tests can diff
 * before/after). Hot-meal counts pass through untouched. Stock floors at zero;
 * loose meals are drawn down first, then whole cases are cracked as needed.
 */
export function applyMealToInventory(
  inv: RationInventory,
  count: Pick<RationCount, "source" | "headcount_fed">,
): RationInventory {
  if (count.source !== "MRE" || count.headcount_fed <= 0) return inv;

  let totalMeals = mealsOnHand(inv) - count.headcount_fed;
  if (totalMeals < 0) totalMeals = 0;

  const on_hand_cases = Math.floor(totalMeals / inv.meals_per_case);
  const loose_meals = totalMeals - on_hand_cases * inv.meals_per_case;

  return { ...inv, on_hand_cases, loose_meals };
}

/** CSV body for the PERSTAT export — plain text, easy to share up the chain. */
export function strengthReportToCsv(report: StrengthReport): string {
  const lines = ["Section,Assigned,Present,Absent"];
  for (const s of report.sections) {
    lines.push(`${s.name},${s.assigned},${s.present},${s.absent}`);
  }
  lines.push(
    `TOTAL,${report.total_assigned},${report.total_present},${report.total_absent}`,
  );
  return lines.join("\n");
}

/** Human-readable absent-reason summary for a PERSTAT remarks line. */
export function absentRemarks(report: StrengthReport): string {
  const order: Array<[DutyStatus, string]> = [
    ["leave", "Leave"],
    ["tdy", "TDY"],
    ["sick", "Sick/Quarters"],
    ["appointment", "Appt"],
    ["details", "Detail"],
    ["awol", "AWOL"],
  ];
  const parts: string[] = [];
  for (const [k, label] of order) {
    const n = (report.absent_by_status as Record<string, number>)[k] ?? 0;
    if (n > 0) parts.push(`${label}: ${n}`);
  }
  return parts.join(", ");
}
