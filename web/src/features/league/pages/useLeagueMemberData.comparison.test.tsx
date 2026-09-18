import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { act, cleanup, render, screen, waitFor } from "@testing-library/react";
import { MemoryRouter, Route, Routes } from "react-router";
import { afterEach, expect, it, vi } from "vitest";
import {
  mockEntryAdviceEnvelope,
  mockEntryAdviceIndex,
  mockEntrySquadEnvelopes,
  mockLeagueMembersEnvelope,
} from "../../../fixtures/league";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES } from "../../../i18n/messages";
import * as clients from "../advice/adviceClient";
import { TOP100_COPY } from "../advice/top100Copy";
import * as data from "../data";
import { LeagueMemberPage } from "./LeagueMemberPage";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
});
const ENTRY = 35249001;
it.each([
  { published: true, valid: true, malformed: false },
  { published: false, valid: true, malformed: false },
  { published: true, valid: false, malformed: false },
  { published: true, valid: true, malformed: true },
])(
  "the computed page reads only a valid published control: %j",
  async ({ published, valid, malformed }) => {
    const squad = mockEntrySquadEnvelopes[ENTRY];
    const index = mockEntryAdviceIndex(ENTRY);
    index.payload.windows = { ...index.payload.windows, "saf-puan": published ? [1, 3, 5] : [1] };
    const rival = valid ? index.payload.default_rival_entry_id! : 99999999;
    const selected = mockEntryAdviceEnvelope(ENTRY, "fark-yarat", 3, rival);
    selected.payload.plan_weeks = mockEntryAdviceEnvelope(ENTRY, "saf-puan", 3).payload.plan_weeks;
    const api = {
      readCapabilities: vi.fn(async () => ({
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
      })),
      readAdvice: vi.fn(async (_request: clients.AdviceRequest) => ({
        kind: "advice",
        envelope: selected,
        source: "api-cache",
      })),
      requestAdvice: vi.fn(),
      readJob: vi.fn(),
    };
    vi.spyOn(clients, "createAdviceClient").mockReturnValue(api as unknown as clients.AdviceClient);
    vi.spyOn(data, "loadEntrySquad").mockResolvedValue(squad);
    vi.spyOn(data, "loadLeagueMembers").mockResolvedValue(mockLeagueMembersEnvelope);
    vi.spyOn(data, "loadEntryAdviceIndex").mockResolvedValue(index);
    const load = vi
      .spyOn(data, "loadEntryAdvice")
      .mockImplementation(async (id, mode, window, other) => {
        const envelope = mockEntryAdviceEnvelope(id, mode, window, other);
        if (malformed && mode === "saf-puan")
          Object.assign(envelope.payload, { plan_weeks: [null, null, null] });
        return envelope;
      });
    const query = new QueryClient({ defaultOptions: { queries: { retry: false, gcTime: 0 } } });
    const { unmount } = render(
      <QueryClientProvider client={query}>
        <LanguageProvider initialLanguage="en">
          <MemoryRouter
            initialEntries={[
              "/league/members/" + ENTRY + "?mode=fark-yarat&window=3&rival=" + rival,
            ]}
          >
            <Routes>
              <Route path="/league/members/:entryId" element={<LeagueMemberPage />} />
            </Routes>
          </MemoryRouter>
        </LanguageProvider>
      </QueryClientProvider>,
    );
    await waitFor(() => expect(api.readCapabilities).toHaveBeenCalledOnce());
    await act(async () => {
      await Promise.resolve();
    });
    if (valid) {
      await screen.findByText(MESSAGES.en.leagueMembers.computeDone, { exact: true });
      expect(api.readAdvice).toHaveBeenCalledTimes(1);
      expect(api.readAdvice.mock.calls[0]?.[0]).toMatchObject({
        strategy: "fark-yarat",
        window: 3,
        rivalEntryId: rival,
      });
    } else expect(api.readAdvice).not.toHaveBeenCalled();
    expect(api.requestAdvice).not.toHaveBeenCalled();
    expect(api.readJob).not.toHaveBeenCalled();
    expect(
      load.mock.calls.filter(([, mode, window]) => mode === "saf-puan" && window === 3),
    ).toHaveLength(published && valid ? 1 : 0);
    const comparison = () =>
      screen.queryByRole("region", { name: TOP100_COPY.en.windowComparisonTitle });
    if (published && valid && !malformed) await waitFor(() => expect(comparison()).toBeVisible());
    else expect(comparison()).toBeNull();
    unmount();
    query.clear();
  },
);
