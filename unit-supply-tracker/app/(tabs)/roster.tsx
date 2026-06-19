// Master Roster. Grouped by section, searchable. Tap a soldier to change duty
// status (the change is what drives the live board). Admins (clerk / supply
// sergeant) can add and remove soldiers; section chiefs see the roster read-only
// except for their own people's status. We store rank / last name / first initial
// / section / status only — no SSN, no DoD ID (by design).

import { useMemo, useState } from "react";
import {
  Alert,
  FlatList,
  Modal,
  Pressable,
  RefreshControl,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSession } from "../../lib/session";
import { useUnitData } from "../../lib/useUnitData";
import { deleteSoldier, setDutyStatus, upsertSoldier } from "../../lib/queries";
import { DutyStatus, Soldier } from "../../lib/types";
import { colors, space, statusColor, statusLabel } from "../../lib/theme";

const STATUSES: DutyStatus[] = [
  "present",
  "leave",
  "tdy",
  "sick",
  "appointment",
  "details",
  "awol",
];

export default function Roster() {
  const { profile, isAdmin } = useSession();
  const { sections, roster, loading, error, reload } = useUnitData(profile?.unit_id);
  const [query, setQuery] = useState("");
  const [statusFor, setStatusFor] = useState<Soldier | null>(null);
  const [showAdd, setShowAdd] = useState(false);

  const sectionName = useMemo(() => {
    const m = new Map(sections.map((s) => [s.id, s.name]));
    return (id: string) => m.get(id) ?? "—";
  }, [sections]);

  // Flatten into section-grouped rows for a sectioned list feel.
  const rows = useMemo(() => {
    const q = query.trim().toLowerCase();
    const filtered = roster.filter(
      (s) =>
        !q ||
        s.last_name.toLowerCase().includes(q) ||
        sectionName(s.section_id).toLowerCase().includes(q) ||
        s.rank.toLowerCase().includes(q),
    );
    const ordered = [...sections].sort((a, b) => a.sort_order - b.sort_order);
    const out: Array<{ header?: string } & Partial<Soldier>> = [];
    for (const sec of ordered) {
      const members = filtered.filter((s) => s.section_id === sec.id);
      if (members.length === 0 && q) continue;
      out.push({ header: `${sec.name}  (${members.length})` });
      members.forEach((m) => out.push(m));
    }
    return out;
  }, [roster, sections, query, sectionName]);

  // A section chief may change status only for their own section.
  const canEditStatus = (s: Soldier) =>
    isAdmin || (profile?.role === "section_chief" && profile.section_id === s.section_id);

  async function changeStatus(s: Soldier, status: DutyStatus) {
    setStatusFor(null);
    try {
      await setDutyStatus(s.id, status);
      reload();
    } catch (e: any) {
      Alert.alert("Couldn't update", e?.message ?? "Permission denied");
    }
  }

  function confirmDelete(s: Soldier) {
    Alert.alert("Remove soldier", `Remove ${s.rank} ${s.last_name} from the roster?`, [
      { text: "Cancel", style: "cancel" },
      {
        text: "Remove",
        style: "destructive",
        onPress: async () => {
          try {
            await deleteSoldier(s.id);
            reload();
          } catch (e: any) {
            Alert.alert("Couldn't remove", e?.message ?? "Permission denied");
          }
        },
      },
    ]);
  }

  return (
    <View style={{ flex: 1, backgroundColor: colors.bg }}>
      <View style={{ padding: space.md, flexDirection: "row", gap: space.sm }}>
        <TextInput
          placeholder="Search name / rank / section"
          placeholderTextColor={colors.dim}
          value={query}
          onChangeText={setQuery}
          style={{
            flex: 1,
            backgroundColor: colors.panel,
            borderColor: colors.border,
            borderWidth: 1,
            borderRadius: 10,
            color: colors.ink,
            paddingHorizontal: space.md,
            paddingVertical: space.sm,
          }}
        />
        {isAdmin && (
          <Pressable
            onPress={() => setShowAdd(true)}
            style={{ backgroundColor: colors.accent, borderRadius: 10, paddingHorizontal: space.lg, justifyContent: "center" }}
          >
            <Text style={{ color: colors.accentInk, fontWeight: "800" }}>+ Add</Text>
          </Pressable>
        )}
      </View>

      {error && <Text style={{ color: colors.bad, paddingHorizontal: space.md }}>{error}</Text>}

      <FlatList
        data={rows}
        keyExtractor={(item, i) => item.id ?? `h-${i}`}
        refreshControl={<RefreshControl refreshing={loading} onRefresh={reload} tintColor={colors.accent} />}
        contentContainerStyle={{ padding: space.md, paddingBottom: space.xl }}
        renderItem={({ item }) => {
          if (item.header) {
            return (
              <Text style={{ color: colors.accent, fontWeight: "800", marginTop: space.md, marginBottom: space.xs }}>
                {item.header}
              </Text>
            );
          }
          const s = item as Soldier;
          return (
            <Pressable
              onPress={() => canEditStatus(s) && setStatusFor(s)}
              onLongPress={() => isAdmin && confirmDelete(s)}
              style={{
                flexDirection: "row",
                alignItems: "center",
                justifyContent: "space-between",
                backgroundColor: colors.panel,
                borderColor: colors.border,
                borderWidth: 1,
                borderRadius: 10,
                padding: space.md,
                marginBottom: space.sm,
              }}
            >
              <Text style={{ color: colors.ink, fontWeight: "600" }}>
                {s.rank} {s.last_name}
                {s.first_initial ? `, ${s.first_initial}.` : ""}
              </Text>
              <View
                style={{
                  backgroundColor: statusColor[s.duty_status] ?? colors.dim,
                  borderRadius: 20,
                  paddingHorizontal: space.md,
                  paddingVertical: 3,
                }}
              >
                <Text style={{ color: colors.accentInk, fontSize: 12, fontWeight: "800" }}>
                  {statusLabel[s.duty_status]}
                </Text>
              </View>
            </Pressable>
          );
        }}
      />

      {/* Status picker */}
      <Modal visible={!!statusFor} transparent animationType="fade" onRequestClose={() => setStatusFor(null)}>
        <Pressable onPress={() => setStatusFor(null)} style={{ flex: 1, backgroundColor: "#000a", justifyContent: "flex-end" }}>
          <View style={{ backgroundColor: colors.panel, borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: space.lg }}>
            <Text style={{ color: colors.ink, fontWeight: "800", marginBottom: space.md }}>
              {statusFor?.rank} {statusFor?.last_name} — set status
            </Text>
            {STATUSES.map((st) => (
              <Pressable
                key={st}
                onPress={() => statusFor && changeStatus(statusFor, st)}
                style={{ flexDirection: "row", alignItems: "center", paddingVertical: space.md }}
              >
                <View style={{ width: 12, height: 12, borderRadius: 6, backgroundColor: statusColor[st], marginRight: space.md }} />
                <Text style={{ color: colors.ink }}>{statusLabel[st]}</Text>
              </Pressable>
            ))}
          </View>
        </Pressable>
      </Modal>

      {showAdd && (
        <AddSoldier
          unitId={profile!.unit_id}
          sections={sections.map((s) => ({ id: s.id, name: s.name }))}
          onClose={() => setShowAdd(false)}
          onSaved={() => {
            setShowAdd(false);
            reload();
          }}
        />
      )}
    </View>
  );
}

function AddSoldier({
  unitId,
  sections,
  onClose,
  onSaved,
}: {
  unitId: string;
  sections: Array<{ id: string; name: string }>;
  onClose: () => void;
  onSaved: () => void;
}) {
  const [rank, setRank] = useState("");
  const [last, setLast] = useState("");
  const [initial, setInitial] = useState("");
  const [sectionId, setSectionId] = useState(sections[0]?.id ?? "");
  const [busy, setBusy] = useState(false);

  async function save() {
    if (!rank.trim() || !last.trim() || !sectionId) {
      Alert.alert("Missing info", "Rank, last name and section are required.");
      return;
    }
    setBusy(true);
    try {
      await upsertSoldier({
        unit_id: unitId,
        section_id: sectionId,
        rank: rank.trim(),
        last_name: last.trim(),
        first_initial: initial.trim().slice(0, 1).toUpperCase(),
        duty_status: "present",
      });
      onSaved();
    } catch (e: any) {
      Alert.alert("Couldn't save", e?.message ?? "Permission denied");
    } finally {
      setBusy(false);
    }
  }

  const field = {
    backgroundColor: colors.panelAlt,
    borderColor: colors.border,
    borderWidth: 1,
    borderRadius: 10,
    color: colors.ink,
    padding: space.md,
    marginBottom: space.sm,
  } as const;

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <Pressable onPress={onClose} style={{ flex: 1, backgroundColor: "#000a", justifyContent: "flex-end" }}>
        <Pressable style={{ backgroundColor: colors.panel, borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: space.lg }}>
          <Text style={{ color: colors.ink, fontWeight: "800", fontSize: 16, marginBottom: space.md }}>Add soldier</Text>
          <TextInput placeholder="Rank (e.g. PFC)" placeholderTextColor={colors.dim} value={rank} onChangeText={setRank} style={field} />
          <TextInput placeholder="Last name" placeholderTextColor={colors.dim} value={last} onChangeText={setLast} style={field} />
          <TextInput placeholder="First initial" placeholderTextColor={colors.dim} value={initial} onChangeText={setInitial} maxLength={1} style={field} />
          <Text style={{ color: colors.dim, marginBottom: space.xs }}>Section</Text>
          <View style={{ flexDirection: "row", flexWrap: "wrap", gap: space.sm, marginBottom: space.md }}>
            {sections.map((s) => (
              <Pressable
                key={s.id}
                onPress={() => setSectionId(s.id)}
                style={{
                  borderColor: sectionId === s.id ? colors.accent : colors.border,
                  borderWidth: 1,
                  backgroundColor: sectionId === s.id ? colors.accent : colors.panelAlt,
                  borderRadius: 20,
                  paddingHorizontal: space.md,
                  paddingVertical: space.xs,
                }}
              >
                <Text style={{ color: sectionId === s.id ? colors.accentInk : colors.ink, fontWeight: "700", fontSize: 12 }}>{s.name}</Text>
              </Pressable>
            ))}
          </View>
          <Pressable onPress={save} disabled={busy} style={{ backgroundColor: colors.accent, borderRadius: 10, padding: space.lg, alignItems: "center" }}>
            <Text style={{ color: colors.accentInk, fontWeight: "800" }}>{busy ? "Saving…" : "Save soldier"}</Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}
