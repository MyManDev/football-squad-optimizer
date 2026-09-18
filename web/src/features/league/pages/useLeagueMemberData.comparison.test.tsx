import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import * as clients from "../advice/adviceClient";
import * as data from "../data";
import { useLeagueMemberData } from "./useLeagueMemberData";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const ENTRY = 35249001;
it.each([true, false])(
  "reads only an index-authorized static control, published=%s",
  async (published) => {
    const squad = mockEntrySquadEnvelopes[ENTRY];
    const index = mockEntryAdviceIndex(ENTRY);
    index.payload.windows = { ...index.payload.windows, "saf-puan": published ? [1, 3, 5] : [1] };
    const caps = {
      leagueId: squad.payload.league_id,
      season: squad.payload.season,
      gameweek: squad.payload.gameweek,
      captureSnapshotId: squad.payload.source_snapshot_id!,
      strategies: {
        "saf-puan": { windows: [1, 3, 5], requiresRival: false },
        "fark-yarat": { windows: [1, 3, 5], requiresRival: true },
      },
      top100Weights: [0, 20],
      managersWord: false,
    };
    const api = {
      readCapabilities: vi.fn(async () => caps),
      readAdvice: vi.fn(),
      requestAdvice: vi.fn(),
      pollAdviceJob: vi.fn(),
    };
    vi.spyOn(clients, "createAdviceClient").mockReturnValue(api as unknown as clients.AdviceClient);
    vi.spyOn(data, "loadEntrySquad").mockResolvedValue(squad);
    vi.spyOn(data, "loadLeagueMembers").mockResolvedValue(mockLeagueMembersEnvelope);
    vi.spyOn(data, "loadEntryAdviceIndex").mockResolvedValue(index);
    const load = vi
      .spyOn(data, "loadEntryAdvice")
      .mockImplementation(async (id, mode, window, rival) =>
        mockEntryAdviceEnvelope(id, mode, window, rival),
      );
    const query = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const { result, unmount } = renderHook(
      () =>
        useLeagueMemberData(
          String(ENTRY),
          new URLSearchParams(
            `mode=fark-yarat&window=3&rival=${index.payload.default_rival_entry_id}`,
          ),
        ),
      {
        wrapper: ({ children }: { children: ReactNode }) => (
          <QueryClientProvider client={query}>{children}</QueryClientProvider>
        ),
      },
    );
    await waitFor(() => expect(result.current.computeService).toBe("ready"));
    await act(async () => {
      await Promise.resolve();
    });
    if (published) {
      await waitFor(() => expect(result.current.windowControl.isSuccess).toBe(true));
      expect(
        load.mock.calls.filter(([, mode, window]) => mode === "saf-puan" && window === 3),
      ).toHaveLength(1);
    } else {
      expect(
        load.mock.calls.filter(([, mode, window]) => mode === "saf-puan" && window === 3),
      ).toHaveLength(0);
    }
    expect(api.readAdvice).not.toHaveBeenCalled();
    expect(api.requestAdvice).not.toHaveBeenCalled();
    unmount();
    query.clear();
  },
);
