// Bottom tab navigation for the main app: Board, Roster, Rations, PERSTAT,
// Settings. Tabs use plain text labels (no icon font dependency) so the build
// stays lean. Header shows the unit name.

import { Tabs } from "expo-router";
import { Text } from "react-native";
import { colors } from "../../lib/theme";

function tabLabel(label: string) {
  return ({ color }: { color: string }) => (
    <Text style={{ color, fontSize: 11, fontWeight: "700" }}>{label}</Text>
  );
}

export default function TabsLayout() {
  return (
    <Tabs
      screenOptions={{
        headerStyle: { backgroundColor: colors.panel },
        headerTitleStyle: { color: colors.ink },
        tabBarStyle: { backgroundColor: colors.panel, borderTopColor: colors.border },
        tabBarActiveTintColor: colors.accent,
        tabBarInactiveTintColor: colors.dim,
      }}
    >
      <Tabs.Screen name="index" options={{ title: "Headcount", tabBarLabel: tabLabel("Board") }} />
      <Tabs.Screen name="roster" options={{ title: "Master Roster", tabBarLabel: tabLabel("Roster") }} />
      <Tabs.Screen name="rations" options={{ title: "Rations / MREs", tabBarLabel: tabLabel("Rations") }} />
      <Tabs.Screen name="perstat" options={{ title: "PERSTAT", tabBarLabel: tabLabel("PERSTAT") }} />
      <Tabs.Screen name="settings" options={{ title: "Settings", tabBarLabel: tabLabel("Settings") }} />
    </Tabs>
  );
}
