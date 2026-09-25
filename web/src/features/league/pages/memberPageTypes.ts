import type { FixturesPayload } from "../../fixtures/types";
import type { ComputeService } from "../advice/AdviceRequestPanel";
import type { AdviceCapabilities } from "../advice/adviceCapabilities";
import type { AdviceClient, AdviceSource } from "../advice/adviceClient";
import type { PublishedAdviceStatus } from "../advice/adviceSelection";
import type {
  EntryAdvice,
  EntryAdviceIndex,
  EntrySquad,
  EntryView,
  LeagueViewEnvelope,
} from "../types";

/** Why no published advice is on hand for the selection: never published, or not loadable. */
export type AdviceIssue =
  | "not-computed"
  | "unavailable"
  | "published-missing"
  | "context-mismatch"
  | Exclude<PublishedAdviceStatus, "ready">;

/** What the advice card shows and where it came from. */
export interface ShownAdvice {
  envelope: LeagueViewEnvelope<EntryAdvice>;
  origin: "computed" | "published" | "published-while-computing" | "baseline-while-computing";
  source?: AdviceSource;
}

export interface LeagueMemberViewProps {
  squad: LeagueViewEnvelope<EntrySquad>;
  advice: LeagueViewEnvelope<EntryAdvice> | null;
  adviceIssue?: AdviceIssue;
  adviceLoading?: boolean;
  membersIssue?: "missing" | "unavailable";
  onRetryAdvice?: () => void;
  onRetryIndex?: () => void;
  members?: EntryView[];
  outcomeFreshness?: { publishedAt: string; scoredGameweek: number | null };
  index?: EntryAdviceIndex | null;
  client?: AdviceClient;
  /** What the compute service answers for this page; absent or null on a static build. */
  capabilities?: AdviceCapabilities | null;
  /** Where the page stands with that service; "static" when none is configured. */
  computeService?: ComputeService;
  /** A service is configured and has not answered yet; never true on a static build. */
  computePending?: boolean;
  windowControl?: LeagueViewEnvelope<EntryAdvice> | null;
  /**
   * The advised gameweek's deadline once it has passed, from the published fixture
   * calendar; null while it is open or the calendar does not say.
   */
  deadlinePassed?: string | null;
  rivalSquad?: LeagueViewEnvelope<EntrySquad> | null;
  /**
   * The published fixture calendar the page already reads for the deadline: the open
   * deadline in the top bar and the clubs' next three gameweeks on the boards come from it.
   * Absent or null, the page says nothing about either.
   */
  fixtures?: FixturesPayload | null;
  /** Whether the calendar is still being read, so its absence is not yet a failure. */
  fixturesPending?: boolean;
  /** The league's published name for the sidebar; absent while the member list is not read. */
  leagueName?: string;
}
