// PERSTAT / strength rollup. The same numbers as the board, formatted as a report
// you can share up the chain: present-for-duty by section, totals, and an
// absent-reason remarks line. The Share button hands a CSV to the OS share sheet
// (email, Signal, etc.) — built from calc.strengthReportToCsv so it always matches
// what's on screen.

import { useMemo } from "react";
import { Pressable, RefreshControl, ScrollView, Share, Text, View } from "react-native";
import { useSession } from "../../lib/session";
import { useUnitData } from "../../lib/useUnitData";
import { absentRemarks, buildStrengthReport, strengthReportToCsv } from "../../lib/calc";
import { colors, space } from "../../lib/theme";

export default function Perstat() {
  const { profile } = useSession();
  const { sections, roster, loading, reload } = useUnitData(profile?.unit_id);
  const report = useMemo(() => buildStrengthReport(sections, roster), [sections, roster]);
  const dateStr = new Date().toISOString().slice(0, 10);

  async function shareCsv() {
    const remarks = absentRemarks(report);
    const body =
      `PERSTAT — C/2-218th FA — ${dateStr}\n\n` +
      strengthReportToCsv(report) +
      (remarks ? `\n\nRemarks: ${remarks}` : "");
    try {
      await Share.share({ message: body, title: `PERSTAT ${dateStr}` });
    } catch {
      /* user dismissed share sheet */
    }
  }

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.bg }}
      contentContainerStyle={{ padding: space.lg }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={reload} tintColor={colors.accent} />}
    >
      <Text style={{ color: colors.dim }}>{dateStr}</Text>
      <Text style={{ color: colors.ink, fontSize: 22, fontWeight: "900", marginBottom: space.md }}>
        Personnel Status
      </Text>

      {/* Table header */}
      <Row bold name="Section" a="ASGD" p="PRES" x="ABS" />
      {report.sections.map((s) => (
        <Row key={s.section_id} name={s.name} a={s.assigned} p={s.present} x={s.absent} warn={s.absent > 0} />
      ))}
      <View style={{ height: 1, backgroundColor: colors.border, marginVertical: space.sm }} />
      <Row bold name="TOTAL" a={report.total_assigned} p={report.total_present} x={report.total_absent} />

      {/* Remarks */}
      {absentRemarks(report) ? (
        <View style={{ backgroundColor: colors.panel, borderColor: colors.border, borderWidth: 1, borderRadius: 12, padding: space.lg, marginTop: space.lg }}>
          <Text style={{ color: colors.dim, fontSize: 12 }}>REMARKS (absent by reason)</Text>
          <Text style={{ color: colors.ink, marginTop: space.xs }}>{absentRemarks(report)}</Text>
        </View>
      ) : null}

      <Pressable onPress={shareCsv} style={{ backgroundColor: colors.accent, borderRadius: 12, padding: space.lg, alignItems: "center", marginTop: space.xl }}>
        <Text style={{ color: colors.accentInk, fontWeight: "800" }}>Share PERSTAT (CSV)</Text>
      </Pressable>
    </ScrollView>
  );
}

function Row({
  name,
  a,
  p,
  x,
  bold,
  warn,
}: {
  name: string;
  a: number | string;
  p: number | string;
  x: number | string;
  bold?: boolean;
  warn?: boolean;
}) {
  const w = bold ? "800" : "500";
  return (
    <View style={{ flexDirection: "row", paddingVertical: space.sm }}>
      <Text style={{ flex: 2, color: bold ? colors.accent : colors.ink, fontWeight: w as any }}>{name}</Text>
      <Text style={{ flex: 1, color: colors.ink, textAlign: "right", fontWeight: w as any }}>{a}</Text>
      <Text style={{ flex: 1, color: colors.good, textAlign: "right", fontWeight: w as any }}>{p}</Text>
      <Text style={{ flex: 1, color: warn ? colors.warn : colors.dim, textAlign: "right", fontWeight: w as any }}>{x}</Text>
    </View>
  );
}
