/**
 * The remaining-time tile is a claim about now, so it is held against a fixed now.
 *
 * The fixture is the published status document itself, unedited, whose `hours_to_deadline`
 * was 1.67 at a deadline that has since closed. Read off that field the tile would announce
 * time that ran out long ago; read off `next_deadline_utc` against the browser's clock it
 * says the deadline has passed. The three states below are the whole of what the tile may
 * say, and none of them is a zero or a negative number.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import indexFixture from "../../../../public/data/index.json";
import publishedStatus from "../../../../public/data/2026-27/status.json";
import type { DataClient, Loaded } from "../../../data/client";
import { DataClientContext } from "../../../data/queries";
import type { SiteIndex, StatusView } from "../../../data/schema";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import type { Language } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import { StatusPage } from "../pages/StatusPage";

/** A day after the published document was written, which is the defect as it was found. */
const NOW = new Date("2026-09-13T09:00:00Z");

const PUBLISHED = publishedStatus.payload as unknown as StatusView;

/** Two days and ninety minutes past NOW, so the countdown cannot round to nothing. */
const FUTURE_DEADLINE = "2026-09-15T10:30:00Z";

function loaded<T>(payload: T): Loaded<T> {
  return { payload, generatedAtUtc: publishedStatus.generated_at_utc };
}

function makeClient(view: StatusView): DataClient {
  return {
    getIndex: async () => loaded(indexFixture.payload as SiteIndex),
    getStatus: async () => loaded(view),
    getRecommendation: async () => {
      throw new Error("not used");
    },
    getPool: async () => {
      throw new Error("not used");
    },
    getLedger: async () => {
      throw new Error("not used");
    },
    getLeague: async () => {
      throw new Error("not used");
    },
  };
}

function renderStatus(view: StatusView, language: Language) {
  const queryClient = new QueryClient({ defaultOptions: { queries: { retry: false } } });
  return render(
    <QueryClientProvider client={queryClient}>
      <DataClientContext.Provider value={makeClient(view)}>
        <LanguageProvider initialLanguage={language}>
          <StatusPage />
        </LanguageProvider>
      </DataClientContext.Provider>
    </QueryClientProvider>,
  );
}

/** Stat renders label, value and note in that order; the value is the tile's claim. */
async function tileValue(label: string): Promise<string> {
  const element = await screen.findByText(label);
  const stat = element.parentElement;
  expect(stat).not.toBeNull();
  return stat!.children[1]?.textContent ?? "";
}

const LABEL: Record<Language, string> = {
  en: "time to deadline",
  tr: "son tarihe kalan süre",
};

beforeEach(() => {
  // Only Date is faked: react-query and Testing Library keep their real timers, and the
  // page's own one-minute interval never fires inside a test.
  vi.useFakeTimers({ toFake: ["Date"] });
  vi.setSystemTime(NOW);
});

afterEach(() => {
  vi.useRealTimers();
  cleanup();
});

describe("the remaining-time tile", () => {
  it.each([
    { language: "en", expected: "2d 01:30" },
    { language: "tr", expected: "2g 01:30" },
  ] as const)(
    "counts down to a deadline still open, in $language",
    async ({ language, expected }) => {
      renderStatus({ ...PUBLISHED, next_deadline_utc: FUTURE_DEADLINE }, language);
      expect(await tileValue(LABEL[language])).toBe(expected);
    },
  );

  it.each([
    { language: "en", expected: "deadline passed" },
    { language: "tr", expected: "son tarih geçti" },
  ] as const)("says the deadline has passed, in $language", async ({ language, expected }) => {
    // The document exactly as published: 1.67 hours to a deadline that closed yesterday.
    expect(PUBLISHED.hours_to_deadline).toBeGreaterThan(0);
    expect(new Date(PUBLISHED.next_deadline_utc!).getTime()).toBeLessThan(NOW.getTime());
    renderStatus(PUBLISHED, language);
    expect(await tileValue(LABEL[language])).toBe(expected);
  });

  it.each([
    { language: "en", expected: "not known" },
    { language: "tr", expected: "bilinmiyor" },
  ] as const)(
    "says unknown when no deadline is carried, in $language",
    async ({ language, expected }) => {
      renderStatus({ ...PUBLISHED, next_deadline_utc: null }, language);
      expect(await tileValue(LABEL[language])).toBe(expected);
    },
  );

  it.each([
    { language: "en", deadline: FUTURE_DEADLINE },
    { language: "en", deadline: PUBLISHED.next_deadline_utc },
    { language: "en", deadline: null },
    { language: "tr", deadline: FUTURE_DEADLINE },
    { language: "tr", deadline: PUBLISHED.next_deadline_utc },
    { language: "tr", deadline: null },
  ] as const)(
    "never reads as zero or as a negative number, $language deadline $deadline",
    async ({ language, deadline }) => {
      renderStatus({ ...PUBLISHED, next_deadline_utc: deadline }, language);
      const value = await tileValue(LABEL[language]);
      expect(value).not.toBe("");
      expect(value).not.toMatch(/^[-−]/);
      expect(value).not.toMatch(/^0+([.,]0+)?$/);
    },
  );

  it.each([
    { language: "en", note: "1.7 h remained when this was published" },
    { language: "tr", note: "yayımlandığında 1,7 sa kalmıştı" },
  ] as const)(
    "keeps the published figure, labelled as the publishing moment, in $language",
    async ({ language, note }) => {
      renderStatus(PUBLISHED, language);
      await screen.findByText(LABEL[language]);
      expect(screen.getByText(note)).toBeInTheDocument();
    },
  );

  it.each(["en", "tr"] as const)(
    "publishes no probability on the status page in %s",
    async (language) => {
      const { container } = renderStatus(PUBLISHED, language);
      await screen.findByText(LABEL[language]);
      expect(container.textContent ?? "").not.toMatch(AS_A_CHANCE);
    },
  );
});

/**
 * The gameweek tile names a number the document carries. That number is true about the
 * publication for as long as the document exists, and true about what comes next only until
 * its deadline closes. The tile therefore stops saying "next" at the same moment the
 * countdown beside it starts saying the deadline has passed, so the two tiles cannot
 * disagree. It never names the gameweek that is open now: the document does not carry one.
 */
describe("the gameweek tile", () => {
  const OPEN_LABEL: Record<Language, string> = {
    en: "next gameweek",
    tr: "sıradaki oyun haftası",
  };
  const CLOSED_LABEL: Record<Language, string> = {
    en: "gameweek in this publication",
    tr: "bu yayının oyun haftası",
  };

  it.each(["en", "tr"] as const)(
    "calls the week next while its deadline is still open, in %s",
    async (language) => {
      renderStatus({ ...PUBLISHED, next_deadline_utc: FUTURE_DEADLINE }, language);
      expect(await tileValue(OPEN_LABEL[language])).toBe(String(PUBLISHED.next_gameweek));
      expect(screen.queryByText(CLOSED_LABEL[language])).toBeNull();
    },
  );

  it.each(["en", "tr"] as const)(
    "stops calling the week next once its deadline has passed, in %s",
    async (language) => {
      // The document exactly as published: it names gameweek 4 at a deadline that closed.
      expect(new Date(PUBLISHED.next_deadline_utc!).getTime()).toBeLessThan(NOW.getTime());
      renderStatus(PUBLISHED, language);
      expect(await tileValue(CLOSED_LABEL[language])).toBe(String(PUBLISHED.next_gameweek));
      expect(screen.queryByText(OPEN_LABEL[language])).toBeNull();
    },
  );

  it.each([
    { language: "en", note: "already passed" },
    { language: "tr", note: ", geçti" },
  ] as const)(
    "says the deadline has passed in the note, in $language",
    async ({ language, note }) => {
      renderStatus(PUBLISHED, language);
      await screen.findByText(CLOSED_LABEL[language]);
      expect(screen.getByText((content) => content.includes(note))).toBeInTheDocument();
    },
  );

  it.each(["en", "tr"] as const)(
    "keeps the published number itself unchanged either way, in %s",
    async (language) => {
      renderStatus({ ...PUBLISHED, next_deadline_utc: FUTURE_DEADLINE }, language);
      const open = await tileValue(OPEN_LABEL[language]);
      cleanup();
      renderStatus(PUBLISHED, language);
      const closed = await tileValue(CLOSED_LABEL[language]);
      expect(open).toBe(closed);
    },
  );
});
