// Rations Control + MRE inventory. The headline number a 92Y wants: TOTAL MREs on
// hand, then days of supply at the current burn, a low-stock alert, a one-tap chow
// count per section (which deducts MREs from stock), and a resupply suggestion in
// whole cases. All the math comes from lib/calc.ts so it's testable and trusted.

import { useCallback, useEffect, useMemo, useState } from "react";
import {
  Alert,
  Modal,
  Pressable,
  RefreshControl,
  ScrollView,
  Text,
  TextInput,
  View,
} from "react-native";
import { useSession } from "../../lib/session";
import {
  fetchMreInventory,
  fetchRecentRationCounts,
  fetchSections,
  logRationCount,
  saveMreInventory,
} from "../../lib/queries";
import {
  applyMealToInventory,
  burnRate,
  daysOfSupply,
  forecastDaysRemaining,
  isLowStock,
  mealsOnHand,
  suggestedResupplyCases,
} from "../../lib/calc";
import { MealSlot, RationCount, RationInventory, Section } from "../../lib/types";
import { colors, space } from "../../lib/theme";

// Planning assumption: a soldier on a full MRE cycle eats ~3 MREs/day. Adjustable
// here because field cycles vary (often 1 hot + 2 MRE). Kept as a constant rather
// than buried in math so it's easy to find.
const MEALS_PER_DAY_ON_MRE = 3;
const TARGET_DAYS_OF_SUPPLY = 5;
const BURN_WINDOW_DAYS = 7;
const MEALS: MealSlot[] = ["B", "L", "D", "Midnight"];

export default function Rations() {
  const { profile, isAdmin } = useSession();
  const unitId = profile?.unit_id;
  const [inv, setInv] = useState<RationInventory | null>(null);
  const [sections, setSections] = useState<Section[]>([]);
  const [counts, setCounts] = useState<RationCount[]>([]);
  const [loading, setLoading] = useState(true);
  const [showChow, setShowChow] = useState(false);
  const [showAdjust, setShowAdjust] = useState(false);

  const reload = useCallback(async () => {
    if (!unitId) return;
    setLoading(true);
    try {
      const since = new Date();
      since.setDate(since.getDate() - BURN_WINDOW_DAYS);
      const [i, secs, c] = await Promise.all([
        fetchMreInventory(unitId),
        fetchSections(unitId),
        fetchRecentRationCounts(unitId, since.toISOString().slice(0, 10)),
      ]);
      setInv(i);
      setSections(secs);
      setCounts(c);
    } finally {
      setLoading(false);
    }
  }, [unitId]);

  useEffect(() => {
    reload();
  }, [reload]);

  // Present-for-duty drives the planned burn. Cheap proxy: count today's logged
  // headcount, falling back to a sensible default if nothing logged yet.
  const presentTroops = useMemo(() => {
    const today = new Date().toISOString().slice(0, 10);
    const todays = counts.filter((c) => c.meal_date === today);
    return todays.length ? Math.max(...todays.map((c) => c.headcount_fed)) : 0;
  }, [counts]);

  const meals = inv ? mealsOnHand(inv) : 0;
  const observedBurn = burnRate(counts, BURN_WINDOW_DAYS);
  const plannedBurn = presentTroops * MEALS_PER_DAY_ON_MRE;
  const days =
    plannedBurn > 0
      ? daysOfSupply(meals, presentTroops, MEALS_PER_DAY_ON_MRE)
      : forecastDaysRemaining(meals, observedBurn, plannedBurn);
  const low = inv ? isLowStock(inv) : false;
  const resupply = inv
    ? suggestedResupplyCases(meals, observedBurn || plannedBurn, TARGET_DAYS_OF_SUPPLY, inv.meals_per_case)
    : 0;

  async function adjustStock(cases: number, loose: number, reorder: number) {
    if (!inv) return;
    const next = { ...inv, on_hand_cases: cases, loose_meals: loose, reorder_point_meals: reorder };
    setInv(next);
    setShowAdjust(false);
    try {
      await saveMreInventory(next);
    } catch (e: any) {
      Alert.alert("Couldn't save stock", e?.message ?? "Permission denied");
      reload();
    }
  }

  async function recordChow(sectionId: string, meal: MealSlot, fed: number, source: "MRE" | "hot") {
    if (!unitId || !inv) return;
    try {
      await logRationCount({
        unit_id: unitId,
        section_id: sectionId,
        meal_date: new Date().toISOString().slice(0, 10),
        meal,
        headcount_fed: fed,
        source,
        entered_by: profile?.id,
      });
      // Deduct MREs from stock (hot meals don't touch the box count).
      if (source === "MRE") {
        const next = applyMealToInventory(inv, { source, headcount_fed: fed });
        setInv(next);
        await saveMreInventory(next);
      }
      setShowChow(false);
      reload();
    } catch (e: any) {
      Alert.alert("Couldn't log chow", e?.message ?? "Permission denied");
    }
  }

  return (
    <ScrollView
      style={{ flex: 1, backgroundColor: colors.bg }}
      contentContainerStyle={{ padding: space.lg }}
      refreshControl={<RefreshControl refreshing={loading} onRefresh={reload} tintColor={colors.accent} />}
    >
      {/* Headline: total MREs on hand */}
      <View style={{ backgroundColor: colors.panel, borderColor: low ? colors.warn : colors.border, borderWidth: 1, borderRadius: 14, padding: space.xl, alignItems: "center" }}>
        <Text style={{ color: colors.dim, letterSpacing: 1 }}>TOTAL MREs ON HAND</Text>
        <Text style={{ color: colors.ink, fontSize: 46, fontWeight: "900" }}>{meals}</Text>
        <Text style={{ color: colors.dim }}>
          meals · {inv?.on_hand_cases ?? 0} cases + {inv?.loose_meals ?? 0} loose
        </Text>
      </View>

      {/* Days of supply + alert */}
      <View style={{ flexDirection: "row", gap: space.md, marginTop: space.lg }}>
        <Stat label="DAYS OF SUPPLY" value={days === Infinity ? "—" : String(days)} sub={`@ ~${MEALS_PER_DAY_ON_MRE}/day`} tone={days !== Infinity && days <= 2 ? colors.warn : colors.ink} />
        <Stat label="BURN (7-day)" value={observedBurn ? observedBurn.toFixed(0) : "—"} sub="meals/day" />
      </View>

      {low && (
        <View style={{ backgroundColor: "#2a1c0c", borderColor: colors.warn, borderWidth: 1, borderRadius: 12, padding: space.lg, marginTop: space.lg }}>
          <Text style={{ color: colors.warn, fontWeight: "800" }}>⚠ LOW STOCK</Text>
          <Text style={{ color: colors.ink, marginTop: space.xs }}>
            At/under reorder point ({inv?.reorder_point_meals} meals).
            {resupply > 0 ? ` Suggest requesting ~${resupply} cases to cover ${TARGET_DAYS_OF_SUPPLY} days.` : ""}
          </Text>
        </View>
      )}

      {/* Actions */}
      <View style={{ flexDirection: "row", gap: space.md, marginTop: space.lg }}>
        <Pressable onPress={() => setShowChow(true)} style={{ flex: 1, backgroundColor: colors.accent, borderRadius: 12, padding: space.lg, alignItems: "center" }}>
          <Text style={{ color: colors.accentInk, fontWeight: "800" }}>Log chow count</Text>
        </Pressable>
        {isAdmin && (
          <Pressable onPress={() => setShowAdjust(true)} style={{ flex: 1, backgroundColor: colors.panelAlt, borderColor: colors.border, borderWidth: 1, borderRadius: 12, padding: space.lg, alignItems: "center" }}>
            <Text style={{ color: colors.ink, fontWeight: "800" }}>Adjust stock</Text>
          </Pressable>
        )}
      </View>

      <Text style={{ color: colors.dim, fontSize: 12, marginTop: space.lg }}>
        Logging an MRE chow count deducts from stock automatically. Hot meals are
        recorded for the burn history but don't draw down MREs.
      </Text>

      {showChow && (
        <ChowModal sections={sections} onClose={() => setShowChow(false)} onRecord={recordChow} canPickSection={isAdmin} mySection={profile?.section_id ?? null} />
      )}
      {showAdjust && inv && (
        <AdjustModal inv={inv} onClose={() => setShowAdjust(false)} onSave={adjustStock} />
      )}
    </ScrollView>
  );
}

function Stat({ label, value, sub, tone = colors.ink }: { label: string; value: string; sub?: string; tone?: string }) {
  return (
    <View style={{ flex: 1, backgroundColor: colors.panelAlt, borderColor: colors.border, borderWidth: 1, borderRadius: 12, padding: space.lg }}>
      <Text style={{ color: colors.dim, fontSize: 11, letterSpacing: 0.5 }}>{label}</Text>
      <Text style={{ color: tone, fontSize: 30, fontWeight: "900" }}>{value}</Text>
      {sub && <Text style={{ color: colors.dim, fontSize: 11 }}>{sub}</Text>}
    </View>
  );
}

function ChowModal({
  sections,
  onClose,
  onRecord,
  canPickSection,
  mySection,
}: {
  sections: Section[];
  onClose: () => void;
  onRecord: (sectionId: string, meal: MealSlot, fed: number, source: "MRE" | "hot") => void;
  canPickSection: boolean;
  mySection: string | null;
}) {
  const usable = canPickSection ? sections : sections.filter((s) => s.id === mySection);
  const [sectionId, setSectionId] = useState(usable[0]?.id ?? "");
  const [meal, setMeal] = useState<MealSlot>("D");
  const [fed, setFed] = useState("");
  const [source, setSource] = useState<"MRE" | "hot">("MRE");

  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <Pressable onPress={onClose} style={{ flex: 1, backgroundColor: "#000a", justifyContent: "flex-end" }}>
        <Pressable style={{ backgroundColor: colors.panel, borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: space.lg }}>
          <Text style={{ color: colors.ink, fontWeight: "800", fontSize: 16, marginBottom: space.md }}>Log chow count</Text>

          <Chips label="Section" items={usable.map((s) => ({ id: s.id, label: s.name }))} value={sectionId} onPick={setSectionId} />
          <Chips label="Meal" items={MEALS.map((m) => ({ id: m, label: m }))} value={meal} onPick={(v) => setMeal(v as MealSlot)} />
          <Chips label="Source" items={[{ id: "MRE", label: "MRE" }, { id: "hot", label: "Hot/UGR" }]} value={source} onPick={(v) => setSource(v as "MRE" | "hot")} />

          <Text style={{ color: colors.dim, marginTop: space.sm, marginBottom: space.xs }}>Headcount fed</Text>
          <TextInput
            keyboardType="number-pad"
            value={fed}
            onChangeText={setFed}
            placeholder="0"
            placeholderTextColor={colors.dim}
            style={{ backgroundColor: colors.panelAlt, borderColor: colors.border, borderWidth: 1, borderRadius: 10, color: colors.ink, padding: space.md, marginBottom: space.md, fontSize: 20 }}
          />

          <Pressable
            onPress={() => {
              const n = parseInt(fed, 10);
              if (!sectionId || !n || n <= 0) {
                Alert.alert("Check entry", "Pick a section and enter a headcount.");
                return;
              }
              onRecord(sectionId, meal, n, source);
            }}
            style={{ backgroundColor: colors.accent, borderRadius: 10, padding: space.lg, alignItems: "center" }}
          >
            <Text style={{ color: colors.accentInk, fontWeight: "800" }}>Record</Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

function AdjustModal({ inv, onClose, onSave }: { inv: RationInventory; onClose: () => void; onSave: (cases: number, loose: number, reorder: number) => void }) {
  const [cases, setCases] = useState(String(inv.on_hand_cases));
  const [loose, setLoose] = useState(String(inv.loose_meals));
  const [reorder, setReorder] = useState(String(inv.reorder_point_meals));
  const field = { backgroundColor: colors.panelAlt, borderColor: colors.border, borderWidth: 1, borderRadius: 10, color: colors.ink, padding: space.md, marginBottom: space.sm, fontSize: 18 } as const;
  return (
    <Modal visible transparent animationType="slide" onRequestClose={onClose}>
      <Pressable onPress={onClose} style={{ flex: 1, backgroundColor: "#000a", justifyContent: "flex-end" }}>
        <Pressable style={{ backgroundColor: colors.panel, borderTopLeftRadius: 16, borderTopRightRadius: 16, padding: space.lg }}>
          <Text style={{ color: colors.ink, fontWeight: "800", fontSize: 16, marginBottom: space.md }}>Adjust MRE stock</Text>
          <Text style={{ color: colors.dim, marginBottom: space.xs }}>Cases on hand (×{inv.meals_per_case} meals)</Text>
          <TextInput keyboardType="number-pad" value={cases} onChangeText={setCases} style={field} />
          <Text style={{ color: colors.dim, marginBottom: space.xs }}>Loose meals</Text>
          <TextInput keyboardType="number-pad" value={loose} onChangeText={setLoose} style={field} />
          <Text style={{ color: colors.dim, marginBottom: space.xs }}>Reorder point (meals)</Text>
          <TextInput keyboardType="number-pad" value={reorder} onChangeText={setReorder} style={field} />
          <Pressable
            onPress={() => onSave(parseInt(cases, 10) || 0, parseInt(loose, 10) || 0, parseInt(reorder, 10) || 0)}
            style={{ backgroundColor: colors.accent, borderRadius: 10, padding: space.lg, alignItems: "center", marginTop: space.sm }}
          >
            <Text style={{ color: colors.accentInk, fontWeight: "800" }}>Save stock</Text>
          </Pressable>
        </Pressable>
      </Pressable>
    </Modal>
  );
}

function Chips({ label, items, value, onPick }: { label: string; items: Array<{ id: string; label: string }>; value: string; onPick: (id: string) => void }) {
  return (
    <View style={{ marginBottom: space.sm }}>
      <Text style={{ color: colors.dim, marginBottom: space.xs }}>{label}</Text>
      <View style={{ flexDirection: "row", flexWrap: "wrap", gap: space.sm }}>
        {items.map((it) => (
          <Pressable
            key={it.id}
            onPress={() => onPick(it.id)}
            style={{ borderColor: value === it.id ? colors.accent : colors.border, borderWidth: 1, backgroundColor: value === it.id ? colors.accent : colors.panelAlt, borderRadius: 20, paddingHorizontal: space.md, paddingVertical: space.xs }}
          >
            <Text style={{ color: value === it.id ? colors.accentInk : colors.ink, fontWeight: "700", fontSize: 13 }}>{it.label}</Text>
          </Pressable>
        ))}
      </View>
    </View>
  );
}
