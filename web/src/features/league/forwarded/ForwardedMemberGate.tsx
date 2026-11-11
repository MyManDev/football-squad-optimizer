import { useMemo, type ReactNode } from "react";
import { Link, useLocation, useParams } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { useLanguage } from "../../../i18n/context";
import { leagueAddress } from "../../../lib/leagueAddresses";
import { useFixtures } from "../../fixtures/data";
import { tableRows, type FplStandingRow } from "../forwarder/documents";
import { MemberGate } from "../pages/MemberGate";
import { MemberPageSkeleton } from "../pages/MemberPageSkeleton";
import { useForwardedLeague } from "./ForwardedLeagueContext";
import { ForwardedTreeProvider } from "./ForwardedTreeProvider";
import { forwardedMemberSquad } from "./memberSquad";
import {
  newestDeviceTable,
  refusalOf,
  standingsPage,
  useCaptureTable,
  useDirectory,
  useEntryBundle,
  useForwardedStandings,
} from "./reads";
import type { ForwardedSources } from "./forwardedTree";
import styles from "./ForwardedMemberGate.module.css";

/** The team's name and manager over a page that cannot open, and the way back to its league. */
function MemberHeading({ title, manager = null }: { title: string; manager?: string | null }) {
  const { messages } = useLanguage();
  const league = useForwardedLeague();
  const location = useLocation();
  const page = standingsPage(location.state?.leaguePage);
  return (
    <header className={styles.heading}>
      <h1 className={styles.title}>{title}</h1>
      {manager ? <p className={styles.manager}>{manager}</p> : null}
      {league !== null ? (
        <p className={styles.back}>
          {league.leagueName ?? messages.forwarded.leagueTitle(league.leagueId)}
          {" · "}
          <Link to={`${leagueAddress(league.leagueId)}${page > 1 ? `?page=${page}` : ""}`}>
            {messages.forwarded.backToLeague}
          </Link>
        </p>
      ) : null}
    </header>
  );
}

/**
 * The gate in front of one FPL team's page read through the forwarder (#983 step 4): at
 * `/entry/<id>` on its own (`standalone`), or under a forwarded league as a member chosen
 * from its table. The capture's own table is the newest the directory names; the team's
 * bundle is asked for that table's gameweek, and the identity rule binds the two
 * (`forwardedMemberSquad`). Bound, the member page the address names is drawn under the
 * forwarded league's tree, behind the same member step a published league has (none for a
 * team on its own). Not bound, the gate says the plan cannot be computed for this team this
 * week, and shows nothing else.
 */
export function ForwardedMemberGate({
  children,
  standalone = false,
  sources,
}: {
  children: ReactNode;
  /** The team opened on its own: league 0, no member step. */
  standalone?: boolean;
  /** The forwarder reads the tree makes; the site's own unless a test injects them. */
  sources?: ForwardedSources;
}) {
  const { messages } = useLanguage();
  const words = messages.forwarded;
  const { entryId: entryParam } = useParams();
  const location = useLocation();
  const league = useForwardedLeague();
  const entryId = /^\d+$/.test(entryParam ?? "") ? Number(entryParam) : 0;
  const valid = Number.isSafeInteger(entryId) && entryId > 0;
  const directory = useDirectory(valid);
  const tableRef = directory.data ? newestDeviceTable(directory.data) : null;
  const table = useCaptureTable(tableRef);
  const gameweek = table.data?.payload.gameweek ?? null;
  const bundle = useEntryBundle(entryId, valid ? gameweek : null);
  const fixtures = useFixtures();
  const standings = useForwardedStandings(
    league?.leagueId ?? null,
    standingsPage(location.state?.leaguePage),
    league?.scoring ?? "classic",
  );
  const leagueTable = standings.data;
  const standing = useMemo<FplStandingRow | null>(() => {
    const row = leagueTable ? tableRows(leagueTable).find((r) => r.entry === entryId) : undefined;
    return row === undefined ? null : { ...row, event_total: row.event_total ?? 0 };
  }, [leagueTable, entryId]);
  const read = bundle.data;
  const tableEnvelope = table.data ?? null;
  const calendar = fixtures.data ?? null;
  // The binding is checked here, before the page, so an unbound team is told why in the
  // forwarded words rather than as a member whose squad is not published.
  const built = useMemo(
    () =>
      read !== undefined && tableEnvelope !== null
        ? forwardedMemberSquad({
            bundle: read.document,
            table: tableEnvelope,
            entryId,
            fixtures: calendar,
            leagueId: league?.leagueId ?? 0,
            standing,
          })
        : null,
    [read, tableEnvelope, entryId, calendar, league?.leagueId, standing],
  );
  // What the tree need not read again: the standings page this member was chosen from and
  // the member's own bundle.
  const knownPages = useMemo(() => (standings.data ? [standings.data] : []), [standings.data]);
  const knownBundles = useMemo(() => (read !== undefined ? [read.document] : []), [read]);

  if (!valid) return <EmptyState title={messages.leagueMembers.invalidEntry} />;
  if (
    directory.isPending ||
    (tableRef !== null && table.isPending) ||
    (gameweek !== null && bundle.isPending) ||
    fixtures.isPending ||
    (league !== null && standings.isPending)
  ) {
    return <MemberPageSkeleton />;
  }
  const fallbackTitle = standing?.entry_name || words.teamTitle(entryId);
  if (tableRef === null || tableEnvelope === null || gameweek === null) {
    return (
      <div className={styles.page}>
        <MemberHeading title={fallbackTitle} manager={standing?.player_name} />
        <p className={styles.state} role="status">
          {words.planNotComputable}
        </p>
      </div>
    );
  }
  // A bundle held stays drawn when a later read of it fails; only none held says why.
  if (read === undefined) {
    const reason = refusalOf(bundle.error);
    const missing = reason === "entry_not_found" || reason === "not_found";
    return (
      <div className={styles.page}>
        <MemberHeading title={fallbackTitle} manager={standing?.player_name} />
        <p className={styles.state} role="status">
          {missing ? words.teamNotFound(entryId) : words.teamUnavailable}
        </p>
        {missing ? null : (
          <button type="button" className={styles.retry} onClick={() => void bundle.refetch()}>
            {words.retry}
          </button>
        )}
      </div>
    );
  }
  if (built === null || !built.ok) {
    return (
      <div className={styles.page}>
        <MemberHeading
          title={standing?.entry_name || read.document.entry.name}
          manager={standing?.player_name}
        />
        <p className={styles.state} role="status" data-plan-not-computable>
          {words.planNotComputable}
        </p>
      </div>
    );
  }
  return (
    <ForwardedTreeProvider
      leagueId={standalone ? 0 : (league?.leagueId ?? 0)}
      leagueName={league?.leagueName ?? ""}
      tableRef={tableRef}
      table={tableEnvelope}
      fixtures={calendar}
      pages={knownPages}
      bundles={knownBundles}
      sources={sources}
    >
      {standalone || league === null ? children : <MemberGate>{children}</MemberGate>}
    </ForwardedTreeProvider>
  );
}
