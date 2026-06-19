// Tests for the pure accountability math. No Supabase, no device — these prove the
// numbers a 92Y will brief are correct. Run with `npm test`.

import {
  absentRemarks,
  applyMealToInventory,
  buildStrengthReport,
  burnRate,
  daysOfSupply,
  forecastDaysRemaining,
  isLowStock,
  mealsOnHand,
  strengthReportToCsv,
  suggestedResupplyCases,
} from "../lib/calc";
import { RationCount, RationInventory, Section, Soldier } from "../lib/types";

const SECTIONS: Section[] = [
  { id: "g1", unit_id: "u", name: "GUN 1", sort_order: 1 },
  { id: "g2", unit_id: "u", name: "GUN 2", sort_order: 2 },
  { id: "g3", unit_id: "u", name: "GUN 3", sort_order: 3 },
  { id: "ammo", unit_id: "u", name: "AMMO", sort_order: 4 },
  { id: "fdc", unit_id: "u", name: "FDC", sort_order: 5 },
  { id: "hq", unit_id: "u", name: "HEADQUARTERS", sort_order: 6 },
];

function soldier(section_id: string, duty_status: Soldier["duty_status"]): Soldier {
  return {
    id: Math.random().toString(36).slice(2),
    unit_id: "u",
    section_id,
    rank: "PFC",
    last_name: "Doe",
    first_initial: "J",
    duty_status,
  };
}

function inv(partial: Partial<RationInventory> = {}): RationInventory {
  return {
    id: "inv",
    unit_id: "u",
    item: "MRE",
    on_hand_cases: 0,
    meals_per_case: 12,
    loose_meals: 0,
    reorder_point_meals: 0,
    ...partial,
  };
}

describe("strength rollup", () => {
  test("rolls up per-section and totals; empty sections still appear as 0/0", () => {
    const soldiers = [
      soldier("g1", "present"),
      soldier("g1", "present"),
      soldier("g1", "leave"),
      soldier("g2", "present"),
      soldier("ammo", "tdy"),
      soldier("fdc", "present"),
      soldier("hq", "sick"),
    ];
    const r = buildStrengthReport(SECTIONS, soldiers);

    expect(r.sections).toHaveLength(6); // all sections present, incl. empty GUN 3
    const g1 = r.sections.find((s) => s.name === "GUN 1")!;
    expect(g1).toMatchObject({ assigned: 3, present: 2, absent: 1 });
    const g3 = r.sections.find((s) => s.name === "GUN 3")!;
    expect(g3).toMatchObject({ assigned: 0, present: 0, absent: 0 });

    expect(r.total_assigned).toBe(7);
    expect(r.total_present).toBe(4);
    expect(r.total_absent).toBe(3);
  });

  test("absent reasons are broken out for the PERSTAT remarks", () => {
    const soldiers = [
      soldier("g1", "leave"),
      soldier("g2", "tdy"),
      soldier("g2", "tdy"),
      soldier("ammo", "sick"),
      soldier("hq", "awol"),
    ];
    const r = buildStrengthReport(SECTIONS, soldiers);
    expect(r.absent_by_status.leave).toBe(1);
    expect(r.absent_by_status.tdy).toBe(2);
    expect(r.absent_by_status.sick).toBe(1);
    expect(r.absent_by_status.awol).toBe(1);
    expect(absentRemarks(r)).toBe("Leave: 1, TDY: 2, Sick/Quarters: 1, AWOL: 1");
  });

  test("CSV export sums correctly", () => {
    const soldiers = [soldier("g1", "present"), soldier("g1", "leave")];
    const csv = strengthReportToCsv(buildStrengthReport(SECTIONS, soldiers));
    expect(csv.split("\n")[0]).toBe("Section,Assigned,Present,Absent");
    expect(csv).toContain("GUN 1,2,1,1");
    expect(csv.trim().endsWith("TOTAL,2,1,1")).toBe(true);
  });
});

describe("MRE inventory math", () => {
  test("meals on hand = cases x meals/case + loose", () => {
    expect(mealsOnHand(inv({ on_hand_cases: 10, loose_meals: 5 }))).toBe(125);
  });

  test("days of supply floors and handles nobody eating MREs", () => {
    // 240 meals, 30 present, 2 MRE meals/day => 60/day => 4 days
    expect(daysOfSupply(240, 30, 2)).toBe(4);
    expect(daysOfSupply(245, 30, 2)).toBe(4); // floors, never over-promises
    expect(daysOfSupply(240, 0, 2)).toBe(Infinity); // nobody on MREs
  });

  test("low stock triggers at/under the reorder point", () => {
    const i = inv({ on_hand_cases: 2, reorder_point_meals: 30 }); // 24 meals <= 30
    expect(isLowStock(i)).toBe(true);
    expect(isLowStock(inv({ on_hand_cases: 5, reorder_point_meals: 30 }))).toBe(false); // 60 > 30
  });

  test("logging an MRE meal deducts stock immutably; hot meals do not", () => {
    const start = inv({ on_hand_cases: 10, loose_meals: 0 }); // 120 meals
    const after = applyMealToInventory(start, { source: "MRE", headcount_fed: 30 });
    expect(mealsOnHand(after)).toBe(90);
    expect(after.on_hand_cases).toBe(7);
    expect(after.loose_meals).toBe(6); // a case got cracked
    expect(mealsOnHand(start)).toBe(120); // original untouched (immutable)

    const hot = applyMealToInventory(start, { source: "hot", headcount_fed: 30 });
    expect(hot).toBe(start); // hot meals don't touch the box count
  });

  test("stock floors at zero, never negative", () => {
    const after = applyMealToInventory(
      inv({ on_hand_cases: 1 }),
      { source: "MRE", headcount_fed: 999 },
    );
    expect(mealsOnHand(after)).toBe(0);
  });
});

describe("forecast + resupply", () => {
  test("burn rate averages MRE meals per logged day in the window", () => {
    const counts: RationCount[] = [
      { id: "1", unit_id: "u", section_id: "g1", meal_date: "2026-06-18", meal: "L", headcount_fed: 30, source: "MRE" },
      { id: "2", unit_id: "u", section_id: "g1", meal_date: "2026-06-18", meal: "D", headcount_fed: 30, source: "MRE" },
      { id: "3", unit_id: "u", section_id: "g1", meal_date: "2026-06-19", meal: "L", headcount_fed: 28, source: "MRE" },
      { id: "4", unit_id: "u", section_id: "g1", meal_date: "2026-06-19", meal: "B", headcount_fed: 100, source: "hot" }, // hot ignored
    ];
    // 2 days observed: day1=60, day2=28 => (60+28)/2 = 44 meals/day
    expect(burnRate(counts, 7, new Date("2026-06-19"))).toBe(44);
  });

  test("forecast prefers observed burn, falls back to planned", () => {
    expect(forecastDaysRemaining(240, 60, 40)).toBe(4); // observed used
    expect(forecastDaysRemaining(240, 0, 40)).toBe(6); // falls back to planned
  });

  test("suggested resupply rounds up to whole cases and ignores surplus", () => {
    // need 5 days @ 60/day = 300 meals; have 120 => short 180 => 15 cases (12/case)
    expect(suggestedResupplyCases(120, 60, 5, 12)).toBe(15);
    expect(suggestedResupplyCases(500, 60, 5, 12)).toBe(0); // already covered
  });
});
