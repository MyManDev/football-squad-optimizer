import type { Messages } from "../../../i18n/messages";
import { money } from "../../../lib/format";
import { netWeekPoints } from "../standing";
import type { EntrySquad, EntryView } from "../types";

export interface ScoreCell {
  key: string;
  label: string;
  value: string;
}

/**
 * The score bug's cells for one member: the rank among the league's members, the season
 * total, last week net of the hits taken (as the member list nets it), and, when the
 * member's squad document is at hand, the bank and the free transfers. A cell whose number
 * is absent is left out, never shown as 0.
 */
export function scoreBugCells(
  entry: EntryView,
  humans: number,
  squad: Pick<EntrySquad, "bank_tenths" | "free_transfers" | "free_transfers_known"> | null,
  locale: string,
  copy: Pick<
    Messages["leagueMembers"],
    "rankLabel" | "pointsLabel" | "lastWeekLabel" | "bankLabel" | "freeTransfersLabel"
  >,
): ScoreCell[] {
  const count = (value: number) => new Intl.NumberFormat(locale).format(value);
  const net = netWeekPoints(entry);
  return [
    Number.isSafeInteger(entry.rank) && entry.rank > 0
      ? {
          key: "rank",
          label: copy.rankLabel,
          value: humans >= entry.rank ? `${entry.rank}/${humans}` : String(entry.rank),
        }
      : null,
    typeof entry.total_points === "number" && Number.isFinite(entry.total_points)
      ? { key: "points", label: copy.pointsLabel, value: count(entry.total_points) }
      : null,
    net !== null && Number.isFinite(net)
      ? { key: "week", label: copy.lastWeekLabel, value: count(net) }
      : null,
    squad !== null && Number.isFinite(squad.bank_tenths)
      ? { key: "bank", label: copy.bankLabel, value: money(squad.bank_tenths, locale) }
      : null,
    squad !== null &&
    squad.free_transfers_known === true &&
    Number.isSafeInteger(squad.free_transfers) &&
    squad.free_transfers >= 0
      ? { key: "free", label: copy.freeTransfersLabel, value: count(squad.free_transfers) }
      : null,
  ].filter((cell) => cell !== null);
}
