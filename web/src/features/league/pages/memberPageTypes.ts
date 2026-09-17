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
  index?: EntryAdviceIndex | null;
  client?: AdviceClient;
  /** What the compute service answers for this page; absent or null on a static build. */
  capabilities?: AdviceCapabilities | null;
  /** Where the page stands with that service; "static" when none is configured. */
  computeService?: ComputeService;
  rivalSquad?: LeagueViewEnvelope<EntrySquad> | null;
}
