/**
 * The phone bar's LIVE pill (the owner's yes of 2026-11-11): the address of the LIVE page it
 * opens, only while one of the member's matches is in its window (`liveWindow`), else null.
 * The member is the claimed one on a league page and the team itself on `/entry/<id>`.
 *
 * Nothing is read outside a match window: the calendar alone says whether any match of the
 * live week is on. Only then are the member's clubs read, from the documents the forwarded
 * gate reads under the same keys (the directory, its newest capture table and the member's
 * bundle for that table's week), so a page that holds them reads none of them again. Where
 * they cannot be read, every match of the live week counts, as the live window's own rule
 * for an unknown club has it. The app shell computes this and hands the shell the address:
 * the shell itself reads no league data.
 */

import { useQuery } from "@tanstack/react-query";
import { useMemo } from "react";

import { FIXTURES_QUERY } from "../../fixtures/data";
import type { FixturesPayload } from "../../fixtures/types";
import type { DevicePlanDocument } from "../device/types";
import type { BundleReason, ForwarderResult } from "../forwarder/client";
import type { FplEntryBundle } from "../forwarder/documents";
import {
  newestDeviceTable,
  useCaptureTable,
  useDirectory,
  useEntryBundle,
} from "../forwarded/reads";
import { LEAGUE_READ } from "../queries";
import { useLiveWindow } from "./useLiveWindow";

export interface LivePillTarget {
  entryId: number;
  /** The LIVE page the pill opens. */
  to: string;
}

/** The clubs of the member's live-week picks, or null where a document does not say them. */
export function memberClubs(
  bundle: ForwarderResult<FplEntryBundle, BundleReason> | undefined,
  table: DevicePlanDocument | undefined,
  calendar: FixturesPayload | null,
): ReadonlySet<number> | null {
  if (!bundle?.ok || bundle.document.current_week === null || !table || calendar === null) {
    return null;
  }
  const teams = new Map(table.players.map((player) => [player.element_id, player.team]));
  const ids = new Map<string, number>();
  for (const week of calendar.gameweeks) {
    for (const fixture of week.fixtures) {
      ids.set(fixture.home.name, fixture.home.team_id);
      ids.set(fixture.away.name, fixture.away.team_id);
    }
  }
  const clubs = new Set<number>();
  for (const elementId of bundle.document.current_week.pick_order) {
    const team = teams.get(elementId);
    const club = team === undefined ? undefined : ids.get(team);
    if (club === undefined) return null;
    clubs.add(club);
  }
  return clubs;
}

/** `enabled` is false where the pill cannot be drawn (no phone bar): nothing is read then. */
export function useLivePill(target: LivePillTarget | null, enabled: boolean): string | null {
  const active = enabled && target !== null;
  const fixtures = useQuery({ ...FIXTURES_QUERY, ...LEAGUE_READ, enabled: active });
  const calendar = active ? (fixtures.data ?? null) : null;
  const any = useLiveWindow(calendar);
  const open = active && any.open;
  const directory = useDirectory(open);
  const tableRef = open && directory.data ? newestDeviceTable(directory.data) : null;
  const table = useCaptureTable(tableRef);
  const gameweek = open ? (table.data?.payload.gameweek ?? null) : null;
  const bundle = useEntryBundle(target?.entryId ?? 0, gameweek);
  const clubs = useMemo(
    () => (open ? memberClubs(bundle.data, table.data?.payload, calendar) : null),
    [open, bundle.data, table.data, calendar],
  );
  const mine = useLiveWindow(calendar, { clubs });
  if (!open || target === null) return null;
  if (clubs !== null) return mine.open ? target.to : null;
  // While the member's clubs are being read the pill waits; where they cannot be read, every
  // match of the live week counts.
  const reading =
    directory.isPending ||
    (tableRef !== null && table.isPending) ||
    (gameweek !== null && bundle.isPending);
  return reading ? null : target.to;
}
