import type { FixturesPayload } from "../../fixtures/types";
import type { ComputeService } from "../advice/AdviceRequestPanel";
import type { AdviceCapabilities } from "../advice/adviceCapabilities";
import type { AdviceClient, AdviceSource } from "../advice/adviceClient";
import type { PublishedAdviceStatus } from "../advice/adviceSelection";
import type { DeviceRivalReads } from "../device/computable";
import type { DevicePlanDependencies } from "../device/useDevicePlan";
import type { WhatIfDependencies } from "../device/useWhatIf";
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
  /** Published coach statements, independent of the selected plan or its news switch. */
  coachNews?: LeagueViewEnvelope<EntryAdvice> | null;
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
  /** The device solve's document loader and worker; the page's own unless a test injects them. */
  deviceDependencies?: DevicePlanDependencies;
  /** The what-if mode's table loader and worker; the page's own unless a test injects them. */
  whatIfDependencies?: WhatIfDependencies;
  /**
   * What the page has read of the other members' entry documents. The device offers a
   * rival strategy only against a rival among them it can use; none given, it offers no rival.
   */
  deviceRivals?: DeviceRivalReads;
  windowControl?: LeagueViewEnvelope<EntryAdvice> | null;
  /**
   * The advised gameweek's deadline once it has passed, from the published fixture
   * calendar; null while it is open or the calendar does not say.
   */
  deadlinePassed?: string | null;
  /**
   * The page's minute clock (epoch ms), the one `deadlinePassed` was read at: the top bar
   * counts down to an open deadline from it. Absent, the bar states the deadline alone.
   */
  now?: number;
  rivalSquad?: LeagueViewEnvelope<EntrySquad> | null;
  /** The entry document of the rival `?duel=` names (#1133); null while none is named or read. */
  duelSquad?: LeagueViewEnvelope<EntrySquad> | null;
  /**
   * Why a named duel rival has no document yet: still being read, not in the week's
   * publication, or a read that failed.
   */
  duelIssue?: "loading" | "missing" | "unreadable";
  /**
   * The published fixture calendar the page already reads for the deadline: the open
   * deadline in the top bar and the clubs' next three gameweeks on the boards come from it.
   * Absent or null, the page says nothing about either.
   */
  fixtures?: FixturesPayload | null;
  /** Whether the calendar is still being read, so its absence is not yet a failure. */
  fixturesPending?: boolean;
}
