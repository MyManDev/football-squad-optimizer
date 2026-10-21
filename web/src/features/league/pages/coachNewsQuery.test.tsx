import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, renderHook, waitFor } from "@testing-library/react";
import type { ReactNode } from "react";
import { afterEach, expect, it, vi } from "vitest";
import { mockEntryAdviceIndex, mockLeagueMembersEnvelope } from "../../../fixtures/league";
import { coachNewsFixture, NEWS_ENTRY } from "../../../testSupport/coachNews";
import { stubTree, withLeague } from "../../../testSupport/league";
import { useLeagueMemberData } from "./useLeagueMemberData";

afterEach(() => {
  cleanup();
  vi.restoreAllMocks();
  vi.unstubAllEnvs();
});

it.each(["real", "failed", "fixture"])(
  "reads factual news independently of the disabled plan switch: %s",
  async (kind) => {
    vi.stubEnv("VITE_ADVICE_API_ORIGIN", "");
    const { squad, document } = coachNewsFixture();
    const index = structuredClone(mockEntryAdviceIndex(NEWS_ENTRY));
    const path = `advice/${NEWS_ENTRY}/saf-puan/1/hoca-sozu.json`;
    index.payload.evidence = {
      available: true,
      path,
      applied_count: 1,
      source_kind: kind === "fixture" ? "synthetic_fixture" : "club_news_capture",
      source_label: "test",
      clubs_covered: ["Liverpool"],
      rule_version: "managers_word_rule_v3",
      binding: true,
    };
    const readNews =
      kind === "failed"
        ? vi.fn().mockRejectedValue(new Error("unavailable"))
        : vi.fn().mockResolvedValue(document);
    const readAdvice = vi.fn().mockResolvedValue(document);
    stubTree({
      members: vi.fn().mockResolvedValue(mockLeagueMembersEnvelope),
      entrySquad: vi.fn().mockResolvedValue(squad),
      entryAdviceIndex: vi.fn().mockResolvedValue(index),
      entryAdvice: readAdvice,
      entryAdviceEvidence: readNews,
    });
    const client = new QueryClient();
    const wrapper = ({ children }: { children: ReactNode }) => (
      <QueryClientProvider client={client}>{withLeague(children)}</QueryClientProvider>
    );
    const { result } = renderHook(
      () =>
        useLeagueMemberData(
          String(NEWS_ENTRY),
          new URLSearchParams("mode=saf-puan&window=1&llm=off"),
        ),
      { wrapper },
    );
    await waitFor(() => expect(result.current.advice.data).toBeDefined());
    if (kind === "fixture") {
      expect(result.current.coachNews.fetchStatus).toBe("idle");
      expect(readNews).not.toHaveBeenCalled();
    } else {
      await waitFor(() =>
        expect(
          kind === "failed" ? result.current.coachNews.isError : result.current.coachNews.isSuccess,
        ).toBe(true),
      );
      expect(readNews).toHaveBeenCalledExactlyOnceWith(NEWS_ENTRY, path, {
        signal: expect.any(AbortSignal),
      });
    }
    expect(readAdvice).toHaveBeenCalledOnce();
    expect(result.current.advice.isSuccess).toBe(true);
  },
);
