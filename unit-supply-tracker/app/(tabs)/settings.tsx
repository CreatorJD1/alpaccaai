// Settings: who am I (role/unit), the OPSEC reminder, and sign out. Account
// management (inviting people, assigning section chiefs) is intentionally done in
// the Supabase dashboard for now — see README — because minting auth users is an
// admin action we keep off the public app surface to preserve invite-only.

import { Alert, Linking, Pressable, ScrollView, Text, View } from "react-native";
import { useSession } from "../../lib/session";
import { colors, space } from "../../lib/theme";

const ROLE_LABEL: Record<string, string> = {
  supply_clerk: "Supply Clerk (92Y)",
  supply_sergeant: "Supply Sergeant",
  section_chief: "Section Chief",
  viewer: "Viewer",
};

export default function Settings() {
  const { profile, signOut } = useSession();

  return (
    <ScrollView style={{ flex: 1, backgroundColor: colors.bg }} contentContainerStyle={{ padding: space.lg }}>
      <Card title="Account">
        <Line label="Role" value={ROLE_LABEL[profile?.role ?? ""] ?? "—"} />
        <Line label="Unit" value="C Battery · 2-218th FA" />
      </Card>

      <Card title="Privacy & OPSEC">
        <Text style={{ color: colors.dim, lineHeight: 20 }}>
          This is a private, invite-only accountability tool for the supply
          section. Store last name, rank, section and duty status only.
          {"\n\n"}
          Do NOT enter SSNs, DoD ID numbers, contact info, or any classified or
          operationally sensitive information. Treat all data as CUI.
        </Text>
      </Card>

      <Card title="Manage accounts">
        <Text style={{ color: colors.dim, lineHeight: 20, marginBottom: space.md }}>
          New users are invited by an admin in the Supabase dashboard (Auth →
          Invite), then attached to this unit with a role. Public sign-up is off.
        </Text>
        <Pressable
          onPress={() =>
            Linking.openURL("https://supabase.com/dashboard").catch(() =>
              Alert.alert("Open in browser", "https://supabase.com/dashboard"),
            )
          }
        >
          <Text style={{ color: colors.accent, fontWeight: "700" }}>Open Supabase dashboard ↗</Text>
        </Pressable>
      </Card>

      <Pressable
        onPress={() =>
          Alert.alert("Sign out", "Sign out of the tracker?", [
            { text: "Cancel", style: "cancel" },
            { text: "Sign out", style: "destructive", onPress: signOut },
          ])
        }
        style={{ backgroundColor: colors.panelAlt, borderColor: colors.bad, borderWidth: 1, borderRadius: 12, padding: space.lg, alignItems: "center", marginTop: space.md }}
      >
        <Text style={{ color: colors.bad, fontWeight: "800" }}>Sign out</Text>
      </Pressable>
    </ScrollView>
  );
}

function Card({ title, children }: { title: string; children: React.ReactNode }) {
  return (
    <View style={{ backgroundColor: colors.panel, borderColor: colors.border, borderWidth: 1, borderRadius: 12, padding: space.lg, marginBottom: space.lg }}>
      <Text style={{ color: colors.accent, fontWeight: "800", marginBottom: space.md }}>{title}</Text>
      {children}
    </View>
  );
}

function Line({ label, value }: { label: string; value: string }) {
  return (
    <View style={{ flexDirection: "row", justifyContent: "space-between", paddingVertical: space.xs }}>
      <Text style={{ color: colors.dim }}>{label}</Text>
      <Text style={{ color: colors.ink, fontWeight: "600" }}>{value}</Text>
    </View>
  );
}
