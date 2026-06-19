// Headcount Board (home). The at-a-glance answer to "how many do we have, by
// section, right now?" A big battery TOTAL up top, then a tile per section
// (GUN 1/2/3, AMMO, FDC, HEADQUARTERS) showing present / assigned. Live — it
// re-rolls whenever anyone updates a duty status (useUnitData realtime).

import { useMemo } from "react";
import { RefreshControl, ScrollView, Text, View } from "react-native";
import { useSession } from "../../lib/session";
import { useUnitData } from "../../lib/useUnitData";
import { buildStrengthReport } from "../../lib/calc";
import { colors, space } from "../../lib/theme";

export default function Board() {
  const { profile } = useSession();
  const { sections, roster, loading, error, reload } = useUnitData(profile?.unit_id);

  const report = useMemo(
    () => buildStrengthReport(sections, roster),
    [sections, roster],
  );

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.bg }}
      contentContainerStyle={{ padding: space.lg }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={reload} tintColor={colors.accent} />}
    >
      {error && <Text style={{ color: colors.bad, marginBottom: space.md }}>{error}</Text>}

      {/* Battery total */}
      <View
        style={{
          backgroundColor: colors.panel,
          borderColor: colors.border,
          borderWidth: 1,
          borderRadius: 14,
          padding: space.xl,
          marginBottom: space.lg,
          alignItems: "center",
        }}
      >
        <Text style={{ color: colors.dim, letterSpacing: 1 }}>BATTERY PRESENT / ASSIGNED</Text>
        <Text style={{ color: colors.ink, fontSize: 44, fontWeight: "900" }}>
          {report.total_present}
          <Text style={{ color: colors.dim, fontSize: 26 }}> / {report.total_assigned}</Text>
        </Text>
        <Text style={{ color: report.total_absent > 0 ? colors.warn : colors.good }}>
          {report.total_absent} absent
        </Text>
      </View>

      {/* Per-section tiles, 2 columns */}
      <View style={{ flexDirection: "row", flexWrap: "wrap", justifyContent: "space-between" }}>
        {report.sections.map((s) => {
          const accountedFor = s.assigned > 0;
          return (
            <View
              key={s.section_id}
              style={{
                width: "48.5%",
                backgroundColor: colors.panelAlt,
                borderColor: colors.border,
                borderWidth: 1,
                borderRadius: 12,
                padding: space.lg,
                marginBottom: space.md,
              }}
            >
              <Text style={{ color: colors.accent, fontWeight: "800", letterSpacing: 0.5 }}>{s.name}</Text>
              <Text style={{ color: colors.ink, fontSize: 28, fontWeight: "900" }}>
                {s.present}
                <Text style={{ color: colors.dim, fontSize: 18 }}> / {s.assigned}</Text>
              </Text>
              <Text style={{ color: s.absent > 0 ? colors.warn : colors.dim, fontSize: 12 }}>
                {accountedFor ? `${s.absent} out` : "no soldiers assigned"}
              </Text>
            </View>
          );
        })}
      </View>

      <Text style={{ color: colors.dim, fontSize: 11, marginTop: space.md, textAlign: "center" }}>
        Live — updates as sections change duty status. Pull to refresh.
      </Text>
    </ScrollView>
  );
}
