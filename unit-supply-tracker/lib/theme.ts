// A small, military-flavored design token set shared by every screen — olive/field
// palette, duty-status colors, and spacing. Centralized so the look is consistent
// and a single edit re-skins the app.

export const colors = {
  bg: "#10140c", // field dark
  panel: "#1b2114",
  panelAlt: "#232b18",
  border: "#3a4527",
  ink: "#e9efd8",
  dim: "#a7b388",
  accent: "#7f9b3f", // OD green
  accentInk: "#0c0f07",
  good: "#6fae3f", // present / healthy
  warn: "#d6a52b", // low stock / attention
  bad: "#c0492f", // AWOL / critical
};

/** Color for a duty status chip. */
export const statusColor: Record<string, string> = {
  present: colors.good,
  leave: "#5b86c4",
  tdy: "#8a6fbf",
  sick: colors.warn,
  appointment: "#c98a3a",
  details: "#7f9b3f",
  awol: colors.bad,
};

export const statusLabel: Record<string, string> = {
  present: "Present",
  leave: "Leave",
  tdy: "TDY",
  sick: "Sick/Qtrs",
  appointment: "Appt",
  details: "Detail",
  awol: "AWOL",
};

export const space = { xs: 4, sm: 8, md: 12, lg: 16, xl: 24 };
