/** The approved week policy: publication, match time, finished rows and checked rows. */

/** Structural input only: the shared policy has no dependency on a feature layer. */
export interface WeekCalendar {
  captured_at_utc: string;
  gameweeks: readonly {
    gameweek: number;
    deadline_utc: string;
    fixtures: readonly { kickoff_utc: string | null; finished: boolean }[];
  }[];
}

export const WEEK_MATCH_LIMIT_MS = 180 * 60_000;

export type WeekPhase =
  | "before-deadline"
  | "before-kickoff"
  | "playing"
  | "played"
  | "finished"
  | "checked"
  | "unavailable";

export interface WeekEvent {
  gameweek: number;
  finished: boolean;
  data_checked: boolean;
  deadline_utc?: string | null;
}

export interface WeekTargets {
  topBar: number | null;
  plan: number | null;
  resources: number | null;
  fixtures: number | null;
  memberRail: number | null;
  memberScore: number | null;
  live: number | null;
  liveWaiting: number | null;
  pill: number | null;
  scoreboard: number | null;
  lastResult: number | null;
  leagueTotal: number | null;
  race: number | null;
  history: number | null;
}

export type WeekConsumer = keyof WeekTargets;

export interface WeekStateInput {
  treeGameweek: number | null;
  events: readonly WeekEvent[];
  fixtures: WeekCalendar | null;
  now: number;
  /** Previously shown weeks, for consumers whose new target has no data row yet. */
  current?: Partial<WeekTargets>;
  /** Omit a consumer only when its row availability is not being checked here. */
  available?: Partial<Record<WeekConsumer, readonly number[]>>;
}

export interface WeekState {
  phase: WeekPhase;
  clock: number;
  gameweek: number | null;
  nextGameweek: number | null;
  elapsedGameweek: number | null;
  planDeadline: string | null;
  planClosed: boolean | null;
  finishedWeeks: number[];
  checkedWeeks: number[];
  /** Policy targets before the same-week data-row gate. */
  targets: WeekTargets;
  /** Targets with each consumer's current week retained when its data row is absent. */
  weeks: WeekTargets;
  nextKickoff: number | null;
  /** The next clock boundary; new documents can also change phase or targets. */
  changesIn: number | null;
}

const instant = (value: string | null | undefined): number | null => {
  const time = value == null ? NaN : Date.parse(value);
  return Number.isFinite(time) ? time : null;
};

/** A device clock behind the capture cannot bring an earlier week back. */
export function calendarClock(payload: Pick<WeekCalendar, "captured_at_utc">, now: number): number {
  return Math.max(now, instant(payload.captured_at_utc) ?? now);
}

/** The same-week data-row gate, shared by every consumer. */
export function availableWeek(
  target: number | null,
  current: number | null,
  rows: readonly number[],
): number | null {
  return target === null ? null : rows.includes(target) ? target : current;
}

/** Capture readers keep their exact microsecond boundary when selecting an open plan. */
export function openPlanWeek(
  deadlines: readonly { gameweek: number; deadline: bigint }[],
  now: bigint,
): number | null {
  return (
    [...deadlines].sort((a, b) => a.gameweek - b.gameweek).find((row) => row.deadline > now)
      ?.gameweek ?? null
  );
}

/** Finished and checked are separate result policies, including for document-only views. */
export function resultWeeks(
  events: readonly WeekEvent[],
  kind: "finished" | "checked",
  now = Number.POSITIVE_INFINITY,
): number[] {
  return [
    ...new Set(
      events
        .filter((event) => {
          const deadline = instant(event.deadline_utc);
          return (
            event.finished &&
            (kind === "finished" || event.data_checked) &&
            (deadline === null || deadline <= now)
          );
        })
        .map((event) => event.gameweek),
    ),
  ].sort((a, b) => a - b);
}

const firstKickoff = (week: WeekCalendar["gameweeks"][number] | undefined): number | null => {
  const times =
    week?.fixtures.flatMap((fixture) => {
      const time = instant(fixture.kickoff_utc);
      return time === null ? [] : [time];
    }) ?? [];
  return times.length ? Math.min(...times) : null;
};

export function weekState({
  treeGameweek,
  events,
  fixtures,
  now,
  current = {},
  available = {},
}: WeekStateInput): WeekState {
  const clock = fixtures === null ? now : calendarClock(fixtures, now);
  const calendar = [...(fixtures?.gameweeks ?? [])]
    .filter((week) => instant(week.deadline_utc) !== null)
    .sort((a, b) => a.gameweek - b.gameweek);
  const elapsed = calendar.filter((week) => instant(week.deadline_utc)! <= clock).at(-1);
  const plan = calendar.find((week) => week.gameweek === treeGameweek);
  const planDeadline = plan?.deadline_utc ?? null;
  const planClosed = plan === undefined ? null : instant(plan.deadline_utc)! <= clock;
  const flags = new Map(events.map((event) => [event.gameweek, event]));
  const elapsedFlags = elapsed === undefined ? undefined : flags.get(elapsed.gameweek);
  const publishedNext =
    elapsed !== undefined &&
    elapsedFlags?.finished === true &&
    elapsedFlags.data_checked &&
    plan !== undefined &&
    plan.gameweek > elapsed.gameweek &&
    planClosed === false;
  const focus = publishedNext ? plan : (elapsed ?? calendar[0]);
  const next = calendar.find((week) => week.gameweek > (focus?.gameweek ?? Infinity));
  let phase: WeekPhase = "unavailable";
  if (focus !== undefined) {
    const event = flags.get(focus.gameweek);
    if (clock < instant(focus.deadline_utc)!) phase = "before-deadline";
    else if (event?.finished && event.data_checked) phase = "checked";
    else if (event?.finished) phase = "finished";
    else if (
      focus.fixtures.every(
        (fixture) =>
          fixture.finished ||
          (instant(fixture.kickoff_utc) !== null &&
            clock >= instant(fixture.kickoff_utc)! + WEEK_MATCH_LIMIT_MS),
      )
    )
      phase = "played";
    else if (
      focus.fixtures.some(
        (fixture) =>
          instant(fixture.kickoff_utc) !== null && clock >= instant(fixture.kickoff_utc)!,
      )
    )
      phase = "playing";
    else phase = "before-kickoff";
  }
  const datedEvents = events.flatMap((event) => {
    const deadline =
      event.deadline_utc ?? calendar.find((week) => week.gameweek === event.gameweek)?.deadline_utc;
    return instant(deadline) === null ? [] : [{ ...event, deadline_utc: deadline }];
  });
  const finishedWeeks = resultWeeks(datedEvents, "finished", clock);
  const checkedWeeks = resultWeeks(datedEvents, "checked", clock);
  const finished = finishedWeeks.at(-1) ?? null;
  const checked = checkedWeeks.at(-1) ?? null;
  const afterPlay = phase === "played" || phase === "finished" || phase === "checked";
  const fixturesWeek = (afterPlay ? next : focus)?.gameweek ?? null;
  // An undated assigned match can retain the calendar phase. It cannot extend LIVE
  // beyond the last known kickoff's limit (owner's explicit decision A).
  const knownKickoffs =
    focus?.fixtures.flatMap((fixture) => {
      const kickoff = instant(fixture.kickoff_utc);
      return kickoff === null ? [] : [kickoff];
    }) ?? [];
  const liveOn =
    phase === "playing" &&
    knownKickoffs.length > 0 &&
    clock < Math.max(...knownKickoffs) + WEEK_MATCH_LIMIT_MS;
  const waiting = liveOn ? undefined : afterPlay || phase === "playing" ? next : focus;
  const targets: WeekTargets = {
    topBar: treeGameweek,
    plan: treeGameweek,
    resources: planClosed === false ? treeGameweek : null,
    fixtures: fixturesWeek,
    memberRail: planClosed === false ? treeGameweek : fixturesWeek,
    memberScore: elapsed?.gameweek ?? null,
    live: liveOn ? focus!.gameweek : null,
    liveWaiting: waiting?.gameweek ?? null,
    pill: liveOn ? focus!.gameweek : null,
    scoreboard: finished,
    lastResult: finished,
    leagueTotal: checked,
    race: checked,
    history: checked,
  };
  const weeks = { ...targets };
  for (const key of Object.keys(available) as WeekConsumer[]) {
    weeks[key] = availableWeek(targets[key], current[key] ?? null, available[key]!);
  }
  const boundaries = calendar
    .flatMap((week) => [
      instant(week.deadline_utc)!,
      ...week.fixtures.flatMap((fixture) => {
        const kickoff = instant(fixture.kickoff_utc);
        return kickoff === null ? [] : [kickoff, kickoff + WEEK_MATCH_LIMIT_MS];
      }),
    ])
    .filter((time) => time > clock);
  return {
    phase,
    clock,
    gameweek: focus?.gameweek ?? null,
    nextGameweek: next?.gameweek ?? null,
    elapsedGameweek: elapsed?.gameweek ?? null,
    planDeadline,
    planClosed,
    finishedWeeks,
    checkedWeeks,
    targets,
    weeks,
    nextKickoff: firstKickoff(waiting),
    changesIn: boundaries.length ? Math.min(...boundaries) - clock : null,
  };
}
