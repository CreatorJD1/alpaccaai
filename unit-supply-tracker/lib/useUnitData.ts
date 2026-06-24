// Shared loader for the unit's sections + roster, with a live Supabase Realtime
// subscription so the Headcount Board updates the moment any section changes a
// soldier's duty status — no manual refresh, which is the whole point of doing
// this on phones instead of a clipboard.

import { useCallback, useEffect, useState } from "react";
import { supabase } from "./supabase";
import { fetchRoster, fetchSections } from "./queries";
import { Section, Soldier } from "./types";

export function useUnitData(unitId: string | undefined) {
  const [sections, setSections] = useState<Section[]>([]);
  const [roster, setRoster] = useState<Soldier[]>([]);
  const [loading, setLoading] = useState(true);
  const [error, setError] = useState<string | null>(null);

  const reload = useCallback(async () => {
    if (!unitId) return;
    try {
      setError(null);
      const [secs, sols] = await Promise.all([
        fetchSections(unitId),
        fetchRoster(unitId),
      ]);
      setSections(secs);
      setRoster(sols);
    } catch (e: any) {
      setError(e?.message ?? "Failed to load unit data");
    } finally {
      setLoading(false);
    }
  }, [unitId]);

  useEffect(() => {
    reload();
    if (!unitId) return;
    // Live updates: any insert/update/delete on this unit's soldiers re-pulls the
    // roster so the board and rollups reflect reality across all phones.
    const channel = supabase
      .channel(`roster-${unitId}`)
      .on(
        "postgres_changes",
        { event: "*", schema: "public", table: "soldiers", filter: `unit_id=eq.${unitId}` },
        () => reload(),
      )
      .subscribe();
    return () => {
      supabase.removeChannel(channel);
    };
  }, [unitId, reload]);

  return { sections, roster, loading, error, reload };
}
