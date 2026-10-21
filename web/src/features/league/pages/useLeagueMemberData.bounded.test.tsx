import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { EXAMPLE_MEMBER, stubTree, withLeague } from "../../../testSupport/league";
import * as clients from "../advice/adviceClient";
import type { LeagueTree } from "../data";
import { boundedRivalIds } from "./rivalReads";
import { useLeagueMemberData } from "./useLeagueMemberData";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const members = Array.from({ length: 1000 }, (_, rank) => ({
  ...EXAMPLE_MEMBER,
  rank: rank + 1,
  entry_id: 10_000 + rank,
}));
const OWN = 10_500;

it("pins neighbours to standings order and refuses unknown, own and malformed IDs", () => {
  expect(boundedRivalIds(members.toReversed(), OWN, 10_001, "10999")).toEqual([
    10_499, 10_501, 10_001, 10_999,
  ]);
  for (const raw of ["10500", "99999", "1e4", "-1", "", null])
    expect(boundedRivalIds(members, OWN, 10_499, raw)).toEqual([10_499, 10_501]);
  expect(boundedRivalIds(members, 10_000, null, null)).toEqual([10_001]);
  expect(boundedRivalIds(members, 10_999, null, null)).toEqual([10_998]);
});

it("reads at most four rival squads in a 1000-member league and one new typed selection", async () => {
  const base = mockEntrySquadEnvelopes[EXAMPLE_MEMBER.entry_id]!;
  const snapshot = "fpl-live-bounded-rivals";
  const index = mockEntryAdviceIndex(EXAMPLE_MEMBER.entry_id);
  Object.assign(index.payload, {
    entry_id: OWN,
    default_rival_entry_id: 10_001,
    strategies: ["saf-puan"],
    rival_entry_ids: [],
    computed: [],
    unavailable: [],
    windows: { "saf-puan": [1] },
  });
  const load = vi.fn<LeagueTree["entrySquad"]>().mockImplementation(async (id) => ({
    ...base,
    payload: {
      ...base.payload,
      entry: members.find((member) => member.entry_id === id)!,
      source_snapshot_id: snapshot,
      device_plan: { held: [], bank_tenths: 0, free_transfers: 1, sell_tenths: {} },
    },
  }));
  stubTree({
    entrySquad: load,
    members: vi.fn().mockResolvedValue({
      ...mockLeagueMembersEnvelope,
      payload: { ...mockLeagueMembersEnvelope.payload, members },
    }),
    entryAdviceIndex: vi.fn().mockResolvedValue(index),
  });
  vi.spyOn(clients, "createAdviceClient").mockImplementation(
    (loader) => new clients.StaticOnlyAdviceClient(loader),
  );
  const query = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
  const wrapper = ({ children }: { children: ReactNode }) => (
    <QueryClientProvider client={query}>{withLeague(children)}</QueryClientProvider>
  );
  const { result, rerender, unmount } = renderHook(
    ({ search }) => useLeagueMemberData(String(OWN), new URLSearchParams(search)),
    { wrapper, initialProps: { search: "mode=ortak-koru&rival=10999" } },
  );
  await waitFor(() => expect(result.current.deviceRivals.squads).toHaveLength(4));
  await waitFor(() => expect(query.isFetching()).toBe(0));
  expect(load.mock.calls.map(([id]) => id).sort()).toEqual([10_001, 10_499, OWN, 10_501, 10_999]);
  rerender({ search: "mode=ortak-koru&rival=10998" });
  await waitFor(() => expect(result.current.selection.request.rivalEntryId).toBe(10_998));
  await waitFor(() => expect(query.isFetching()).toBe(0));
  expect(load).toHaveBeenCalledTimes(6);
  expect(load).toHaveBeenLastCalledWith(10_998);
  unmount();
  query.clear();
});
