import { useLanguage } from "../../../i18n/context";
import { ExternalIcon } from "../components/memberIcons";
import type { EntryAdvice, EntrySquad } from "../types";
import styles from "./LeagueMemberPage.module.css";

const FPL_TRANSFERS = "https://fantasy.premierleague.com/transfers";
const FPL_PICK_TEAM = "https://fantasy.premierleague.com/my-team";

/**
 * The way from this week's decision to the game, where the member makes it: the site reads
 * the team and never changes it. Transfers are made on the game's transfers page; a week
 * with no transfer whose plan moves the armband sends the member to the game's team page,
 * where the captain is set. A week that leaves the team as it stands (no transfer, and the
 * captain already wearing the armband) has nothing to apply, so it offers nothing.
 */
export function ApplyOnFpl({
  plan,
  squad,
  canOpen,
}: {
  plan: EntryAdvice;
  squad: EntrySquad;
  canOpen: () => boolean;
}) {
  const copy = useLanguage().messages.leagueMembers;
  const held = squad.starting_xi.find((player) => player.is_captain)?.player_id;
  const transfers = plan.moves.length > 0;
  if (!transfers && (!plan.captain || plan.captain.player_id === held)) return null;
  return (
    <div className={styles.apply} data-zone="apply-fpl">
      <a
        className={styles.applyLink}
        href={transfers ? FPL_TRANSFERS : FPL_PICK_TEAM}
        target="_blank"
        rel="noopener noreferrer"
        onClick={(event) => {
          if (!canOpen()) event.preventDefault();
        }}
      >
        {copy.applyOnFpl}
        <ExternalIcon />
      </a>
    </div>
  );
}
