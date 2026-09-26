import { CHIP_COPY } from "../features/league/advice/chipCopy";
import { CHIP_FORECAST_COPY } from "../features/league/advice/chipForecastCopy";
import { COMPUTE_COPY } from "../features/league/advice/computeCopy";
import { EVIDENCE_COPY } from "../features/league/advice/evidenceCopy";
import { TOP100_COPY } from "../features/league/advice/top100Copy";
import { FIXTURES_COPY } from "../features/fixtures/fixturesCopy";
import { MESSAGES, type Language } from "../i18n/messages";

/**
 * Every catalogue of the site's own words, in one place, for the honesty walk
 * (`i18n/messagesNoProbability.test.ts`) to iterate.
 *
 * `messages` is the site-wide catalogue. Each other key names a page-scoped copy module,
 * kept beside the page that reads it so it loads with that page's chunk rather than with
 * every first visit, and each key is that module's file name: the walk checks that every
 * production `*Copy.ts` under `src` is listed here, so a new one cannot be left out.
 *
 * This lives in `testSupport/` because only tests read it, and because `i18n/` is a lower
 * zone that imports nothing from `features/`.
 */
export const CATALOGUES = {
  messages: MESSAGES,
  evidenceCopy: EVIDENCE_COPY,
  top100Copy: TOP100_COPY,
  chipCopy: CHIP_COPY,
  chipForecastCopy: CHIP_FORECAST_COPY,
  computeCopy: COMPUTE_COPY,
  fixturesCopy: FIXTURES_COPY,
} as const satisfies Record<string, Record<Language, object>>;
