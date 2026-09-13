export type Language = "tr" | "en";

export type ReasonParams = Record<string, string | number | undefined>;

const en = {
  suggestionHistory: {
    title: "Weekly Suggestion History",
    overview: "Overview",
    systemNet: "System Suggestion · Net",
    memberNet: "Member's Squad · Net",
    weekDifference: "Weekly Difference",
    cumulative: "Cumulative Difference",
    total: "Total",
    comparedWeeks: (compared: number, recorded: number) =>
      `Compared Weeks: ${compared}/${recorded}`,
    overviewNote:
      "Weeks accumulate here in order. Select a week to inspect it. Member points are the final result of their actual FPL squad; all scores are net of transfer costs.",
    totalNote:
      "Difference = system suggestion − member's actual result. Totals and cumulative differences include only weeks with both final scores. Missing weeks are excluded from both totals, never counted as zero.",
    actualNotRecorded: "Member Result Missing",
    back: "Back To Member",
    week: "Recorded Week",
    gameweek: (week: number) => `Gameweek ${week}`,
    scope: "League 352490 · Last recorded pre-deadline pure-points suggestion for one gameweek.",
    method:
      "We score the recorded squad with settled player results, captain and automatic substitution rules. Past suggestions are never solved again. The difference is a comparison, not proof that you followed the suggestion or would have gained these points.",
    empty: "No Record",
    emptyBody:
      "No historical suggestion has been recorded for this member. We do not reconstruct missing weeks.",
    unreadable: "History Could Not Be Verified",
    retry: "Retry",
    unsettled: "Result Not Final",
    unavailable: "Comparison Unavailable",
    noEligible: "No suggestion was recorded before the deadline.",
    missingOutcomes: "The week is final, but its captured player results are missing.",
    invalid: "The saved data does not support a verified comparison.",
    pending: "Points remain hidden until the week is finished and its results are checked.",
    suggested: "Suggested Squad",
    actual: "Member's Actual Result",
    gross: "Gross Points",
    hits: "Transfer Cost",
    net: "Net Points",
    difference: "Suggested Net − Actual Net",
    actualMissing:
      "The member's final score or transfer cost is not recorded; the difference is unknown.",
    expectation: "Recorded XI + Captain Expectation",
    expectationNote:
      "Before transfer costs and additional chip points; this is not a net-score forecast.",
    captainBonus: "Captain Bonus",
    autosubs: "Points From Automatic Substitutes",
    chip: "Chip",
    players: "Suggested Players",
    player: "Player",
    role: "Recorded Role",
    starter: "Starting XI",
    bench: "Bench",
    captain: "Captain",
    vice: "Vice-Captain",
    forecast: "Expected",
    realized: "Actual",
    error: "Actual − Expected",
    minutes: "Minutes",
    playerNote:
      "Expected and actual are each player's unmultiplied points. The captain label shows the applied multiplier.",
    evidence: "Record Details",
    published: "Recorded Publication",
    deadline: "Deadline",
    captured: "Advice Data Captured",
    settledAt: "Results Captured",
    outcomeAsOf: "Results Available Through",
    adviceId: "Advice Capture",
    outcomeId: "Result Capture",
    digest: "Advice Digest",
    noChip: "None",
    wildcard: "Wildcard",
    freehit: "Free Hit",
    bboost: "Bench Boost",
    triple: "Triple Captain",
  },
  common: {
    loading: "Loading…",
    gameweek: (gameweek: number) => `Gameweek ${gameweek}`,
    gameweekShort: (gameweek: number) => `GW${gameweek}`,
    noDecisionForGameweek: "No decision for this gameweek.",
    noDecisionRecorded: "No decision recorded yet.",
    closed: "CLOSED",
    dayShort: "d",
    none: "None.",
    rawJson: "Raw JSON",
  },
  shell: {
    skip: "Skip to content",
    tagline: "a decision, and what it rests on",
    primary: "Primary",
    squad: "Squad",
    moves: "Suggested Moves",
    rivals: "Rivals",
    league: "League",
    analysis: "Analysis",
    footer: "Public league records, published plans and analysis.",
    operations: "Operations Status",
    notFound: "There is no page here.",
    metaDescription: "SquadOpt: a weekly FPL decision, and what it rests on.",
  },
  language: {
    label: "Language",
    tr: "Türkçe",
    en: "English",
  },
  theme: {
    label: "Theme",
    light: "Light",
    dark: "Dark",
    switchTo: (current: string, next: string) => `Theme: ${current}. Switch to ${next}.`,
  },
  squad: {
    loading: "Loading the latest decision…",
    dataError: "The site data could not be read.",
    noDecisionBody:
      "The first gameweek is decided about two hours before its deadline; this page fills in once the ledger holds an entry.",
    decisionError: "This decision could not be shown.",
    openingSquad: "Opening Squad",
    transferDecision: "Transfer Decision",
    why: "Why These Players →",
    deadline: "Deadline",
    deadlineIn: "Deadline In",
    projectedScore: "Projected Score",
    settledTitle: "Projection Versus Outcome",
    liveTitle: "Last Recorded Provisional Score",
    liveProvisional: "Provisional",
    liveStale: "Old capture · over 1 hour",
    liveUnavailable: "Score unavailable",
    liveUnavailableNote:
      "No verified live score is available for this decision. Missing data is not zero points.",
    liveMissing: "No live score data was found for this gameweek.",
    liveMismatch: "Score data does not match the selected decision or gameweek.",
    liveUnverified: "Score data is incomplete or could not be verified.",
    liveNamed: "Selected XI + chip",
    liveNet: "Provisional net",
    liveHit: (hit: string) => `${hit} transfer-hit points deducted once`,
    liveRule: "Captain/chip included; no automatic substitutions or vice-captain replacement.",
    liveFixtures: "Fixtures finished",
    liveBonusConfirmed: "Bonus confirmed in source",
    liveBonusPending: "Bonus not yet confirmed; points may change",
    liveCaptured: "Captured",
    liveSnapshotNote:
      "Last known capture, not a continuously updated feed. This is not the official FPL total after automatic substitutions.",
    settledAside: "Settled",
    settledProjected: "Projected",
    settledRealizedLabel: "Realized",
    settledNet: "Net",
    settledNetNote: "After Transfer-Hit Points",
    settledNote:
      "Player tiles show the published event points and the multiplier applied to the captain when the settled player fields are present.",
    seasonTitle: "Season Standing",
    seasonNet: "Season (Net)",
    seasonNetNote: (weeks: number, hits: string) => `${weeks} Settled · ${hits} Hit Points`,
    seasonLatestWeek: "Latest Settled Week",
    seasonLatestWeekNote: (gameweek: string, projected: string) =>
      `${gameweek} · Projected ${projected}`,
    seasonVsProjection: "Versus Projection",
    seasonVsProjectionNote: "Realized Minus Projected, Over Settled Weeks",
    projectedPlayerPoints: (points: string) => `xP ${points}`,
    realizedPlayerPoints: (points: string) => `Actual ${points}`,
    eventPointsUnavailable: "Event Points Pending",
    playerPointDifference: (difference: string) => `Difference ${difference}`,
    pointDifferenceUnavailable: "Difference Pending",
    captainMultiplier: (multiplier: number) => `×${multiplier} C`,
    squadCost: "Squad Cost",
    squadSellValue: "Squad Sell Value",
    bankAndFt: (bank: string, transfers: number) => `Bank ${bank} · ${transfers} FT Left`,
    budget: "Budget £100.0m",
    solver: "Solver",
    provedOptimal: "Proved Optimal, Single Thread",
    notProved: "Not Proved — Reported, Not Recommended",
    startingXi: "Starting XI",
    starterCount: (count: number) => `${count} Starters · Captain Counted Twice`,
    captain: "Captain",
    noCaptain: "Captain not in the starting eleven.",
    bench: "Bench",
    substitutionOrder: "In Substitution Order",
    limitsTitle: "What these numbers do not say",
    risk: "Risk",
    riskStatus: {
      available: "Available",
      unavailable: "Unavailable",
      not_requested: "Not Requested",
    },
    scenarioMean: "Mean of Scenarios",
    shiftedForOptimism: (points: string) => `Shifted ${points} for Selection Optimism`,
    scenarioCount: (count: number) => `${count} Scenarios`,
    rivalComparisons: "Rival Comparisons →",
    captured: "Captured",
    recordIdentity: "Record Identity",
    projection: "Projection",
    generated: "Page Generated",
    settledRealized: (points: string) => `Settled: ${points} Realized`,
    pitchLabel: "Starting eleven by position",
    captainLabel: "captain",
  },
  moves: {
    loading: "Loading the proposed moves…",
    error: "The moves could not be shown.",
    noDecisionBody: "Moves appear once a gameweek has been decided.",
    deadline: "deadline",
    title: "Suggested Moves",
    chip: "chip",
    openingTitle: "Opening squad — no transfers to make.",
    openingBeforeLink:
      "Gameweek 1 builds the squad from scratch, so there is nothing to move. The first wildcard and the other chips open in gameweek 2; from then on this page carries the planner's proposed transfers, what they cost in points, and the state they leave the bank and the free transfers in. See the ",
    openingLink: "squad it built",
    transfers: "transfers",
    transferNote: (paid: number, points: string) => `${paid} paid · ${points} points charged`,
    freeTransfers: "free transfers",
    freeTransferNote: (cap: number, cost: string) =>
      `cap ${cap}; the planner priced a hit at ${cost}`,
    bank: "bank",
    bankNote: (before: string, value: string) => `from ${before} · squad value ${value}`,
    out: "Out",
    in: "In",
    leaving: (count: number) => `${count} leaving`,
    arriving: (count: number) => `${count} arriving`,
    restsOn: "What this proposal rests on",
    restsOnItems: [
      "The planner maximises the projection it was given over its horizon; a transfer is worth making only if that projection is right about the players involved.",
      "Prices are the capture's: outgoing players are valued at their sell price (purchase plus half of any rise), incoming at the price shown.",
      "Chips are offered inside their published windows only; a chip that is not shown was either unavailable or worth less than holding it.",
    ],
    plannerContract: (status: string) => `Planner contract ${status} at decision time.`,
  },
  decision: {
    title: "Decision View",
    shareable: "Shareable in the URL",
    intro:
      "The horizon and play mode save how you want to read the recommendation. This screen shows the current ledger decision; changing a selection does not run a new optimization yet.",
    horizon: "Planning Horizon",
    week: (count: number) => `${count} week${count === 1 ? "" : "s"}`,
    liveControl: "live control",
    researchShadow: "research shadow",
    liveControlTitle: "H1 drives the current decision.",
    liveControlBody: "Only the one-week control is eligible to become the live recommendation.",
    liveEvidenceBody:
      "The batch H1 reproduced the frozen ledger decision; the ledger remains authoritative.",
    researchShadowTitle: (weeks: number) => `H${weeks} is reserved for shadow evidence.`,
    researchShadowBody:
      "A result appears after the batch runs and cannot replace the live recommendation until its forecast and solver gates pass.",
    shadowEvidenceBody: (status: string, proof: string) =>
      `The batch computed this shadow (${status}; solver proof: ${proof}). It is evidence, not live advice.`,
    mode: "Play Mode",
    leagueId: "League ID",
    leaguePlaceholder: "League number or FPL link",
    leagueHelp: "Precomputed for the registered league; opens its members page.",
    leagueConnect: "Connect",
    leagueInvalid: "Enter a league number or an FPL league link.",
    leagueUnavailable:
      "League member data is not published yet; it arrives with the next decision publish.",
    leagueMismatch: (leagueId: number) =>
      `This site precomputes league ${leagueId} only; that is the league it can open.`,
    diagnostic: "diagnostic",
    diagnosticTitle: (weeks: number) =>
      `The league-relative ${weeks}-week result is a diagnostic, never a chance of winning.`,
    diagnosticBody:
      "The scenarios price only part of the crowd's measured +7.19 points/week edge, so the competitive horizon is directional only.",
    sourceBefore: "Price labels come from the zero-point budget cell of the ",
    sourceAfter: (folds: number) =>
      ` measurement against a synthetic risk-neutral rival over ${folds} folds.`,
    modes: {
      pure: "Pure Points",
      pureDescription: "Targets the highest expected points independently of a rival.",
      purePrice: "No rival budget, no measured cost",
      safe: "Cautious",
      safeDescription:
        "Counts finishing level with the rival as success; the price is its measured cost in expected points.",
      aggressive: "Aggressive",
      aggressiveDescription: "A balanced competitive mode focused on moving ahead of the rival.",
      extreme: "Very Aggressive",
      extremeDescription: "Looks for harder decisions that can create a gap of more than five.",
      cost: "cost",
      points: "points",
    },
  },
  rivals: {
    loading: "Loading the projections…",
    error: "The analysis could not be shown.",
    nothingTitle: "Nothing to compare yet.",
    nothingBody: "Projections and rival comparisons appear once a gameweek has been decided.",
    kicker: (season: string, gameweek: number, pool: number) =>
      `${season} · gameweek ${gameweek} · pool of ${pool} players`,
    title: "Rival Analysis",
    lede: "Two questions on one page: who else could have been picked (the projections the solver chose from), and how the chosen squad compares with a rival's in the same scenarios.",
    projections: "Projections",
    projectionsBody:
      "The top of the pool per position, ranked by projected points, with the frozen squad marked. A better-projected player who is not selected was priced out, capped by his club's three-player limit, or displaced by the formation.",
    topPool: (count: number) => `top ${count} of the pool`,
    projectedPool: (position: string) => `Projected pool, ${position}`,
    player: "player",
    price: "price",
    inSquad: "in squad",
    bench: "bench",
    provenance: "Provenance",
    capture: "capture",
    model: "model",
    features: "features",
    unavailable: "unavailable in pool",
    against: "Against Rivals",
    noRivalTitle: "No rival was scored against this decision.",
    noRivalBeforeStatus:
      "A rival comparison needs two things this gameweek does not have: a decision whose risk view was evaluated (this one is ",
    noRivalAfterStatus:
      "), and a rival squad to score in the same scenarios. Both are being wired up — the template rival comes from the capture's ownership, mini-league rivals from the entry data. Until then this page shows the projections below rather than a probability nobody measured.",
    linksBefore: "Where the squad itself came from is on ",
    squadPage: "the squad page",
    linksMiddle: "; how the season compares with everyone else is on ",
    leaguePage: "the league page",
  },
  league: {
    loading: "Loading the season…",
    ledgerError: "The ledger could not be read.",
    noSeason: "No season yet.",
    season: "season",
    title: "League Analysis",
    lede: "How this season is going, and how that compares with everyone else playing the same game.",
    decidedSettled: "decided · settled",
    decidedSettledNote: "gameweeks with a frozen decision · with an outcome",
    realizedProjected: "realized vs projected",
    realizedWeeks: (points: string) => `${points} realized on settled weeks`,
    shownWhenSettled: "shown once a gameweek settles",
    hitsChips: "hits · chips",
    noChip: "no chip played yet",
    cumulative: "Projected vs realized, cumulative",
    points: "points",
    fromGw2: "from gameweek 2",
    onePoint:
      "One gameweek is a point, not a line. The chart starts once a second decision exists; the realized line starts once the first gameweek settles.",
    againstLeague: "Recorded squad and FPL average",
    comparisonMissing:
      "The comparison is built from the capture the decision used; this site build did not include one, so nothing about the league is claimed here.",
    firstRow: "The first row appears once gameweek 1 is decided.",
    ourSeason: "Our Season",
    ledgerAside: "each row is a frozen, checksummed ledger entry",
    ledgerCaption: "Season ledger, one row per gameweek",
    decision: "decision",
    projected: "projected",
    realized: "realized",
    error: "error",
    hits: "hits",
    chip: "chip",
    state: "state",
    note: "SquadOpt's recorded squad net includes captain/chip effects and transfer hits, but no autosubs or vice-captain replacement. It is not directly comparable with official FPL scores.",
    modeNote:
      "Each row says the mode it was recorded in — live: decided before that deadline, from a capture that run took; replay: recorded after that deadline, or from a capture the run did not take but named. A row with no mode was recorded before the ledger stamped one.",
    chartReplays: (count: number) =>
      `${count} of the gameweeks drawn here were recorded as replay rather than live; the table below says which.`,
    weeklySummary: (snapshot: string) =>
      `the game's own weekly summary · capture ${snapshot.slice(0, 24)}…`,
    chartStarts:
      "The chart starts with the first scored gameweek: the game publishes an average only once a gameweek finishes, so there is nothing to draw yet.",
    templateTitle: "How much of this squad is the template",
    gameweekAside: (gameweek: number) => `gameweek ${gameweek}`,
    meanOwnership: "mean starter ownership",
    meanOwnershipNote: "the average share of the field that owns one of our starters",
    effectiveOwnership: "effective ownership",
    effectiveOwnershipNote:
      "starters plus the captain again — the exposure we share with the field",
    differentials: "differentials",
    differentialNote: (threshold: number) => `starters owned by ${threshold}% or less`,
    mostOwned: "Most Owned",
    leastOwned: "least owned",
    ownershipNote:
      "Ownership is the capture's selected_by_percent at decision time; it moves after the deadline and this page does not follow it.",
    openingSquad: "Opening Squad",
    transferCount: (count: number) => `${count} transfer${count === 1 ? "" : "s"}`,
    deadline: "deadline",
    settled: "settled",
    decided: "decided",
    cumulativeLabel: (projected: string) =>
      `Cumulative projected (${projected}) versus realized points by gameweek`,
    projectedCumulative: "projected, cumulative",
    realizedCumulative: "realized, cumulative",
    afterSettle: " (after the first settle)",
    averageLabel: (count: number) =>
      `Recorded squad net and official FPL average over ${count} scored gameweeks`,
    ourNet: "recorded squad net",
    gameAverage: "official FPL average",
    lastWeek: (points: string) => `last scored week difference: ${points}`,
  },
  scoreboardComparisons: {
    title: "Weekly comparison and error breakdown",
    week: "GW",
    name: "Decision",
    net: "Points",
    zero: "Starters with no minutes",
    minutes: "Minutes shortfall",
    captain: "Captain shortfall",
    autosub: "Autosub recovery",
    missing:
      "- means not measured. Minutes shortfall covers starters who played; negative means more minutes than projected. Captain shortfall is expected minus received bonus points.",
    legacy: "Named eleven; autosubs and vice-captain recovery unavailable",
    synthetic: "Reconstructed legal squad within the opening budget; no transfer history",
    game: "Game's published average",
    official: "Official substitutions and captain scoring",
    absent: "Decision record unavailable",
    pending: "Awaiting settled results",
    names: {
      system: "System",
      base: "Bare component",
      elite_xi: "Lagged elite XI",
      ownership_template: "Ownership template",
      league_mean: "League mean, net",
      game_mean: "Game average",
    },
  },
  leagueScoreboard: {
    title: "Weekly scoreboard",
    aside: (snapshot: string) => `capture ${snapshot.slice(0, 24)}…`,
    loading: "Loading the scoreboard…",
    notPublished:
      "The scoreboard is not published yet. It appears after the first weekly run that writes it.",
    notAvailable: "The scoreboard could not be read.",
    caption:
      "Per finished gameweek: our paper ledger, the league members' mean net, the Top-100 mean, the FPL average and the highest score",
    gameweek: "GW",
    ours: "SquadOpt · named eleven",
    members: "league members · mean net",
    membersCounted: (count: number) => `${count} member${count === 1 ? "" : "s"}`,
    top100: "Top-100 · mean",
    top100NotFinal: "not final",
    top100Net: "net of hits",
    top100Gross: "gross of hits",
    average: "FPL average",
    highest: "highest",
    notSettled: "decided, not settled",
    provisional: "provisional",
    noGameweek: "No gameweek has finished in this capture yet.",
    cumulative: (gameweek: number) => `cumulative through GW${gameweek}`,
    oursCovers: (gameweeks: string) => `GW ${gameweeks} only`,
    oursNone: "no settled week",
    membersTotal: (count: number) => `mean total of ${count}`,
    membersCovers: (gameweeks: string) => `covers GW ${gameweeks}`,
    paperLedger:
      "Our squad is a paper ledger. The comparison table names each row's scoring basis. Older decisions lack a frozen bench order and vice-captain, so their figure scores only the named eleven. New decisions record both and can be scored with official substitutions. A member's net is their week minus the transfer cost, read from their own history.",
    grossNote:
      "The Top-100 mean for this capture is gross of transfer costs: it is the cohort standings' own weekly total, before hits are taken off, so it is not on the same basis as the net columns beside it and the two do not compare. It is netted only when the week's elite-picks capture covers all hundred.",
    provisionalNote:
      "A gameweek marked provisional has finished but has not been data-checked in this capture: bonus points land fixture by fixture, so its scores can still move.",
    modeNote:
      "live: decided before the deadline, from a capture that run took. replay: recorded after that deadline, or from a capture the run did not take but named.",
  },
  leagueEntry: {
    title: "Find your league",
    label: "League ID",
    hint: "Type your league ID to continue.",
    submit: "Find league",
    invalid: "Enter a positive whole-number league ID.",
    loading: "Reading the published league…",
    unsupported: "Only league 352490 is supported for now.",
    missing: "The published league document is unavailable. Try again later.",
    failed: "The published league data could not be read. Try again.",
  },
  memberResources: {
    transfersTitle: "Free transfers",
    unknown: "Unknown",
    chipsTitle: "Chips",
    chipsMissing: "No chip information",
    asOf: (week: number) => `Before GW${week}`,
    halves: { first_half: "First half", second_half: "Second half" },
    window: (start: number, stop: number) => `GW${start} to GW${stop}`,
    used: (week: number) => `Used in GW${week}`,
    noWindow: "No window published",
    states: {
      available: "Available",
      used: "Used",
      expired: "Expired",
      not_yet: "Not open yet",
      unknown: "Unknown",
    },
  },
  leagueMembers: {
    loading: "Loading league members…",
    computeTitle: "Compute this plan",
    computeBodySelf: "Compute this plan from your own squad.",
    computeBodyOther:
      "You are viewing another member. The computation starts from this member's public squad.",
    computeRivalNearest: "Nearest above in the standings",
    computeButton: "Compute",
    computeRequesting: "Sending the request…",
    computeQueued: "Queued",
    computeRunning: "Computing",
    computeWaiting: "The answer will appear here when the computation finishes.",
    computeWaitingWithFallback: "Showing the previously published plan below while this computes.",
    computeDone: "Plan available",
    computePublished: "Published plan",
    computeUnsupportedSelection:
      "Compute supports pure points at one, three or five weeks, and a one-week strategy with a rival chosen. A rival strategy is not computed over a longer window.",
    computeProvenance: (capture: string, at: string) => `Capture ${capture}, result dated ${at}.`,
    computeStaticFallback: "The backend was unreachable; this is the published static answer.",
    computeUnavailable:
      "Only the published site is available right now; this combination was not published.",
    computeFailed:
      "The computation did not finish. The published plan, where one exists, still stands.",
    adviceComputedBadge: "Computation result",
    advicePublishedWhileComputing: "The published plan is shown while the computation runs.",
    adviceBaselineWhileComputing:
      "This is the published pure-points, one-week plan; the requested combination is still computing.",
    adviceRequestHint: "You can ask for it with Compute above.",
    viewerTitle: "Which one is you?",
    viewerBody:
      "Pick your own row to get advice from your squad. Select again whenever you reopen or refresh the site. This is a claim, not a login: anyone can pick anyone, and that is fine because everything shown here is already public after the deadline.",
    viewerSelect: "This is me",
    viewerYouBadge: "You",
    viewerSelected: (name: string) =>
      `Viewing as ${name}. Advice pages will start from this squad.`,
    viewerClear: "Clear Selection",
    viewerChange: "Change Member",
    viewerMissing:
      "Your saved selection is not in the published member list. Choose another member or clear it.",
    viewerOpenMine: "Open my squad →",
    notYourPageTitle: "Not your page",
    notYourPageBody: "You picked another row as yourself; this page advises this member.",
    notYourPageLink: "Go to my page →",
    strategyTitle: "Your play",
    strategyIntro:
      "Every option below was solved from your own squad; a rival strategy names the member you play against.",
    strategyLegend: "Strategy",
    strategies: {
      "saf-puan": {
        name: "Pure points",
        // Not "the highest expected points": the solve maximises the eleven, the captain
        // and the bench together, and the figure below the card is the eleven and the
        // captain only. A banded plan that keeps a weaker bench can read higher on that
        // figure. Measured on the 2026-27 GW4 capture: entry 3832237's pure-points plan
        // publishes 46.5454 against its ortak-koru plan's 46.7016, both OPTIMAL, both
        // free of hits.
        description:
          "Points alone, no rival in the equation. The plan is chosen on the eleven, the captain and the bench together, so another option can still show more expected points for the eleven and captain.",
      },
      "ortak-koru": {
        name: "Keep the shared core",
        description:
          "Requests at least 9 shared players between your recommended 15 and the rival's XI. This minimum may be lowered to fit the free-transfer limit; the published plan states the applied bound.",
      },
      "fark-yarat": {
        name: "Create a gap",
        description:
          "Requests at most 5 shared players between your recommended 15 and the rival's XI. This maximum may be raised to fit the free-transfer limit; the published plan states the applied bound.",
      },
    } as Record<"saf-puan" | "ortak-koru" | "fark-yarat", { name: string; description: string }>,
    rulePickBadge: "The rule's pick",
    rulePickNote: (rival: string, gap: string, weeks: number) =>
      `A declared rule marks one option from two numbers: your league points against ${rival} (${gap}) and the ${weeks} gameweeks still to play. The rule is written down, not measured — nothing has tested whether following it does better than ignoring it — so it labels an option and never chooses for you.`,
    publicationStates: {
      "published-missing": {
        title: "The listed advice file is unavailable.",
        body: "The index lists this plan, but its document is missing. This does not mean the publisher could not solve the plan.",
      },
      "context-mismatch": {
        title: "The returned advice does not match this view.",
        body: "Its member, selection, week or data snapshot differs. The mismatched plan is not shown; the held squad remains visible.",
      },
      "index-missing": {
        title: "This member's advice index is not published.",
        body: "Strategies, windows and rivals can be selected only after the index is available.",
      },
      "index-error": {
        title: "This member's advice index could not be read.",
        body: "The held squad remains visible. Advice requests are paused until the index can be read.",
      },
      "not-listed": {
        title: "This selection is not listed in this publication.",
        body: "Choose a strategy, window and rival that this member's index publishes.",
      },
      "declared-unavailable": {
        title: "The publisher could not produce this selection.",
        body: "The publisher marked this selection as having no available plan.",
      },
    },
    rivalPlayersTitle: "Shared and different players",
    rivalPlayersBasis:
      "Names compare the recommended 15 (XI plus bench) with the rival's published XI, using player IDs from the same capture. They are not rankings or new projections. The published expected gap compares the two XIs with captains and subtracts this plan's transfer hits.",
    rivalPlayerGroups: {
      shared: "Shared: recommended 15 and rival XI",
      recommendedOnly: "Recommended 15 only",
      rivalOnly: "Rival XI only",
    },
    rivalPlayersNone: "None",
    rivalPlayersUnavailable:
      "Player names cannot be compared: matching league, season, gameweek, capture and complete player lists are required.",
    rivalLegend: "Rival",
    rivalLabel: "The member you are playing against",
    rivalChoose: "Choose a rival",
    rivalDefaultSuffix: "(nearest above in the standings)",
    rivalUnavailableSuffix: "(not computed)",
    rivalNone: "No other member's squad is published for this week.",
    rivalNoDefault:
      "This publish named no standings neighbour for you, so no rival is chosen on your behalf: pick one and the plan against them can be computed.",
    rivalNote: "The rival's public eleven is a constraint and a comparison, nothing more.",
    windowLegend: "Window",
    windowNotComputed:
      "Only the one-week plan is on hand for this choice: three- and five-week plans exist for pure points only, and only where this publish solved them; a rival strategy is one week at a time.",
    windowLimits:
      "A three- or five-week plan repeats the week-1 projection over the fixture calendar, one transfer a week, and is published with the limits it assumes; it is not a forecast of the later weeks.",
    windowFellBack: (asked: number, shown: number) =>
      `The ${asked}-week window was not published for this strategy, so this selection is the ${shown}-week plan.`,
    windowTitle: (weeks: number) => `The ${weeks}-week window`,
    windowRule:
      "The moves and the lineup above are the first week's. Each row below is one gameweek of the plan, in expected points under the limits stated here.",
    windowLimitsLabel: "What this window assumes",
    windowWeek: "Week",
    windowWeekOf: (gameweek: number) => `GW${gameweek}`,
    windowHits: "Hit points",
    windowPoints: "Expected points",
    // Only exact published limit keys receive these reviewed explanations.
    statedLimitUnknown:
      "No translated explanation is available for this published window assumption.",
    statedLimits: {
      "The first week's projection is repeated over the later weeks, rescaled by each club's fixture count in that week relative to its count in the first week, from the captured calendar; a club with no fixture in the first week stays at zero all the way through, and the later weeks are not projected separately.":
        "The first week's projection is repeated over the later weeks, rescaled by each club's fixture count in that week relative to its count in the first week, from the captured calendar; a club with no fixture in the first week stays at zero all the way through, and the later weeks are not projected separately.",
      "Availability is applied once, from the capture: injuries, rotation and suspensions after it are not seen.":
        "Availability is applied once, from the capture: injuries, rotation and suspensions after it are not seen.",
      "Every week inside the window, the first included, is capped at one transfer (a wildcard week excepted); the one-week plan has no such cap.":
        "Every week inside the window, the first included, is capped at one transfer (a wildcard week excepted); the one-week plan has no such cap.",
      "The Top-100 uplift is inside the first week's numbers, and the repetition carries it into every later week.":
        "The Top-100 uplift is inside the first week's numbers, and the repetition carries it into every later week.",
      "Prices are held at the captured values; no price change is modelled.":
        "Prices are held at the captured values; no price change is modelled.",
      "No chip is offered inside the window. A finite window counts nothing for holding a chip back, so a planner that could reach one would spend it; chip timing is a season-long decision this window cannot price.":
        "No chip is offered inside the window. A finite window counts nothing for holding a chip back, so a planner that could reach one would spend it; chip timing is a season-long decision this window cannot price.",
    } as Record<string, string>,
    controlUnprovenBody: (gap: string) =>
      `The pure-points plan this price is measured against was not proven optimal (gap ≤ ${gap} pts), so the price is published as a ceiling — the most this strategy can cost — and not as an exact figure.`,
    overlapLine: (count: number) => `${count} of the rival's eleven in your fifteen`,
    gapLine: (points: string) => `expected gap vs rival ${points}`,
    captainShared: "same captain",
    planWithinFree: (cap: number, target: number, applied: number) =>
      `Free-transfer allowance ${cap}, no transfer penalties: requested overlap bound ${target}, applied overlap bound ${applied}.`,
    planWithHits: (cap: number, target: number) =>
      `Plan allowing paid transfers: free-transfer allowance ${cap}, requested overlap bound ${target}. Published transfer penalties are included in the price.`,
    alternativeWithHits: (applied: number, hits: string, cost: string) =>
      `Alternative allowing paid transfers: applied overlap bound ${applied}; published transfer penalties ${hits} points, cost ${cost} expected points against pure points.`,
    alternativeWithinFree: (applied: number, cost: string) =>
      `Alternative within free transfers: applied overlap bound ${applied}; cost ${cost} expected points against pure points.`,
    // The same two sentences where a proof is missing: the figure is the most the
    // candidate could have cost, never a claimed exact cost.
    alternativeWithHitsAtMost: (applied: number, hits: string, cost: string) =>
      `Alternative allowing paid transfers: applied overlap bound ${applied}; published transfer penalties ${hits} points, cost at most ${cost} expected points against pure points.`,
    alternativeWithinFreeAtMost: (applied: number, cost: string) =>
      `Alternative within free transfers: applied overlap bound ${applied}; cost at most ${cost} expected points against pure points.`,
    templatesTitle: "Game templates",
    templatesBody:
      "A template is a named strategy-and-window pair. Applying one sets the same shareable selection the controls read; your own templates live in this browser.",
    templateMeta: (strategy: string, window: number, rival: string) =>
      `${strategy} · ${window}w · ${rival}`,
    templateNamePlaceholder: "Name this combination",
    templateSave: "Save current",
    templateRemove: (name: string) => `Remove template ${name}`,
    notAvailable: "The member list is not published.",
    notAvailableBody: "This site has no published member-list document available.",
    membersUnreadable: "The member list could not be read.",
    membersUnreadableBody:
      "The published document did not return readable data. You can try the same document again.",
    membersAuxiliaryUnavailable:
      "This member's held squad remains visible. Some names in the member list may be unavailable.",
    retryPublishedRead: "Try reading again",
    loadingAdvice: "Loading published advice…",
    entryUnreadable: "This member's squad could not be read.",
    entryUnreadableBody: "The published squad document did not return readable data.",
    unprovenPlanGapUnknown:
      "The proof for this plan is incomplete. The optimality gap was not published.",
    controlGapUnknown:
      "The pure-points control was not proven optimal and its gap was not published. Any stated price ceiling remains an upper bound.",
    planWithinFreeUnknown: (cap: number, target: number) =>
      `The plan used a free-transfer limit of ${cap} and requested an overlap bound of ${target} players. The applied overlap bound was not published.`,
    hitPointsNotPublished: "an unpublished number of",
    noPlanInRecord:
      "This record does not provide enough plan detail to establish a no-transfer recommendation.",
    publicationReasons: {
      "The advice rules belong to another capture.":
        "The advice inputs use different data snapshots.",
      "The advice rules belong to another season.":
        "The advice inputs belong to different seasons.",
      "A member cannot be their own rival.": "The selected member and rival are the same.",
    } as Record<string, string>,
    publicationReasonUnknown:
      "The publisher supplied a reason, but no translated explanation is available.",
    loadingEntry: "Loading this member's squad…",
    adviceNotComputed: "This combination was not computed for this publish.",
    adviceNotComputedBody:
      "The site publishes the decisions it actually solved from your squad: pure points, and each strategy against each rival where a plan exists. A pair that has no plan says so in the rival list.",
    adviceUnreadable: "This member's advice could not be read.",
    adviceUnreadableBody:
      "The squad above came from this build and the advice document did not answer, so this is a fault in reading the site rather than a combination nobody solved. Reloading, or reporting it, is the right move.",
    freeHitSquadBasis: (week: number) =>
      `Free Hit played; this advice stands on your GW ${week} squad.`,
    entryNotAvailable: "This member’s squad document is not published.",
    entryNotAvailableBody: "Return to the member list or try again after the next publication.",
    invalidEntry: "This entry ID is not valid.",
    exampleData: "example data",
    systemTeamBadge: "SquadOpt · system team",
    systemTeamTitle: "SquadOpt is playing too",
    leagueNumber: (leagueId: number) => `league ${leagueId}`,
    title: "League Members",
    members: "Members",
    memberCount: (count: number) => `${count} members`,
    caption: (leagueName: string) => `${leagueName} member standings`,
    rank: "rank",
    member: "member",
    team: "team",
    gameweekNetPoints: "GW net points",
    gameweekNetPointsFor: (gameweek: number) => `GW${gameweek} net points`,
    gameweekNetNote:
      "The gameweek column is net for every row: the week's score after the transfer hits taken that week, which is the amount the season total moved by. The FPL site shows the week before hits, so a member who took a four-point hit reads four points lower here than there. A row whose hit is not in the published data shows a dash rather than a number on the other basis.",
    noScoredWeek:
      "No gameweek has been finalised yet, so no scores are published: points are only final once the platform has added bonus and checked the week.",
    total: "total",
    movement: "movement",
    unknown: "unknown",
    newMember: "new",
    movementLabel: (movement: "up" | "down" | "same", places: number) =>
      movement === "same" ? "—" : `${movement === "up" ? "↑" : "↓"} ${places}`,
    unknownMember: "Unknown Member",
    unknownTeam: "Unnamed Team",
    publicDataTitle: "Public after the deadline",
    publicDataBody:
      "These records are public FPL data after the gameweek deadline. SquadOpt never asks for an FPL password, session or private account access.",
    backToMembers: "← League members",
    incompleteTitle: "Incomplete Source Record",
    missingFieldLabels: {
      free_transfers: "free-transfer allowance",
      purchase_prices: "purchase prices",
    } as Record<string, string>,
    missingFieldUnknown: "other missing data",
    incompleteBody: (fields: string) =>
      `The source did not provide: ${fields}. Nothing is invented to fill it.`,
    entryAssumptionsTitle: "Public-data limits",
    currentPriceFallback:
      "Purchase prices are not public. Current prices are used as selling prices, which may overstate the available budget after a price rise.",
    memberSquad: "Member Squad",
    heldViceCaptainUnavailable: "The published squad does not name the vice-captain.",
    starterCount: (count: number) => `${count} starters`,
    bench: "Bench",
    benchCount: (count: number) => `${count} substitutes`,
    emptySquad: "No squad is available for this member.",
    emptySquadBody: "The published member record does not contain squad data.",
    advice: "Suggested Moves",
    honestyRule:
      "Advice shows expected-point trade-offs. Strategy labels follow declared rules; the published solver status and bounds state what was established.",
    independentAdviceRule:
      "Your advice is calculated from your squad and selected strategy. Every member is evaluated independently under the same decision rules.",
    squadoptComparisonTitle: "Recorded score difference",
    squadoptComparison: (difference: string) =>
      `Your point difference from SquadOpt's squad this gameweek: ${difference}`,
    noMove: "The published plan recommends no transfers.",
    noAdviceMissingData: "Advice is withheld because the source squad is incomplete.",
    diagnosticOnly:
      "The two starting XIs use the same projection. Shared players with equal multipliers cancel out; the remaining expected points, captain multipliers and this plan’s transfer hits determine the expected gap.",
    unprovenPlanBadge: "Proof incomplete",
    unprovenPlanBody: (gap: string) =>
      `The solver could not finish the proof for this plan (gap ≤ ${gap} pts). It is the best plan the search found, not a plan shown to be the best one.`,
    out: "Out",
    in: "In",
    projectedGain: (points: string) => `${points} projected gain`,
    weekTransferCost: (points: string) =>
      `~${points} expected-point cost for this week's transfers in total: the game charges the week, not each move.`,
    windowValueReason: "Part of the multiweek plan using published projections.",
    pointsGainReason: "Part of the one-week pure-points plan, chosen for expected points alone.",
    modeTradeoffReason: "This move is part of the selected strategy’s expected-point trade-off.",
    planCost: (points: string) =>
      `This strategy gives up ~${points} expected points against the pure-points pick, hits included.`,
    // The same price where a proof is missing. A bound is not a range around a guess:
    // the figure is the largest the cost can be, and the true cost is somewhere at or
    // under it — which is a fact about a search that stopped, never a chance of anything.
    planCostAtMost: (points: string) =>
      `This strategy gives up at most ${points} expected points against the pure-points pick, hits included.`,
    planRival: (name: string) => `priced against ${name}'s squad`,
    lineupTitle: "Your gameweek",
    lineupRule:
      "Captain, vice-captain, eleven and bench order follow the same projection as the moves; the bench is listed in the order the game's automatic substitutions walk it.",
    expectedOwnPoints: (points: string) =>
      `${points} expected points for the eleven with the captain doubled`,
    captainLabel: "Captain",
    viceCaptainLabel: "Vice-captain",
    startingXiLabel: "Starting eleven",
    benchOrderLabel: "Bench order",
    chipLabel: "Chip",
    chipNone: "No chip this gameweek",
    chipNames: {
      bboost: "Bench Boost",
      "3xc": "Triple Captain",
      wildcard: "Wildcard",
      freehit: "Free Hit",
    } as Record<string, string>,
    linkTitle: "Classic league 352490",
    linkBody:
      "The member surface is prepared mock-first; every row will link to that entry's public post-deadline squad and suggested moves.",
    linkLabel: "Open league members →",
  },
  reasonCodes: {
    no_capture: () => "no capture is held; the calendar is unknown",
    settle_due: (p: ReasonParams) =>
      `gameweek ${p.gameweek} is finished in the latest capture and its decision has no outcome`,
    recapture_for_outcome: (p: ReasonParams) =>
      `gameweek ${p.gameweek} was decided but is not marked finished; the capture is ${p.capture_age_hours} h old`,
    await_outcome: (p: ReasonParams) =>
      `gameweek ${p.gameweek} awaits its outcome; next look after ${p.recapture_hours} h`,
    deadline_missed: (p: ReasonParams) =>
      `gameweek ${p.gameweek} closed with no decision recorded; nothing can be decided for it now`,
    no_open_deadline: () => "no deadline is open in the latest capture's calendar",
    already_decided: (p: ReasonParams) =>
      `gameweek ${p.gameweek} is already decided; nothing to do until its outcome`,
    before_window: (p: ReasonParams) =>
      `gameweek ${p.gameweek} deadline in ${p.hours_left} h; capture opens ${p.window_hours} h before it`,
    capture_window_open: (p: ReasonParams) =>
      `gameweek ${p.gameweek} deadline in ${p.hours_left} h and no capture from inside the window is held`,
    decide_opening: (p: ReasonParams) =>
      `opening gameweek ${p.gameweek}: the capture is inside the window`,
    decide_ready: (p: ReasonParams) =>
      `gameweek ${p.gameweek}: capture and projection handoff are both ready`,
    handoff_missing: (p: ReasonParams) =>
      `gameweek ${p.gameweek} deadline in ${p.hours_left} h, capture held, but the projection handoff is missing`,
  },
  riskReasons: {
    not_requested: "No residual history was supplied; distributional risk was not evaluated.",
    available: "Risk metrics are supported by matched historical residual evidence.",
    model_mismatch: "The residual history was produced by a different model contract.",
    unsupported_opening_gameweek: "Midseason residuals do not support opening-gameweek risk.",
    insufficient_history: "The eligible residual history is too short to calibrate.",
  },
  verdictCodes: {
    no_scored_gameweeks: () =>
      "No gameweek has been scored yet, so there is nothing to compare: the game publishes an average only once a gameweek finishes.",
    standing: (p: ReasonParams) => {
      const caveat =
        p.caveat === "noise"
          ? " - one gameweek is noise, not evidence"
          : p.caveat === "few"
            ? " - still fewer weeks than a season's variation needs"
            : "";
      const own =
        p.mean_starter_ownership !== undefined
          ? `; the starting eleven averages ${p.mean_starter_ownership}% ownership`
          : "";
      const sign = Number(p.difference) >= 0 ? "+" : "";
      return `${sign}${p.difference} points against the game's average over ${p.scored} scored ${Number(p.scored) === 1 ? "gameweek" : "gameweeks"}${caveat}${own}.`;
    },
  },
  status: {
    loading: "Loading the tick status…",
    unavailable: "Status is not available.",
    noStatus: "No status recorded.",
    kicker: (contract: string, time: string) => `season tick · ${contract} · as of ${time}`,
    title: "Status",
    nextGameweek: "next gameweek",
    deadline: (time: string) => `deadline ${time}`,
    noDeadline: "no open deadline in the latest capture",
    timeToDeadline: "time to deadline",
    deadlinePassed: "deadline passed",
    deadlineUnknown: "not known",
    atPublish: (hours: string) => `${hours} h remained when this was published`,
    latestCapture: (capture: string) => `latest capture ${capture}`,
    noCapture: "no capture held",
    decidedSettled: "decided · settled",
    gameweeks: (weeks: number[]) => `GW ${weeks.join(", ")}`,
    nothingDecided: "nothing decided yet",
    actionsTitle: "What the tick would do now",
    idle: "idle",
    actionCount: (count: number) => `${count} action(s)`,
    nothingDue: "Nothing is due.",
    recent: "Recent Run Log",
    newest: "newest first",
    noLog: "No run log yet — the tick has not run on this machine.",
  },
  analysis: {
    types: {
      passed: "gate passed",
      negative: "clean negative",
      descriptive: "descriptive",
      prereg: "prereg",
    },
    noDate: "date not recorded",
    notFoundTitle: "Measurement not found.",
    notFoundBody: "The index has no artifact with this identifier.",
    loadingDocument: "Loading measurement…",
    documentError: "The measurement could not be opened.",
    back: "← Analysis Center",
    loadingIndex: "Loading measurement index…",
    indexError: "The Analysis Center could not be opened.",
    kicker: "evidence beside the decision",
    title: "Analysis Center",
    lede: "Clean negatives stay here alongside passed gates. The content is an unchanged copy of the English source documents.",
    viewLabel: "Measurement View",
    all: "All Measurements",
    negatives: "Negatives",
    filters: "Measurement Filters",
    type: "Type",
    phase: "Phase",
    allOption: "All",
    from: "Start Date",
    to: "End Date",
    count: (shown: number, total: number) => `${shown} / ${total} measurements shown`,
    empty: "No measurements match these filters.",
  },
} as const;

type MessageSchema<T> = {
  [K in keyof T]: T[K] extends (...args: infer A) => string
    ? (...args: A) => string
    : T[K] extends readonly string[]
      ? readonly string[]
      : T[K] extends object
        ? MessageSchema<T[K]>
        : string;
};

const tr: MessageSchema<typeof en> = {
  suggestionHistory: {
    title: "Haftalık Öneri Geçmişi",
    overview: "Genel Bakış",
    systemNet: "Sistem Tavsiyesi · Net",
    memberNet: "Kullanıcının Kadrosu · Net",
    weekDifference: "Haftalık Fark",
    cumulative: "Birikimli Fark",
    total: "Toplam",
    comparedWeeks: (compared, recorded) => `Karşılaştırılan Hafta: ${compared}/${recorded}`,
    overviewNote:
      "Haftalar burada sırayla birikir. Ayrıntılar için bir haftayı seçebilirsin. Kullanıcı puanı, FPL'de oynadığı gerçek kadronun sonucudur; tüm puanlar transfer cezası sonrasıdır.",
    totalNote:
      "Fark = sistem tavsiyesi − kullanıcının gerçek sonucu. Toplamlar ve birikimli fark yalnız iki sonucu da kesinleşmiş haftaları içerir. Eksik haftalar iki toplamın da dışında tutulur, sıfır sayılmaz.",
    actualNotRecorded: "Kullanıcı Sonucu Kayıtlı Değil",
    back: "Üyeye Dön",
    week: "Kayıtlı Hafta",
    gameweek: (week) => `Oyun Haftası ${week}`,
    scope: "Lig 352490 · Deadline öncesinde kaydedilmiş son bir haftalık saf puan önerisi.",
    method:
      "Kayıtlı kadroyu kesinleşmiş oyuncu sonuçları, kaptan ve otomatik yedek kurallarıyla puanlıyoruz. Geçmiş önerileri yeniden hesaplatmıyoruz. Puan farkı bir karşılaştırmadır; öneriyi uyguladığınızı veya bu puanı kazanacağınızı kanıtlamaz.",
    empty: "Kayıt Yok",
    emptyBody: "Bu üye için geçmiş öneri kaydı bulunmuyor. Eksik haftaları sonradan üretmiyoruz.",
    unreadable: "Geçmiş Doğrulanamadı",
    retry: "Yeniden Dene",
    unsettled: "Sonuç Kesinleşmedi",
    unavailable: "Karşılaştırma Yapılamıyor",
    noEligible: "Deadline öncesinde kaydedilmiş öneri yok.",
    missingOutcomes: "Hafta kesinleşmiş ancak oyuncu sonuçlarının kaydı bulunmuyor.",
    invalid: "Kayıtlı veriler doğrulanmış bir karşılaştırma için yeterli değil.",
    pending: "Hafta tamamlanıp sonuçlar kontrol edilene kadar puanlar gösterilmez.",
    suggested: "Önerilen Kadro",
    actual: "Üyenin Gerçek Sonucu",
    gross: "Brüt Puan",
    hits: "Transfer Cezası",
    net: "Net Puan",
    difference: "Önerinin Neti − Üyenin Neti",
    actualMissing:
      "Üyenin kesinleşmiş puanı veya transfer cezası kayıtlı değil; puan farkı bilinmiyor.",
    expectation: "Kayıtlı İlk 11 + Kaptan Beklentisi",
    expectationNote: "Transfer cezası ve ek çip puanları öncesidir; net puan tahmini değildir.",
    captainBonus: "Kaptan Ek Puanı",
    autosubs: "Otomatik Giren Yedeklerin Puanı",
    chip: "Çip",
    players: "Önerilen Oyuncular",
    player: "Oyuncu",
    role: "Kayıtlı Rol",
    starter: "İlk 11",
    bench: "Yedek",
    captain: "Kaptan",
    vice: "Yardımcı Kaptan",
    forecast: "Beklenen",
    realized: "Gerçekleşen",
    error: "Gerçekleşen − Beklenen",
    minutes: "Dakika",
    playerNote:
      "Beklenen ve gerçekleşen değerler oyuncunun çarpansız puanıdır. Uygulanan çarpan kaptan etiketinde gösterilir.",
    evidence: "Kayıt Ayrıntıları",
    published: "Kayıtlı Yayın",
    deadline: "Deadline",
    captured: "Öneri Verisinin Alındığı An",
    settledAt: "Sonuçların Alındığı An",
    outcomeAsOf: "Sonuç Verisinin Tarihi",
    adviceId: "Öneri Veri Kaydı",
    outcomeId: "Sonuç Veri Kaydı",
    digest: "Öneri Özeti (SHA-256)",
    noChip: "Yok",
    wildcard: "Wildcard",
    freehit: "Free Hit",
    bboost: "Bench Boost",
    triple: "Triple Captain",
  },
  common: {
    loading: "Yükleniyor…",
    gameweek: (gameweek) => `Oyun haftası ${gameweek}`,
    gameweekShort: (gameweek) => `OH${gameweek}`,
    noDecisionForGameweek: "Bu oyun haftası için karar yok.",
    noDecisionRecorded: "Henüz kaydedilmiş karar yok.",
    closed: "KAPANDI",
    dayShort: "g",
    none: "Yok.",
    rawJson: "Ham JSON",
  },
  shell: {
    skip: "İçeriğe geç",
    tagline: "bir karar ve dayandığı kanıt",
    primary: "Ana navigasyon",
    squad: "Kadro",
    moves: "Önerilen Hamleler",
    rivals: "Rakipler",
    league: "Lig",
    analysis: "Analiz",
    footer: "Herkese açık lig kayıtları, yayımlanan planlar ve analizler.",
    operations: "Operasyon Durumu",
    notFound: "Burada bir sayfa yok.",
    metaDescription: "SquadOpt: haftalık FPL kararı ve dayandığı kanıt.",
  },
  language: { label: "Dil", tr: "Türkçe", en: "English" },
  theme: {
    label: "Tema",
    light: "Açık",
    dark: "Koyu",
    switchTo: (current, next) => `Tema: ${current}. ${next} temaya geç.`,
  },
  squad: {
    loading: "Son karar yükleniyor…",
    dataError: "Site verisi okunamadı.",
    noDecisionBody:
      "İlk oyun haftası son tarihten yaklaşık iki saat önce kararlaştırılır; ledger kaydı oluşunca bu sayfa dolar.",
    decisionError: "Bu karar gösterilemedi.",
    openingSquad: "Açılış Kadrosu",
    transferDecision: "Transfer Kararı",
    why: "Bu Oyuncular Neden Seçildi →",
    deadline: "Son Tarih",
    deadlineIn: "Son Tarihe",
    projectedScore: "Tahmini Puan",
    settledTitle: "Projeksiyon ve Gerçekleşen",
    liveTitle: "Son Kaydedilen Geçici Puan",
    liveProvisional: "Geçici",
    liveStale: "Eski capture · 1 saati aştı",
    liveUnavailable: "Puan mevcut değil",
    liveUnavailableNote:
      "Bu karar için doğrulanmış canlı puan mevcut değil. Eksik veri sıfır puan değildir.",
    liveMissing: "Bu hafta için canlı puan verisi bulunamadı.",
    liveMismatch: "Puan verisi seçili karar veya haftayla uyuşmuyor.",
    liveUnverified: "Puan verisi eksik veya doğrulanamadı.",
    liveNamed: "Seçilen XI + chip",
    liveNet: "Geçici net puan",
    liveHit: (hit: string) => `${hit} transfer cezası bir kez düşüldü`,
    liveRule: "Kaptan/chip dahil; otomatik değişiklik ve yardımcı kaptana geçiş uygulanmaz.",
    liveFixtures: "Tamamlanan maç",
    liveBonusConfirmed: "Kaynakta bonus onaylandı",
    liveBonusPending: "Bonus henüz onaylanmadı; puan değişebilir",
    liveCaptured: "Capture zamanı",
    liveSnapshotNote:
      "Son bilinen capture gösterilir; kesintisiz canlı akış değildir. Bu sayı otomatik değişiklik sonrası resmi FPL toplamı değildir.",
    settledAside: "Sonuçlandı",
    settledProjected: "Tahmin",
    settledRealizedLabel: "Gerçekleşen",
    settledNet: "Net",
    settledNetNote: "Transfer Cezasından Sonra",
    settledNote:
      "Sonuçlanan oyuncu alanları mevcut olduğunda kartlar yayımlanan event puanını ve kaptana uygulanan çarpanı gösterir.",
    seasonTitle: "Sezon Durumu",
    seasonNet: "Sezon (Net)",
    seasonNetNote: (weeks, hits) => `${weeks} Hafta · ${hits} Ceza Puanı`,
    seasonLatestWeek: "Son Tamamlanan Hafta",
    seasonLatestWeekNote: (gameweek, projected) => `${gameweek} · Tahmin ${projected}`,
    seasonVsProjection: "Projeksiyona Karşı",
    seasonVsProjectionNote: "Sonuçlanan Haftalarda Gerçekleşen Eksi Tahmin",
    projectedPlayerPoints: (pointsValue) => `xP ${pointsValue}`,
    realizedPlayerPoints: (pointsValue) => `Gerçekleşen ${pointsValue}`,
    eventPointsUnavailable: "Event Puanı Bekleniyor",
    playerPointDifference: (difference) => `Fark ${difference}`,
    pointDifferenceUnavailable: "Fark Bekleniyor",
    captainMultiplier: (multiplier) => `×${multiplier} C`,
    squadCost: "Kadro Maliyeti",
    squadSellValue: "Kadro Satış Değeri",
    bankAndFt: (bank, transfers) => `Banka ${bank} · ${transfers} Serbest Transfer Kaldı`,
    budget: "Bütçe £100.0m",
    solver: "Çözücü",
    provedOptimal: "Optimal Olduğu Kanıtlandı, Tek İş Parçacığı",
    notProved: "Kanıtlanmadı — Raporlandı, Öneri Değil",
    startingXi: "İlk 11",
    starterCount: (count) => `${count} İlk 11 Oyuncusu · Kaptan İki Kez Sayılır`,
    captain: "Kaptan",
    noCaptain: "Kaptan ilk 11 içinde değil.",
    bench: "Yedekler",
    substitutionOrder: "Oyuna Giriş Sırasıyla",
    limitsTitle: "Bu sayılar neyi söylemiyor",
    risk: "Risk",
    riskStatus: {
      available: "Kullanılabilir",
      unavailable: "Kullanılamıyor",
      not_requested: "İstenmedi",
    },
    scenarioMean: "Senaryo Ortalaması",
    shiftedForOptimism: (pointsValue) => `Seçim İyimserliği İçin ${pointsValue} Kaydırıldı`,
    scenarioCount: (count) => `${count} Senaryo`,
    rivalComparisons: "Rakip Karşılaştırmaları →",
    captured: "Yakalandı",
    recordIdentity: "Kayıt Kimliği",
    projection: "Projeksiyon",
    generated: "Sayfa Üretimi",
    settledRealized: (pointsValue) => `Sonuçlandı: ${pointsValue} Gerçekleşen`,
    pitchLabel: "Pozisyona göre ilk on bir",
    captainLabel: "kaptan",
  },
  moves: {
    loading: "Önerilen hamleler yükleniyor…",
    error: "Hamleler gösterilemedi.",
    noDecisionBody: "Bir oyun haftası kararlaştırılınca hamleler burada görünür.",
    deadline: "son tarih",
    title: "Önerilen Hamleler",
    chip: "çip",
    openingTitle: "Açılış kadrosu — yapılacak transfer yok.",
    openingBeforeLink:
      "İlk oyun haftasında kadro sıfırdan kurulur; bu yüzden yapılacak transfer yoktur. İlk wildcard ve diğer çipler ikinci oyun haftasında açılır. Bu noktadan sonra planlayıcının transfer önerileri, puan maliyetleri, banka ve serbest transfer durumu burada görünür. Oluşturulan ",
    openingLink: "kadroya bakın",
    transfers: "transferler",
    transferNote: (paid, pointsValue) => `${paid} ücretli · ${pointsValue} puan kesildi`,
    freeTransfers: "serbest transferler",
    freeTransferNote: (cap, cost) =>
      `üst sınır ${cap}; planlayıcı transfer cezasını ${cost} olarak fiyatladı`,
    bank: "banka",
    bankNote: (before, value) => `${before} değerinden · kadro değeri ${value}`,
    out: "Giden",
    in: "Gelen",
    leaving: (count) => `${count} oyuncu gidiyor`,
    arriving: (count) => `${count} oyuncu geliyor`,
    restsOn: "Bu öneri neye dayanıyor",
    restsOnItems: [
      "Planlayıcı, kendisine verilen projeksiyonu ufuk boyunca maksimize eder; bir transfer ancak ilgili oyuncular hakkındaki projeksiyon doğruysa değerlidir.",
      "Fiyatlar capture anındandır: giden oyuncular satış fiyatıyla, gelen oyuncular gösterilen güncel fiyatla değerlendirilir.",
      "Çipler yalnız yayımlanmış pencerelerinde sunulur; gösterilmeyen bir çip ya kullanılamıyordur ya da saklamaktan daha değersizdir.",
    ],
    plannerContract: (status) => `Karar anında planlayıcı sözleşmesi: ${status}.`,
  },
  decision: {
    title: "Karar Görünümü",
    shareable: "URL'de paylaşılabilir",
    intro:
      "Pencere ve oyun modu, öneriyi hangi açıdan okumak istediğinizi kaydeder. Bu ekran mevcut ledger kararını gösterir; seçimi değiştirmek henüz yeni bir optimizasyon çalıştırmaz.",
    horizon: "Planlama Penceresi",
    week: (count) => `${count} hafta`,
    liveControl: "canlı kontrol",
    researchShadow: "araştırma gölgesi",
    liveControlTitle: "H1 mevcut kararı belirler.",
    liveControlBody: "Yalnız bir haftalık kontrol canlı öneri olmaya uygundur.",
    liveEvidenceBody:
      "Toplu koşudaki H1, dondurulmuş ledger kararını aynen üretti; karar otoritesi ledger'dır.",
    researchShadowTitle: (weeks) => `H${weeks} gölge kanıt için ayrılmıştır.`,
    researchShadowBody:
      "Sonuç toplu koşudan sonra oluşur; tahmin ve çözücü kapılarını geçene kadar canlı önerinin yerini alamaz.",
    shadowEvidenceBody: (status, proof) =>
      `Toplu koşu bu gölgeyi hesapladı (${status}; çözücü kanıtı: ${proof}). Bu kanıttır, canlı öneri değildir.`,
    mode: "Oyun Modu",
    leagueId: "Lig Numarası",
    leaguePlaceholder: "Lig numarası ya da FPL bağlantısı",
    leagueHelp: "Kayıtlı lig için önceden hesaplanır; üyeler sayfasını açar.",
    leagueConnect: "Bağlan",
    leagueInvalid: "Bir lig numarası ya da FPL lig bağlantısı gir.",
    leagueUnavailable: "Lig üyesi verisi henüz yayınlanmadı; bir sonraki karar yayınıyla gelir.",
    leagueMismatch: (leagueId) =>
      `Bu site yalnızca ${leagueId} numaralı ligi hesaplar; açabildiği lig o.`,
    diagnostic: "diagnostik",
    diagnosticTitle: (weeks) =>
      `Lig-içi ${weeks} haftalık sonuç bir teşhis göstergesidir; kazanma ihtimali değildir.`,
    diagnosticBody:
      "Senaryolar kalabalığın ölçülen +7,19 puan/hafta üstünlüğünü yalnız kısmen fiyatlıyor; bu nedenle rekabetçi pencere yalnız yön gösterir.",
    sourceBefore: "Fiyat etiketleri ",
    sourceAfter: (folds) =>
      ` ölçümünün 0 puan bütçe hücresinden, sentetik risk-neutral rakibe karşı ${folds} fold üzerinden gelir.`,
    modes: {
      pure: "Saf Puan",
      pureDescription: "Rakipten bağımsız en yüksek beklenen puanı hedefler.",
      purePrice: "Rakip bütçesi yok, ölçülmüş maliyet yok",
      safe: "Garantici",
      safeDescription:
        "Rakiple eşit bitirmeyi başarı sayar; fiyatı, beklenen puan üzerinden ölçülen maliyetidir.",
      aggressive: "Agresif",
      aggressiveDescription: "Rakibin önüne geçmeye odaklanan dengeli rekabet modu.",
      extreme: "Aşırı Agresif",
      extremeDescription: "Beş puandan büyük fark yaratabilecek daha sert kararları arar.",
      cost: "maliyet",
      points: "puan",
    },
  },
  rivals: {
    loading: "Projeksiyonlar yükleniyor…",
    error: "Analiz gösterilemedi.",
    nothingTitle: "Henüz karşılaştırılacak bir şey yok.",
    nothingBody:
      "Bir oyun haftası kararlaştırılınca projeksiyonlar ve rakip karşılaştırmaları görünür.",
    kicker: (season, gameweek, pool) =>
      `${season} · oyun haftası ${gameweek} · ${pool} oyunculuk havuz`,
    title: "Rakip Analizi",
    lede: "Bu sayfa iki soruyu yanıtlar: başka kimler seçilebilirdi ve seçilen kadro aynı senaryolarda rakibe karşı nasıl görünüyor?",
    projections: "Projeksiyonlar",
    projectionsBody:
      "Her pozisyondaki havuzun üst sıraları tahmini puana göre listelenir ve dondurulmuş kadro işaretlenir. Daha yüksek projeksiyonlu seçilmemiş bir oyuncu bütçe, takım başına üç oyuncu sınırı veya diziliş nedeniyle dışarıda kalmıştır.",
    topPool: (count) => `havuzun ilk ${count} oyuncusu`,
    projectedPool: (position) => `Projeksiyon havuzu, ${position}`,
    player: "oyuncu",
    price: "fiyat",
    inSquad: "kadroda",
    bench: "yedek",
    provenance: "Kaynak Bilgisi",
    capture: "capture",
    model: "model",
    features: "özellikler",
    unavailable: "havuzda kullanılamayan",
    against: "Rakiplere Karşı",
    noRivalTitle: "Bu karara karşı puanlanmış bir rakip yok.",
    noRivalBeforeStatus:
      "Rakip karşılaştırması için bu haftada eksik iki şey var: risk görünümü değerlendirilmiş bir karar (bu kararın durumu ",
    noRivalAfterStatus:
      ") ve aynı senaryolarda puanlanacak bir rakip kadro. Şablon rakip capture sahipliğinden, mini lig rakipleri entry verisinden bağlanacak. O zamana kadar ölçülmemiş bir olasılık yerine aşağıdaki projeksiyonlar gösterilir.",
    linksBefore: "Kadronun nasıl oluştuğu ",
    squadPage: "kadro sayfasında",
    linksMiddle: "; sezonun diğer oyuncularla karşılaştırması ",
    leaguePage: "lig sayfasında",
  },
  league: {
    loading: "Sezon yükleniyor…",
    ledgerError: "Ledger okunamadı.",
    noSeason: "Henüz sezon yok.",
    season: "sezon",
    title: "Lig Analizi",
    lede: "Bu sezonun nasıl ilerlediği ve aynı oyunu oynayan herkesle karşılaştırması.",
    decidedSettled: "kararlaştırılan · sonuçlanan",
    decidedSettledNote: "dondurulmuş kararı olan · sonucu olan oyun haftaları",
    realizedProjected: "gerçekleşen ve tahmin",
    realizedWeeks: (pointsValue) => `sonuçlanan haftalarda ${pointsValue} gerçekleşen puan`,
    shownWhenSettled: "bir oyun haftası sonuçlanınca gösterilir",
    hitsChips: "cezalar · çipler",
    noChip: "henüz çip oynanmadı",
    cumulative: "Tahmin ve gerçekleşen, kümülatif",
    points: "puan",
    fromGw2: "ikinci oyun haftasından itibaren",
    onePoint:
      "Tek oyun haftası bir noktadır, çizgi değildir. Grafik ikinci karar oluşunca; gerçekleşen çizgisi ilk hafta sonuçlanınca başlar.",
    againstLeague: "Kaydedilen kadro ve FPL ortalaması",
    comparisonMissing:
      "Karşılaştırma, kararın kullandığı capture üzerinden kurulur. Bu site build'i capture içermediği için lig hakkında bir iddia gösterilmiyor.",
    firstRow: "İlk satır, birinci oyun haftası kararlaştırılınca görünür.",
    ourSeason: "Sezonumuz",
    ledgerAside: "her satır dondurulmuş ve checksum alınmış bir ledger kaydıdır",
    ledgerCaption: "Oyun haftası başına bir satırla sezon ledger'ı",
    decision: "karar",
    projected: "tahmin",
    realized: "gerçekleşen",
    error: "hata",
    hits: "ceza",
    chip: "çip",
    state: "durum",
    note: "SquadOpt’un kaydedilen kadro neti kaptan/çip ve transfer cezasını içerir; otomatik değişiklik ve kaptan yedeği uygulanmaz. Resmi FPL puanlarıyla birebir karşılaştırılamaz.",
    modeNote:
      "Her satır hangi modda kaydedildiğini söyler — live: o son tarihten önce, o koşunun kendi aldığı capture'dan kararlaştırıldı; replay: o son tarihten sonra kaydedildi ya da koşunun kendisinin almadığı, adıyla verilen bir capture'dan kararlaştırıldı. Modu olmayan bir satır, ledger mod damgalamaya başlamadan önce kaydedilmiştir.",
    chartReplays: (count) =>
      `Burada çizilen oyun haftalarının ${count} tanesi live değil replay olarak kaydedildi; hangileri olduğunu aşağıdaki tablo söylüyor.`,
    weeklySummary: (snapshot) => `oyunun haftalık özeti · capture ${snapshot.slice(0, 24)}…`,
    chartStarts:
      "Grafik ilk puanlanan oyun haftasıyla başlar. Oyun ortalamayı hafta bittikten sonra yayımladığı için henüz çizilecek veri yok.",
    templateTitle: "Bu kadronun ne kadarı şablon",
    gameweekAside: (gameweek) => `oyun haftası ${gameweek}`,
    meanOwnership: "ortalama ilk 11 sahipliği",
    meanOwnershipNote: "ilk 11 oyuncularımızdan birine sahip olan saha payının ortalaması",
    effectiveOwnership: "etkin sahiplik",
    effectiveOwnershipNote: "ilk 11 ve kaptan tekrar — sahayla paylaştığımız maruziyet",
    differentials: "diferansiyeller",
    differentialNote: (threshold) => `%${threshold} veya daha az sahiplikli ilk 11 oyuncuları`,
    mostOwned: "En Yüksek Sahiplik",
    leastOwned: "en düşük sahiplik",
    ownershipNote:
      "Sahiplik, karar anındaki capture'ın selected_by_percent değeridir; son tarihten sonra değişir ve bu sayfa onu takip etmez.",
    openingSquad: "Açılış Kadrosu",
    transferCount: (count) => `${count} transfer`,
    deadline: "son tarih",
    settled: "sonuçlandı",
    decided: "kararlaştırıldı",
    cumulativeLabel: (projected) =>
      `Oyun haftasına göre kümülatif tahmin (${projected}) ve gerçekleşen puan`,
    projectedCumulative: "tahmin, kümülatif",
    realizedCumulative: "gerçekleşen, kümülatif",
    afterSettle: " (ilk sonuçtan sonra)",
    averageLabel: (count) =>
      `${count} puanlanmış haftada kaydedilen kadro neti ve resmi FPL ortalaması`,
    ourNet: "kaydedilen kadro neti",
    gameAverage: "resmi FPL ortalaması",
    lastWeek: (pointsValue) => `son puanlanan hafta farkı: ${pointsValue}`,
  },
  scoreboardComparisons: {
    title: "Haftalık karşılaştırma ve hata ayrıştırması",
    week: "GW",
    name: "Karar",
    net: "Puan",
    zero: "Sıfır dakikalı ilk 11",
    minutes: "Dakika açığı",
    captain: "Kaptan açığı",
    autosub: "Otomatik değişiklik getirisi",
    missing:
      "- ölçülmedi demektir. Dakika açığı oynayan ilk 11 oyuncularını kapsar; negatif değer tahminden fazla dakika oynandığını gösterir. Kaptan açığı, beklenen ile gerçekleşen ek puan farkıdır.",
    legacy: "Adı konan ilk 11; otomatik değişiklik ve ikinci kaptan getirisi bilinmiyor",
    synthetic: "Açılış bütçesiyle kurallara uygun yeniden kurulan kadro; transfer geçmişi yok",
    game: "Oyunun yayımladığı ortalama",
    official: "Resmi değişiklik ve kaptan puanlaması",
    absent: "Karar kaydı yok",
    pending: "Yerleşmiş sonuç bekleniyor",
    names: {
      system: "Sistem",
      base: "Çıplak bileşen",
      elite_xi: "Önceki haftanın elit XI'i",
      ownership_template: "Sahiplik şablonu",
      league_mean: "Lig ortalaması, net",
      game_mean: "Oyun ortalaması",
    },
  },
  leagueScoreboard: {
    title: "Haftalık skor tablosu",
    aside: (snapshot) => `capture ${snapshot.slice(0, 24)}…`,
    loading: "Skor tablosu yükleniyor…",
    notPublished:
      "Skor tablosu henüz yayımlanmadı. Onu yazan ilk haftalık çalıştırmadan sonra görünür.",
    notAvailable: "Skor tablosu okunamadı.",
    caption:
      "Biten her oyun haftası için: kâğıt ledger'ımız, lig üyelerinin ortalama neti, Top-100 ortalaması, FPL ortalaması ve en yüksek puan",
    gameweek: "OH",
    ours: "SquadOpt · yazılan on bir",
    members: "lig üyeleri · ortalama net",
    membersCounted: (count) => `${count} üye`,
    top100: "Top-100 · ortalama",
    top100NotFinal: "kesin değil",
    top100Net: "cezalar düşülmüş",
    top100Gross: "cezalar düşülmemiş",
    average: "FPL ortalaması",
    highest: "en yüksek",
    notSettled: "kararlaştırıldı, sonuçlanmadı",
    provisional: "geçici",
    noGameweek: "Bu capture'da henüz biten oyun haftası yok.",
    cumulative: (gameweek) => `OH${gameweek} sonuna kadar kümülatif`,
    oursCovers: (gameweeks) => `yalnız OH ${gameweeks}`,
    oursNone: "sonuçlanmış hafta yok",
    membersTotal: (count) => `${count} üyenin ortalama toplamı`,
    membersCovers: (gameweeks) => `OH ${gameweeks} kapsıyor`,
    paperLedger:
      "Kadromuz kâğıt üstünde izlenen bir kadrodur. Karşılaştırma tablosu her satırın puanlama temelini gösterir. Eski kararlarda dondurulmuş bench sırası ve yardımcı kaptan olmadığı için yalnızca adı konan ilk 11 puanlanır. Yeni kararlar ikisini de kaydeder ve resmi otomatik değişikliklerle puanlanabilir. Bir üyenin neti, kendi geçmişinden okunan hafta puanı eksi transfer cezasıdır.",
    grossNote:
      "Bu capture'daki Top-100 ortalaması transfer cezaları düşülmeden hesaplanmıştır: kohortun kendi sıralama tablosundaki haftalık toplamdır ve cezalar çıkarılmamıştır; yanındaki net sütunlarla aynı ölçüde değildir, ikisi karşılaştırılamaz. Ancak haftanın elite-picks capture'ı yüz üyenin hepsini kapsadığında netlenir.",
    provisionalNote:
      "Geçici işaretli bir oyun haftası bitmiştir ama bu capture'da veri denetimi tamamlanmamıştır: bonus puanlar maç maç işlendiği için puanları hâlâ değişebilir.",
    modeNote:
      "live: son tarihten önce, o koşunun kendi aldığı capture'dan kararlaştırıldı. replay: son tarihten sonra kaydedildi ya da koşunun kendisinin almadığı, adıyla verilen bir capture'dan kararlaştırıldı.",
  },
  leagueEntry: {
    title: "Ligini bul",
    label: "Lig numarası",
    hint: "Devam etmek için lig numaranı yaz.",
    submit: "Ligi bul",
    invalid: "Pozitif tam sayı olan bir lig numarası gir.",
    loading: "Yayımlanan lig okunuyor…",
    unsupported: "Şimdilik yalnız 352490 numaralı lig destekleniyor.",
    missing: "Yayımlanmış lig belgesi şu anda mevcut değil. Daha sonra yeniden dene.",
    failed: "Yayımlanan lig verisi okunamadı. Yeniden dene.",
  },
  memberResources: {
    transfersTitle: "Ücretsiz transfer hakkı",
    unknown: "Bilinmiyor",
    chipsTitle: "Chipler",
    chipsMissing: "Chip bilgisi yok",
    asOf: (week) => `GW${week} öncesi`,
    halves: { first_half: "İlk yarı", second_half: "İkinci yarı" },
    window: (start, stop) => `GW${start} ile GW${stop}`,
    used: (week) => `GW${week}'te kullanıldı`,
    noWindow: "Yayımlanmış pencere yok",
    states: {
      available: "Kullanılabilir",
      used: "Kullanıldı",
      expired: "Süresi doldu",
      not_yet: "Henüz açılmadı",
      unknown: "Bilinmiyor",
    },
  },
  leagueMembers: {
    computeTitle: "Bu planı hesapla",
    computeBodySelf: "Bu planı kendi kadrondan hesaplat.",
    computeBodyOther:
      "Başka bir üyeye bakıyorsun. Hesap bu üyenin herkese açık kadrosundan başlar.",
    computeRivalNearest: "Sıralamada hemen üstündeki",
    computeButton: "Hesapla",
    computeRequesting: "İstek gönderiliyor…",
    computeQueued: "Kuyrukta",
    computeRunning: "Hesaplanıyor",
    computeWaiting: "Hesap bitince cevap burada görünecek.",
    computeWaitingWithFallback: "Hesap sürerken aşağıda daha önce yayınlanmış plan gösteriliyor.",
    computeDone: "Plan hazır",
    computePublished: "Yayınlanmış plan",
    computeUnsupportedSelection:
      "Hesapla saf puanı bir, üç ve beş haftada, rakip seçilmiş bir stratejiyi ise bir haftada destekler. Rakip stratejisi daha uzun pencerede hesaplanmaz.",
    computeProvenance: (capture: string, at: string) => `Capture ${capture}, sonuç tarihi ${at}.`,
    computeStaticFallback: "Backend'e ulaşılamadı; bu, yayınlanmış statik cevap.",
    computeUnavailable: "Şu an yalnız yayınlanmış site var; bu kombinasyon yayınlanmamış.",
    computeFailed: "Hesap tamamlanamadı. Yayınlanmış plan, varsa, geçerli olmaya devam ediyor.",
    adviceComputedBadge: "Hesap sonucu",
    advicePublishedWhileComputing: "Hesap sürerken yayınlanmış plan gösteriliyor.",
    adviceBaselineWhileComputing:
      "Bu, yayınlanmış saf puan / 1 hafta planı; istenen kombinasyon hâlâ hesaplanıyor.",
    adviceRequestHint: "Yukarıdaki Hesapla ile isteyebilirsin.",
    viewerTitle: "Hangisi sensin?",
    viewerBody:
      "Kendi satırını seç ki tavsiye kendi kadrondan hesaplansın. Siteyi yeniden açtığında veya yenilediğinde tekrar seçim yapmalısın. Bu bir beyandır, giriş değil: herkes herkesi seçebilir ve bu sorun değil, çünkü burada gösterilen her şey son tarihten sonra zaten herkese açık.",
    viewerSelect: "Bu benim",
    viewerYouBadge: "Sen",
    viewerSelected: (name: string) =>
      `${name} olarak bakıyorsun. Tavsiye sayfaları bu kadrodan başlayacak.`,
    viewerClear: "Seçimi Kaldır",
    viewerChange: "Üyeyi Değiştir",
    viewerMissing:
      "Kayıtlı seçimin yayımlanan üye listesinde yok. Başka bir üye seç veya seçimi kaldır.",
    viewerOpenMine: "Kadromu aç →",
    notYourPageTitle: "Bu senin sayfan değil",
    notYourPageBody: "Kendin olarak başka bir satırı seçtin; bu sayfa bu üyeye öneri verir.",
    notYourPageLink: "Kendi sayfama git →",
    strategyTitle: "Oyunun",
    strategyIntro:
      "Aşağıdaki her seçenek senin kadrondan çözüldü; rakip stratejisi karşısında oynadığın üyeyi adlandırır.",
    strategyLegend: "Strateji",
    strategies: {
      "saf-puan": {
        name: "Saf puan",
        description:
          "Yalnız puan; denklemde rakip yok. Plan, ilk on bir, kaptan ve yedek kulübesi birlikte değerlendirilerek seçilir; bu yüzden başka bir seçenek ilk on bir ve kaptan için daha yüksek beklenen puan gösterebilir.",
      },
      "ortak-koru": {
        name: "Ortak çekirdeği koru",
        description:
          "Önerilen 15 oyuncun ile rakibin ilk 11'i arasında en az 9 ortak oyuncu ister. Ücretsiz transfer sınırına uymak için bu alt sınır düşürülebilir; yayımlanan plan uygulanan sınırı belirtir.",
      },
      "fark-yarat": {
        name: "Fark yarat",
        description:
          "Önerilen 15 oyuncun ile rakibin ilk 11'i arasında en fazla 5 ortak oyuncu ister. Ücretsiz transfer sınırına uymak için bu üst sınır yükseltilebilir; yayımlanan plan uygulanan sınırı belirtir.",
      },
    },
    rulePickBadge: "Kuralın seçimi",
    rulePickNote: (rival: string, gap: string, weeks: number) =>
      `Tanımlı bir kural, iki sayıya bakarak seçeneklerden birini işaretler: ${rival} karşısındaki lig puanın (${gap}) ve oynanacak ${weeks} hafta. Kural yazılı, ölçülmüş değil — uymanın uymamaktan daha iyi olduğu test edilmedi — yani bir seçeneği etiketler, senin yerine seçmez.`,
    publicationStates: {
      "published-missing": {
        title: "Listelenen öneri dosyası bulunamadı.",
        body: "İndeks bu planı listeliyor, fakat belgesi bulunamıyor. Bu durum, planın çözülemediği anlamına gelmez.",
      },
      "context-mismatch": {
        title: "Dönen öneri bu görünümle eşleşmiyor.",
        body: "Üye, seçim, hafta veya veri kaydı farklı. Eşleşmeyen plan gösterilmez; mevcut kadro görünür kalır.",
      },
      "index-missing": {
        title: "Bu üyenin öneri indeksi yayımlanmamış.",
        body: "Strateji, pencere ve rakip seçimi için yayımlanan indeks gerekli.",
      },
      "index-error": {
        title: "Bu üyenin öneri indeksi okunamadı.",
        body: "Mevcut kadro görünür kalır. İndeks okunana kadar öneri istekleri durdurulur.",
      },
      "not-listed": {
        title: "Bu seçim bu yayında listelenmiyor.",
        body: "Bu üyenin indeksinde yayımlanan bir strateji, pencere ve rakip seç.",
      },
      "declared-unavailable": {
        title: "Yayıncı bu seçim için plan üretemedi.",
        body: "Yayıncı, bu seçim için kullanılabilir bir plan olmadığını bildirdi.",
      },
    },
    rivalPlayersTitle: "Ortak ve farklı oyuncular",
    rivalPlayersBasis:
      "Adlar, aynı veri kesitindeki oyuncu kimlikleriyle önerilen 15'i (ilk 11 ve yedekler) rakibin yayımlanan ilk 11'iyle karşılaştırır. Sıralama veya yeni puan tahmini değildir. Yayımlanan beklenen fark, iki ilk 11'i kaptanlarla karşılaştırır ve bu planın transfer cezasını çıkarır.",
    rivalPlayerGroups: {
      shared: "Ortak: önerilen 15 ve rakibin ilk 11'i",
      recommendedOnly: "Yalnız önerilen 15'te",
      rivalOnly: "Yalnız rakibin ilk 11'inde",
    },
    rivalPlayersNone: "Yok",
    rivalPlayersUnavailable:
      "Oyuncu adları karşılaştırılamıyor: lig, sezon, oyun haftası ve veri kesiti eşleşmeli; oyuncu listeleri tam olmalı.",
    rivalLegend: "Rakip",
    rivalLabel: "Karşısında oynadığın üye",
    rivalChoose: "Bir rakip seç",
    rivalDefaultSuffix: "(sıralamada hemen üstün)",
    rivalUnavailableSuffix: "(hesaplanamadı)",
    rivalNone: "Bu hafta için başka bir üyenin kadrosu yayınlanmamış.",
    rivalNoDefault:
      "Bu yayın senin için sıralamada bir komşu belirlemedi, o yüzden yerine bir rakip seçilmiyor: birini seç, ona karşı plan hesaplanabilsin.",
    rivalNote: "Rakibin açık on biri bir kısıt ve bir karşılaştırmadır, başka bir şey değil.",
    windowLegend: "Pencere",
    windowNotComputed:
      "Bu seçim için yalnız bir haftalık plan var: üç ve beş haftalık planlar yalnız saf puan için ve yalnız bu yayının çözdüğü yerde var; rakip stratejisi hafta hafta oynanır.",
    windowLimits:
      "Üç ya da beş haftalık plan 1. hafta projeksiyonunu fikstür takvimi üzerinde tekrarlar, haftada bir transferle; varsaydığı sınırlarla yayınlanır ve sonraki haftaların tahmini değildir.",
    windowFellBack: (asked, shown) =>
      `${asked} haftalık pencere bu strateji için yayınlanmadı; bu seçim ${shown} haftalık plandır.`,
    windowTitle: (weeks) => `${weeks} haftalık pencere`,
    windowRule:
      "Yukarıdaki hamleler ve kadro ilk haftanın. Aşağıdaki her satır planın bir oyun haftası; beklenen puan, burada yazılı sınırlar altında.",
    windowLimitsLabel: "Bu pencerenin varsaydıkları",
    windowWeek: "Hafta",
    windowWeekOf: (gameweek) => `OH${gameweek}`,
    windowHits: "Transfer cezası",
    windowPoints: "Beklenen puan",
    // Only exact published limit keys receive these reviewed explanations.
    statedLimitUnknown: "Yayımlanan bu pencere varsayımı için çevrilmiş bir açıklama bulunmuyor.",
    statedLimits: {
      "The first week's projection is repeated over the later weeks, rescaled by each club's fixture count in that week relative to its count in the first week, from the captured calendar; a club with no fixture in the first week stays at zero all the way through, and the later weeks are not projected separately.":
        "İlk haftanın projeksiyonu sonraki haftalarda tekrarlanır; her kulüp için veri kesitindeki takvimde o haftanın maç sayısı, ilk haftanın maç sayısına oranlanarak ölçeklenir. İlk haftada maçı olmayan bir kulüp pencere boyunca sıfırda kalır ve sonraki haftalar ayrıca projekte edilmez.",
      "Availability is applied once, from the capture: injuries, rotation and suspensions after it are not seen.":
        "Oynayabilirlik bir kez, veri kesitinden uygulanır: sonrasındaki sakatlıklar, rotasyon ve cezalar görülmez.",
      "Every week inside the window, the first included, is capped at one transfer (a wildcard week excepted); the one-week plan has no such cap.":
        "Pencere içindeki her hafta, ilki dahil, bir transferle sınırlıdır (wildcard haftası hariç); bir haftalık planda böyle bir sınır yoktur.",
      "The Top-100 uplift is inside the first week's numbers, and the repetition carries it into every later week.":
        "Top-100 düzeltmesi ilk haftanın sayılarının içindedir ve tekrar onu sonraki her haftaya taşır.",
      "Prices are held at the captured values; no price change is modelled.":
        "Fiyatlar veri kesitindeki değerlerde tutulur; fiyat değişimi modellenmez.",
      "No chip is offered inside the window. A finite window counts nothing for holding a chip back, so a planner that could reach one would spend it; chip timing is a season-long decision this window cannot price.":
        "Pencere içinde çip önerilmez. Sonlu bir pencere, bir çipi elde tutmaya değer biçmez; ulaşabilse harcardı. Çip zamanlaması sezonluk bir karardır ve bu pencere onu fiyatlayamaz.",
    },
    controlUnprovenBody: (gap: string) =>
      `Bu fiyatın ölçüldüğü saf puan planı en iyi diye kanıtlanamadı (fark ≤ ${gap} puan); bu yüzden fiyat kesin bir değer olarak değil, tavan olarak yayımlanıyor: bu stratejinin mal olabileceği en fazla değer.`,
    overlapLine: (count: number) => `rakibin on birinden ${count} tanesi senin on beşinde`,
    gapLine: (pointsValue: string) => `rakibe karşı beklenen fark ${pointsValue}`,
    captainShared: "aynı kaptan",
    planWithinFree: (cap: number, target: number, applied: number) =>
      `Ücretsiz transfer hakkı ${cap}, transfer cezası yok: istenen ortak oyuncu sınırı ${target}, uygulanan ortak oyuncu sınırı ${applied}.`,
    planWithHits: (cap: number, target: number) =>
      `Transfer cezalarına izin veren plan: ücretsiz transfer hakkı ${cap}, istenen ortak oyuncu sınırı ${target}. Yayımlanan transfer cezaları fiyata dahildir.`,
    alternativeWithHits: (applied: number, hits: string, cost: string) =>
      `Transfer cezalarına izin veren alternatif: uygulanan ortak oyuncu sınırı ${applied}; yayımlanan transfer cezası ${hits} puan, saf puana göre maliyet ${cost} beklenen puan.`,
    alternativeWithinFree: (applied: number, cost: string) =>
      `Ücretsiz transferler içinde kalan alternatif: uygulanan ortak oyuncu sınırı ${applied}; saf puana göre maliyet ${cost} beklenen puan.`,
    alternativeWithHitsAtMost: (applied: number, hits: string, cost: string) =>
      `Transfer cezalarına izin veren alternatif: uygulanan ortak oyuncu sınırı ${applied}; yayımlanan transfer cezası ${hits} puan, saf puana göre maliyet en fazla ${cost} beklenen puan.`,
    alternativeWithinFreeAtMost: (applied: number, cost: string) =>
      `Ücretsiz transferler içinde kalan alternatif: uygulanan ortak oyuncu sınırı ${applied}; saf puana göre maliyet en fazla ${cost} beklenen puan.`,
    templatesTitle: "Oyun şablonları",
    templatesBody:
      "Şablon, adlandırılmış bir strateji-pencere çiftidir. Uygulamak, kontrollerin okuduğu paylaşılabilir seçimi kurar; kendi şablonların bu tarayıcıda durur.",
    templateMeta: (strategy: string, window: number, rival: string) =>
      `${strategy} · ${window}h · ${rival}`,
    templateNamePlaceholder: "Bu kombinasyonu adlandır",
    templateSave: "Seçimi kaydet",
    templateRemove: (name: string) => `${name} şablonunu kaldır`,
    loading: "Lig üyeleri yükleniyor…",
    notAvailable: "Üye listesi yayımlanmamış.",
    notAvailableBody: "Bu sitede okunabilecek yayımlanmış bir üye listesi bulunmuyor.",
    membersUnreadable: "Üye listesi okunamadı.",
    membersUnreadableBody:
      "Yayımlanan belge okunabilir veri döndürmedi. Aynı belgeyi yeniden okumayı deneyebilirsin.",
    membersAuxiliaryUnavailable:
      "Bu üyenin mevcut kadrosu görünür kalır. Üye listesindeki bazı adlar kullanılamayabilir.",
    retryPublishedRead: "Yeniden oku",
    loadingAdvice: "Yayımlanan öneri okunuyor…",
    entryUnreadable: "Bu üyenin kadrosu okunamadı.",
    entryUnreadableBody: "Yayımlanan kadro belgesi okunabilir veri döndürmedi.",
    unprovenPlanGapUnknown:
      "Bu planın en iyi olduğu kanıtlanamadı. En iyi çözüme uzaklık sınırı yayımlanmamış.",
    controlGapUnknown:
      "Saf puan planının en iyi olduğu kanıtlanamadı ve fark sınırı yayımlanmamış. Belirtilen maliyet tavanı bir üst sınırdır.",
    planWithinFreeUnknown: (cap: number, target: number) =>
      `Planın serbest transfer sınırı ${cap}, ortak oyuncu sayısı için istenen sınır ${target}. Uygulanan ortak oyuncu sınırı yayımlanmamış.`,
    hitPointsNotPublished: "yayımlanmayan sayıda",
    noPlanInRecord:
      "Bu kayıt, transfersiz bir öneri olduğunu doğrulayacak kadar plan bilgisi içermiyor.",
    publicationReasons: {
      "The advice rules belong to another capture.":
        "Önerinin girdileri farklı veri kayıtlarına ait.",
      "The advice rules belong to another season.": "Önerinin girdileri farklı sezonlara ait.",
      "A member cannot be their own rival.": "Seçilen üye ve rakip aynı kişi.",
    } as Record<string, string>,
    publicationReasonUnknown:
      "Yayıncı bir neden belirtmiş; bu nedenin çevrilmiş açıklaması bulunmuyor.",
    loadingEntry: "Üyenin kadrosu yükleniyor…",
    adviceNotComputed: "Bu kombinasyon bu yayın için hesaplanmadı.",
    adviceNotComputedBody:
      "Site, kadrondan gerçekten çözdüğü kararları yayınlar: saf puan ve plan bulunan her rakibe karşı her strateji. Planı olmayan bir çift rakip listesinde bunu söyler.",
    adviceUnreadable: "Bu üyenin önerisi okunamadı.",
    adviceUnreadableBody:
      "Yukarıdaki kadro bu yayından geldi, öneri belgesi ise yanıt vermedi; yani bu, kimsenin çözmediği bir kombinasyon değil, siteyi okurken çıkan bir arıza. Sayfayı yenilemek ya da bildirmek doğru olan.",
    freeHitSquadBasis: (week: number) => `Free Hit oynadın; bu öneri GW ${week} kadrona göre.`,
    entryNotAvailable: "Bu üyenin kadro belgesi yayımlanmamış.",
    entryNotAvailableBody: "Üye listesine dönebilir veya sonraki yayında yeniden deneyebilirsin.",
    invalidEntry: "Bu üye numarası geçerli değil.",
    exampleData: "örnek veri",
    systemTeamBadge: "SquadOpt · sistem takımı",
    systemTeamTitle: "SquadOpt da oynuyor",
    leagueNumber: (leagueId) => `lig ${leagueId}`,
    title: "Lig Üyeleri",
    members: "Üyeler",
    memberCount: (count) => `${count} üye`,
    caption: (leagueName) => `${leagueName} üye sıralaması`,
    rank: "sıra",
    member: "üye",
    team: "takım",
    gameweekNetPoints: "OH net puanı",
    gameweekNetPointsFor: (gameweek) => `OH${gameweek} net puanı`,
    gameweekNetNote:
      "Oyun haftası sütunu her satır için nettir: o haftaki transfer cezaları düşüldükten sonraki puan, yani sezon toplamının arttığı miktarın ta kendisi. FPL sitesi haftayı cezalardan önce gösterir; bu yüzden 4 puan ceza alan bir üye burada oradakinden 4 puan düşük görünür. Cezası yayınlanan veride bulunmayan bir satırda, yanlış temeldeki bir sayı yerine tire gösterilir.",
    noScoredWeek:
      "Henüz kesinleşmiş oyun haftası yok, o yüzden puan yayınlanmıyor: puanlar ancak platform bonusu ekleyip haftayı kontrol edince kesinleşir.",
    total: "toplam",
    movement: "hareket",
    unknown: "bilinmiyor",
    newMember: "yeni",
    movementLabel: (movement, places) =>
      movement === "same" ? "—" : `${movement === "up" ? "↑" : "↓"} ${places}`,
    unknownMember: "Bilinmeyen Üye",
    unknownTeam: "İsimsiz takım",
    publicDataTitle: "Son tarihten sonra herkese açık",
    publicDataBody:
      "Bu kayıtlar oyun haftası son tarihinden sonra herkese açık FPL verisidir. SquadOpt hiçbir zaman FPL şifresi, oturumu veya özel hesap erişimi istemez.",
    backToMembers: "← Lig üyeleri",
    incompleteTitle: "Eksik Kaynak Kaydı",
    missingFieldLabels: {
      free_transfers: "ücretsiz transfer hakkı",
      purchase_prices: "satın alma fiyatları",
    },
    missingFieldUnknown: "diğer eksik veri",
    incompleteBody: (fields) =>
      `Kaynak şu alanları sağlamadı: ${fields}. Boşlukları doldurmak için veri uydurulmaz.`,
    entryAssumptionsTitle: "Herkese Açık Veri Sınırları",
    currentPriceFallback:
      "Satın alma fiyatları herkese açık değildir. Satış fiyatı olarak mevcut fiyat kullanılır; fiyatı yükselen bir oyuncu için kullanılabilir bütçe olduğundan yüksek görünebilir.",
    memberSquad: "Üye kadrosu",
    heldViceCaptainUnavailable: "Yayımlanan kadroda yedek kaptan belirtilmiyor.",
    starterCount: (count) => `${count} ilk 11 oyuncusu`,
    bench: "Yedekler",
    benchCount: (count) => `${count} yedek`,
    emptySquad: "Bu üye için kadro bulunmuyor.",
    emptySquadBody: "Yayımlanan üye kaydında kadro bilgisi bulunmuyor.",
    advice: "Önerilen Hamleler",
    honestyRule:
      "Öneriler beklenen puan ödünleşimlerini gösterir. Strateji etiketleri tanımlı kurallara dayanır; yayımlanan çözücü durumu ve sınırlar, kanıtın kapsamını belirtir.",
    independentAdviceRule:
      "Önerin yalnızca senin kadrondan hareketle, seçtiğin stratejiye göre hesaplanır. Her üye bağımsız olarak aynı karar kurallarıyla değerlendirilir.",
    squadoptComparisonTitle: "Kaydedilen puan farkı",
    squadoptComparison: (difference) =>
      `SquadOpt'un bu haftaki kadrosuyla puan farkın: ${difference}`,
    noMove: "Yayımlanan plan transfer önermiyor.",
    noAdviceMissingData: "Kaynak kadro eksik olduğu için öneri gösterilmiyor.",
    diagnosticOnly:
      "İki ilk 11 aynı projeksiyonla karşılaştırılır. Aynı çarpana sahip ortak oyuncuların katkıları sadeleşir; kalan beklenen puanlar, kaptan çarpanları ve bu planın transfer cezaları beklenen farkı belirler.",
    unprovenPlanBadge: "Kanıt tamamlanamadı",
    unprovenPlanBody: (gap: string) =>
      `Çözücü bu plan için kanıtı tamamlayamadı (fark ≤ ${gap} puan). Bu, aramanın bulduğu en iyi plan; en iyisi olduğu gösterilmiş bir plan değil.`,
    out: "Çıkan",
    in: "Giren",
    projectedGain: (pointsValue) => `${pointsValue} tahmini kazanç`,
    weekTransferCost: (pointsValue) =>
      `Bu haftanın transferlerinin toplam beklenen puan maliyeti ~${pointsValue}: oyun haftayı ücretlendirir, her hamleyi ayrı ayrı değil.`,
    windowValueReason: "Yayımlanan puan tahminlerini kullanan çok haftalı planın bir parçası.",
    pointsGainReason:
      "Bir haftalık saf puan planının parçası; yalnızca beklenen puana göre seçildi.",
    modeTradeoffReason: "Bu hamle, seçilen stratejinin beklenen puan ödünleşiminin bir parçasıdır.",
    planCost: (pointsValue) =>
      `Bu strateji, saf puan seçimine göre ~${pointsValue} beklenen puandan vazgeçiyor (transfer cezaları dahil).`,
    planCostAtMost: (pointsValue) =>
      `Bu strateji, saf puan seçimine göre en fazla ${pointsValue} beklenen puandan vazgeçiyor (transfer cezaları dahil).`,
    planRival: (name) => `${name} kadrosuna göre fiyatlandı`,
    lineupTitle: "Bu haftaki kadron",
    lineupRule:
      "Kaptan, yedek kaptan, ilk on bir ve yedek sırası hamlelerle aynı projeksiyondan gelir; yedekler oyunun otomatik değişikliklerinin izlediği sırayla listelenir.",
    expectedOwnPoints: (pointsValue) => `${pointsValue} beklenen puan (ilk on bir, kaptan iki kat)`,
    captainLabel: "Kaptan",
    viceCaptainLabel: "Yedek kaptan",
    startingXiLabel: "İlk on bir",
    benchOrderLabel: "Yedek sırası",
    chipLabel: "Çip",
    chipNone: "Bu hafta çip yok",
    chipNames: {
      bboost: "Bench Boost",
      "3xc": "Triple Captain",
      wildcard: "Wildcard",
      freehit: "Free Hit",
    },
    linkTitle: "Klasik lig 352490",
    linkBody:
      "Üye yüzeyi mock-first hazırlandı; her satır üyenin son tarih sonrası public kadrosuna ve önerilen hamlelerine bağlanacak.",
    linkLabel: "Lig üyelerini aç →",
  },
  reasonCodes: {
    no_capture: () => "elde capture yok; takvim bilinmiyor",
    settle_due: (p: ReasonParams) =>
      `oyun haftası ${p.gameweek} son capture'da bitmiş görünüyor ve kararının sonucu işlenmemiş`,
    recapture_for_outcome: (p: ReasonParams) =>
      `oyun haftası ${p.gameweek} karara bağlandı ama bitmiş işaretli değil; capture ${p.capture_age_hours} saatlik`,
    await_outcome: (p: ReasonParams) =>
      `oyun haftası ${p.gameweek} sonucunu bekliyor; ${p.recapture_hours} saat sonra tekrar bakılacak`,
    deadline_missed: (p: ReasonParams) =>
      `oyun haftası ${p.gameweek} kararsız kapandı; artık bu hafta için karar verilemez`,
    no_open_deadline: () => "son capture'ın takviminde açık bir deadline yok",
    already_decided: (p: ReasonParams) =>
      `oyun haftası ${p.gameweek} zaten karara bağlandı; sonucu gelene kadar yapılacak iş yok`,
    before_window: (p: ReasonParams) =>
      `oyun haftası ${p.gameweek} deadline'ına ${p.hours_left} saat var; capture penceresi ${p.window_hours} saat önce açılır`,
    capture_window_open: (p: ReasonParams) =>
      `oyun haftası ${p.gameweek} deadline'ına ${p.hours_left} saat var ve pencere içinden capture alınmadı`,
    decide_opening: (p: ReasonParams) => `açılış haftası ${p.gameweek}: capture pencere içinde`,
    decide_ready: (p: ReasonParams) =>
      `oyun haftası ${p.gameweek}: capture ve projeksiyon devri hazır`,
    handoff_missing: (p: ReasonParams) =>
      `oyun haftası ${p.gameweek} deadline'ına ${p.hours_left} saat var; capture hazır ama projeksiyon devri eksik`,
  },
  riskReasons: {
    not_requested: "Artık geçmişi verilmedi; dağılımsal risk değerlendirilmedi.",
    available: "Risk metrikleri, eşleşen tarihsel artık kanıtına dayanıyor.",
    model_mismatch: "Artık geçmişi farklı bir model sözleşmesinden üretilmiş.",
    unsupported_opening_gameweek: "Sezon içi artıklar açılış haftası riskini desteklemez.",
    insufficient_history: "Uygun artık geçmişi kalibrasyon için çok kısa.",
  },
  verdictCodes: {
    no_scored_gameweeks: () =>
      "Henüz skorlanmış oyun haftası yok, karşılaştıracak bir şey de yok: oyun, ortalamayı ancak bir hafta bitince yayınlıyor.",
    standing: (p: ReasonParams) => {
      const caveat =
        p.caveat === "noise"
          ? " - tek hafta gürültüdür, kanıt değil"
          : p.caveat === "few"
            ? " - bir sezonun oynaklığı için hâlâ az hafta"
            : "";
      const own =
        p.mean_starter_ownership !== undefined
          ? `; ilk on birin ortalama sahipliği %${p.mean_starter_ownership}`
          : "";
      const sign = Number(p.difference) >= 0 ? "+" : "";
      return `Skorlanan ${p.scored} haftada oyun ortalamasına karşı ${sign}${p.difference} puan${caveat}${own}.`;
    },
  },
  status: {
    loading: "Tick durumu yükleniyor…",
    unavailable: "Durum bilgisi kullanılamıyor.",
    noStatus: "Kaydedilmiş durum yok.",
    kicker: (contract, time) => `sezon tick'i · ${contract} · ${time} itibarıyla`,
    title: "Durum",
    nextGameweek: "sıradaki oyun haftası",
    deadline: (time) => `son tarih ${time}`,
    noDeadline: "son capture'da açık son tarih yok",
    timeToDeadline: "son tarihe kalan süre",
    deadlinePassed: "son tarih geçti",
    deadlineUnknown: "bilinmiyor",
    atPublish: (hours) => `yayımlandığında ${hours} sa kalmıştı`,
    latestCapture: (capture) => `son capture ${capture}`,
    noCapture: "capture yok",
    decidedSettled: "kararlaştırılan · sonuçlanan",
    gameweeks: (weeks) => `OH ${weeks.join(", ")}`,
    nothingDecided: "henüz karar yok",
    actionsTitle: "Tick şimdi ne yapardı",
    idle: "boşta",
    actionCount: (count) => `${count} işlem`,
    nothingDue: "Yapılması gereken işlem yok.",
    recent: "Son Çalışma Günlüğü",
    newest: "en yeni önce",
    noLog: "Henüz çalışma günlüğü yok — tick bu makinede çalışmadı.",
  },
  analysis: {
    types: {
      passed: "kapı geçti",
      negative: "temiz negatif",
      descriptive: "betimleyici",
      prereg: "prereg",
    },
    noDate: "tarih kaydı yok",
    notFoundTitle: "Ölçüm bulunamadı.",
    notFoundBody: "İndekste bu kimlikle bir artefakt yok.",
    loadingDocument: "Ölçüm yükleniyor…",
    documentError: "Ölçüm açılamadı.",
    back: "← Analiz Merkezi",
    loadingIndex: "Ölçüm indeksi yükleniyor…",
    indexError: "Analiz Merkezi açılamadı.",
    kicker: "kanıt, kararın yanında",
    title: "Analiz Merkezi",
    lede: "Geçen kapılar kadar temiz negatifler de burada kalır. İçerikler İngilizce kaynak belgelerin değişmeden sunulan kopyalarıdır.",
    viewLabel: "Ölçüm görünümü",
    all: "Tüm Ölçümler",
    negatives: "Negatifler",
    filters: "Ölçüm filtreleri",
    type: "Tür",
    phase: "Faz",
    allOption: "Tümü",
    from: "Başlangıç Tarihi",
    to: "Bitiş Tarihi",
    count: (shown, total) => `${shown} / ${total} ölçüm gösteriliyor`,
    empty: "Bu filtrelerle ölçüm yok.",
  },
};

export type Messages = MessageSchema<typeof en>;

export const MESSAGES: Record<Language, Messages> = { tr, en };
