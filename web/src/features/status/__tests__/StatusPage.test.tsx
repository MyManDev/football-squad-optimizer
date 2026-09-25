/**
 * The remaining-time tile is a claim about now, so it is held against a fixed now.
 *
 * The fixture is the published status document itself, unedited. Read off its own
 * `hours_to_deadline` the tile would announce time measured at the moment of publication;
 * read off `next_deadline_utc` against the browser's clock it says what is true now. The
 * three states below are the whole of what the tile may say, and none of them is a zero or
 * a negative number.
 */

import { QueryClient, QueryClientProvider } from "@tanstack/react-query";
import { cleanup, render, screen } from "@testing-library/react";
import { afterEach, beforeEach, describe, expect, it, vi } from "vitest";

import indexFixture from "../../../../public/data/index.json";
import publishedStatus from "../../../../public/data/2026-27/status.json";
import type { DataClient, Loaded } from "../../../data/client";
import { DataClientContext } from "../../../data/queries";
import type { SiteIndex, StatusView, TickActionView } from "../../../data/schema";
import { LanguageProvider } from "../../../i18n/LanguageProvider";
import { MESSAGES, type Language } from "../../../i18n/messages";
import { AS_A_CHANCE } from "../../../testSupport/honesty";
import { StatusPage } from "../pages/StatusPage";

const PUBLISHED = publishedStatus.payload as unknown as StatusView;

/**
 * Every instant here is derived from the fixture's own deadline, never written as a date.
 *
 * The first version of this file pinned `NOW` to a literal the week it was written, when the
 * published document happened to carry a deadline that had already closed. That made the file
 * a hostage of the data: the next publication moved the deadline into the future and ten tests
 * that assume it has passed failed, on a release, for a reason that had nothing to do with the
 * page. The property under test is a relationship between two instants and not a fact about
 * any particular week, so the instants are now computed from the document that ships.
 */
const PUBLISHED_DEADLINE = new Date(PUBLISHED.next_deadline_utc!);

/** A day after the published deadline: the state the tiles are about. */
const NOW = new Date(PUBLISHED_DEADLINE.getTime() + 24 * 60 * 60 * 1000);

/** Two days and ninety minutes past NOW, so the countdown cannot round to nothing. */
const FUTURE_DEADLINE = new Date(NOW.getTime() + (48 * 60 + 90) * 60 * 1000).toISOString();

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
    // The document exactly as published, held at a now the fixture itself defines: the
    // published figure is positive and the deadline it was measured against has closed.
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

  it.each(["en", "tr"] as const)(
    "keeps the published figure, labelled as the publishing moment, in %s",
    async (language) => {
      // The figure comes from the document rather than from a literal, for the same reason
      // NOW does: this asserts that the published number survives to the page unchanged, and
      // a literal would make that assertion expire the next time the week is published.
      const hours = PUBLISHED.hours_to_deadline!.toLocaleString(
        language === "tr" ? "tr-TR" : "en-GB",
        { maximumFractionDigits: 1 },
      );
      renderStatus(PUBLISHED, language);
      await screen.findByText(LABEL[language]);
      expect(screen.getByText(MESSAGES[language].status.atPublish(hours))).toBeInTheDocument();
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

/**
 * An action is shown through its reason code's translation, so the translation has to say
 * what the planner means by the code. A settle needs the week finished and checked, so a
 * week that is finished but not yet checked is recaptured too. The page must not call that
 * week unfinished, and the English sentence the planner records is only the fallback.
 */
describe("the settle reasons", () => {
  function action(kind: TickActionView["kind"], code: string): TickActionView {
    return {
      gameweek: 1,
      handoff_path: null,
      kind,
      reason: "the planner's own sentence, shown only when the code is unknown",
      reason_code: code,
      reason_params: { gameweek: 1, capture_age_hours: 13 },
      snapshot_id: null,
    };
  }

  it.each([
    {
      language: "en",
      expected:
        "gameweek 1 was decided but is not yet marked finished and checked; the capture is 13 h old",
    },
    {
      language: "tr",
      expected:
        "oyun haftası 1 karara bağlandı ama henüz bitmiş ve kontrol edilmiş olarak işaretli değil; veri çekimi 13 saatlik",
    },
  ] as const)(
    "names both flags when it recaptures, in $language",
    async ({ language, expected }) => {
      renderStatus(
        { ...PUBLISHED, is_idle: false, actions: [action("capture", "recapture_for_outcome")] },
        language,
      );
      expect(await screen.findByText(expected)).toBeInTheDocument();
    },
  );

  it.each([
    {
      language: "en",
      expected:
        "gameweek 1 is finished and checked in the latest capture and its decision has no outcome",
    },
    {
      language: "tr",
      expected:
        "oyun haftası 1 son veri çekiminde bitmiş ve kontrol edilmiş görünüyor, kararının sonucu henüz işlenmedi",
    },
  ] as const)("names both flags when it settles, in $language", async ({ language, expected }) => {
    renderStatus(
      { ...PUBLISHED, is_idle: false, actions: [action("settle", "settle_due")] },
      language,
    );
    expect(await screen.findByText(expected)).toBeInTheDocument();
  });
});
