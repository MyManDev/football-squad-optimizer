export type Language = "tr" | "en";

export type ReasonParams = Record<string, string | number | undefined>;

const en = {
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
    footer:
      "Decisions and settled results come from the SquadOpt ledger. Provisional scores show their source capture and time.",
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
    lowerTail: (probability: string, points: string) => `Lower ${probability} Tail ${points}`,
    lowerTailUnavailable: "Lower Tail: Not Evaluated",
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
    score: "Score",
    riskStatus: {
      available: "Available",
      unavailable: "Unavailable",
      not_requested: "Not Requested",
    },
    scenarioMean: "Mean of Scenarios",
    shiftedForOptimism: (points: string) => `Shifted ${points} for Selection Optimism`,
    meanWorst: (fraction: string) => `Mean Worst ${fraction}`,
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
      purePrice: "No Rival Budget",
      safe: "Cautious",
      safeDescription: "Aims to reduce the chance of falling behind in the league.",
      aggressive: "Aggressive",
      aggressiveDescription: "A balanced competitive mode focused on moving ahead of the rival.",
      extreme: "Very Aggressive",
      extremeDescription: "Looks for harder decisions that can create a gap of more than five.",
      behind: "P(behind)",
      aheadFive: "P(5+ ahead)",
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
    probabilityTitle: "Probability of finishing ahead",
    probabilityAside: "same scenarios, shared players cancel",
    rivalComparisons: "Rival Comparisons",
    rival: "rival",
    probabilityInterval: "P(ahead) with 90% interval",
    meanGap: "mean gap",
    shared: "shared",
    probabilityLabel: (rival: string) => `probability of finishing ahead of ${rival}`,
    interval: (low: string, high: string) => `90% interval ${low} to ${high}`,
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
      "Pick your own row to get advice from your squad. This is a claim, not a login: anyone can pick anyone, and that is fine because everything shown here is already public after the deadline.",
    viewerSelect: "This is me",
    viewerYouBadge: "You",
    viewerSelected: (name: string) =>
      `Viewing as ${name}. Advice pages will start from this squad.`,
    viewerClear: "Clear selection",
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
        description: "The highest expected points, no rival in the equation.",
      },
      "ortak-koru": {
        name: "Keep the shared core",
        description:
          "Hold as many of the rival's eleven as the free transfers reach, up to nine; a hit is spent only where it pays for itself.",
      },
      "fark-yarat": {
        name: "Create a gap",
        description:
          "Hold as few of the rival's eleven as the free transfers allow, down to five; the players you do not share decide the gap.",
      },
    } as Record<"saf-puan" | "ortak-koru" | "fark-yarat", { name: string; description: string }>,
    rivalLegend: "Rival",
    rivalLabel: "The member you are playing against",
    rivalDefaultSuffix: "(nearest above in the standings)",
    rivalUnavailableSuffix: "(not computed)",
    rivalNone: "No other member's squad is published for this week.",
    rivalNote: "The rival's public eleven is a constraint and a comparison, nothing more.",
    windowLegend: "Window",
    windowNotComputed:
      "Only the one-week plan is on hand for this choice: three- and five-week plans exist for pure points only, and only where this publish solved them; a rival strategy is one week at a time.",
    windowLimits:
      "A three- or five-week plan repeats the week-1 projection over the fixture calendar, one transfer a week, and is published with the limits it assumes; it is not a forecast of the later weeks.",
    windowTitle: (weeks: number) => `The ${weeks}-week window`,
    windowRule:
      "The moves and the lineup above are the first week's. Each row below is one gameweek of the plan, in expected points under the limits stated here.",
    windowLimitsLabel: "What this window assumes",
    windowWeek: "Week",
    windowWeekOf: (gameweek: number) => `GW${gameweek}`,
    windowHits: "Hit points",
    windowPoints: "Expected points",
    // The producer's limit sentences travel in the payload; English shows them as
    // written, so nothing is listed here and every sentence falls through unchanged.
    statedLimits: {} as Record<string, string>,
    controlUnprovenBody: (gap: string) =>
      `The pure-points plan behind this price was not proven optimal (gap ≤ ${gap} pts): the tag is a reading with that bound, not a proof.`,
    overlapLine: (count: number) => `${count} of the rival's eleven in your fifteen`,
    gapLine: (points: string) => `expected gap vs rival ${points}`,
    captainShared: "same captain",
    planWithinFree: (cap: number, target: number, applied: number) =>
      `Played within ${cap} free transfer${cap === 1 ? "" : "s"}, no hits: the strategy asked for ${target} of the rival's eleven and ${applied} was reachable.`,
    planWithHits: (cap: number, target: number) =>
      `Reaching ${target} of the rival's eleven needed more than the ${cap} free transfer${cap === 1 ? "" : "s"}; the hits are charged in the price and still came out ahead.`,
    alternativeWithHits: (applied: number, hits: string, cost: string) =>
      `Not taken: reaching ${applied} with hits would have cost ${hits} hit points, ${cost} expected points against pure points.`,
    alternativeWithinFree: (applied: number, cost: string) =>
      `Not taken: staying within the free transfers reached ${applied} at ${cost} expected points against pure points.`,
    templatesTitle: "Game templates",
    templatesBody:
      "A template is a named strategy-and-window pair. Applying one sets the same shareable selection the controls read; your own templates live in this browser.",
    templateMeta: (strategy: string, window: number, rival: string) =>
      `${strategy} · ${window}w · ${rival}`,
    templateNamePlaceholder: "Name this combination",
    templateSave: "Save current",
    templateRemove: (name: string) => `Remove template ${name}`,
    notAvailable: "League member data is not connected yet.",
    notAvailableBody:
      "The page is ready for the post-deadline public entry feed. No example records are shipped in the production build.",
    loadingEntry: "Loading this member's squad…",
    adviceNotComputed: "This combination was not computed for this publish.",
    adviceNotComputedBody:
      "The site publishes the decisions it actually solved from your squad: pure points, and each strategy against each rival where a plan exists. A pair that has no plan says so in the rival list.",
    entryNotAvailable: "This member is not available yet.",
    entryNotAvailableBody:
      "The public post-deadline squad or its advice has not been published to this site build.",
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
    gameweekPoints: "GW points",
    gameweekPointsFor: (gameweek: number) => `GW${gameweek} points`,
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
    incompleteBody: (fields: string) =>
      `The source did not provide: ${fields}. Nothing is invented to fill it.`,
    entryAssumptionsTitle: "Public-data limits",
    freeTransfersAssumed: (count: number) =>
      `The public source does not reveal banked free transfers. This plan assumes ${count}; a second banked transfer may be invisible.`,
    currentPriceFallback:
      "Purchase prices are not public. Current prices are used as selling prices, which may overstate the available budget after a price rise.",
    memberSquad: "Member Squad",
    starterCount: (count: number) => `${count} starters`,
    bench: "Bench",
    benchCount: (count: number) => `${count} substitutes`,
    emptySquad: "No squad is available for this member.",
    emptySquadBody:
      "The empty example fixes the UI behaviour for an entry whose public picks have not arrived.",
    advice: "Suggested Moves",
    honestyRule:
      "Advice is labelled only with a point trade-off. Crowd-relative window diagnostics are never dressed up as a chance of winning.",
    independentAdviceRule:
      "Your advice is calculated only from your squad and your objective. SquadOpt's own team does not enter that calculation: the system cannot protect its rank by giving anyone worse advice; every member is evaluated independently by the same decision function.",
    squadoptComparisonTitle: "Recorded score difference",
    squadoptComparison: (difference: string) =>
      `Your point difference from SquadOpt's squad this gameweek: ${difference}`,
    noMove: "No move clears the selected example point trade-off.",
    noAdviceMissingData: "Advice is withheld because the source squad is incomplete.",
    diagnosticOnly:
      "Two squads are compared under one projection. Players you both own cancel out; the players you do not share decide the gap. We publish expected points, never a chance of winning — that claim fell three times in its own measurement, and the line is closed.",
    unprovenPlanBadge: "Proof incomplete",
    unprovenPlanBody: (gap: string) =>
      `The solver found this plan but could not prove nothing better exists (gap ≤ ${gap} pts). The plan is real; the missing part is the proof.`,
    out: "Out",
    in: "In",
    projectedGain: (points: string) => `${points} projected gain`,
    expectedPointCost: (points: string) => `~${points} expected-point cost`,
    windowValueReason: "The longer window recovers the transfer cost in the example projection.",
    modeTradeoffReason:
      "The mode changes the point trade-off, never a claimed chance of beating a rival.",
    planCost: (points: string) =>
      `This strategy gives up ~${points} expected points against the pure-points pick, hits included.`,
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
    hours: "hours to deadline",
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
    footer:
      "Kararlar ve kesinleşmiş sonuçlar SquadOpt ledger kaydından gelir. Geçici puanlar kaynak capture ve zamanıyla gösterilir.",
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
    lowerTail: (probability, pointsValue) => `Alt ${probability} Kuyruk ${pointsValue}`,
    lowerTailUnavailable: "Alt Kuyruk Değerlendirilmedi",
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
    score: "Puan",
    riskStatus: {
      available: "Kullanılabilir",
      unavailable: "Kullanılamıyor",
      not_requested: "İstenmedi",
    },
    scenarioMean: "Senaryo Ortalaması",
    shiftedForOptimism: (pointsValue) => `Seçim İyimserliği İçin ${pointsValue} Kaydırıldı`,
    meanWorst: (fraction) => `En Kötü ${fraction} Ortalaması`,
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
      purePrice: "Rakip Bütçesi Yok",
      safe: "Garantici",
      safeDescription: "Lig içinde geride kalma ihtimalini azaltmayı hedefler.",
      aggressive: "Agresif",
      aggressiveDescription: "Rakibin önüne geçmeye odaklanan dengeli rekabet modu.",
      extreme: "Aşırı Agresif",
      extremeDescription: "Beş puandan büyük fark yaratabilecek daha sert kararları arar.",
      behind: "P(geride)",
      aheadFive: "P(5+ önde)",
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
    probabilityTitle: "Önde bitirme olasılığı",
    probabilityAside: "aynı senaryolar; ortak oyuncular birbirini götürür",
    rivalComparisons: "Rakip Karşılaştırmaları",
    rival: "rakip",
    probabilityInterval: "%90 aralıkla P(önde)",
    meanGap: "ortalama fark",
    shared: "ortak",
    probabilityLabel: (rival) => `${rival} rakibinin önünde bitirme olasılığı`,
    interval: (low, high) => `%90 aralık ${low}–${high}`,
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
      "Kendi satırını seç ki tavsiye kendi kadrondan hesaplansın. Bu bir beyandır, giriş değil: herkes herkesi seçebilir ve bu sorun değil, çünkü burada gösterilen her şey son tarihten sonra zaten herkese açık.",
    viewerSelect: "Bu benim",
    viewerYouBadge: "Sen",
    viewerSelected: (name: string) =>
      `${name} olarak bakıyorsun. Tavsiye sayfaları bu kadrodan başlayacak.`,
    viewerClear: "Seçimi kaldır",
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
        description: "En yüksek beklenen puan; denklemde rakip yok.",
      },
      "ortak-koru": {
        name: "Ortak çekirdeği koru",
        description:
          "Rakibin on birinden ücretsiz transferlerin ulaştığı kadarını tut, en çok dokuz; hit yalnız kendini ödüyorsa harcanır.",
      },
      "fark-yarat": {
        name: "Fark yarat",
        description:
          "Rakibin on birinden ücretsiz transferlerin izin verdiği kadar azını tut, en az beş; paylaşmadığın oyuncular farkı belirler.",
      },
    },
    rivalLegend: "Rakip",
    rivalLabel: "Karşısında oynadığın üye",
    rivalDefaultSuffix: "(sıralamada hemen üstün)",
    rivalUnavailableSuffix: "(hesaplanamadı)",
    rivalNone: "Bu hafta için başka bir üyenin kadrosu yayınlanmamış.",
    rivalNote: "Rakibin açık on biri bir kısıt ve bir karşılaştırmadır, başka bir şey değil.",
    windowLegend: "Pencere",
    windowNotComputed:
      "Bu seçim için yalnız bir haftalık plan var: üç ve beş haftalık planlar yalnız saf puan için ve yalnız bu yayının çözdüğü yerde var; rakip stratejisi hafta hafta oynanır.",
    windowLimits:
      "Üç ya da beş haftalık plan 1. hafta projeksiyonunu fikstür takvimi üzerinde tekrarlar, haftada bir transferle; varsaydığı sınırlarla yayınlanır ve sonraki haftaların tahmini değildir.",
    windowTitle: (weeks) => `${weeks} haftalık pencere`,
    windowRule:
      "Yukarıdaki hamleler ve kadro ilk haftanın. Aşağıdaki her satır planın bir oyun haftası; beklenen puan, burada yazılı sınırlar altında.",
    windowLimitsLabel: "Bu pencerenin varsaydıkları",
    windowWeek: "Hafta",
    windowWeekOf: (gameweek) => `OH${gameweek}`,
    windowHits: "Hit puanı",
    windowPoints: "Beklenen puan",
    // The producer's sentences, keyed exactly as its payload carries them; a sentence
    // the site does not know falls through in the producer's own words.
    statedLimits: {
      "The first week's projection is repeated over the later weeks, scaled by each club's fixture count from the captured calendar; the later weeks are not projected separately.":
        "İlk haftanın projeksiyonu sonraki haftalarda tekrarlanır, her kulübün capture'daki takvimdeki maç sayısıyla ölçeklenir; sonraki haftalar ayrıca projekte edilmez.",
      "Availability is applied once, from the capture: injuries, rotation and suspensions after it are not seen.":
        "Oynayabilirlik bir kez, capture'dan uygulanır: sonrasındaki sakatlıklar, rotasyon ve cezalar görülmez.",
      "Every week inside the window, the first included, is capped at one transfer (a wildcard week excepted); the one-week plan has no such cap.":
        "Pencere içindeki her hafta, ilki dahil, bir transferle sınırlıdır (wildcard haftası hariç); bir haftalık planda böyle bir sınır yoktur.",
      "The Top-100 uplift is inside the first week's numbers, and the repetition carries it into every later week.":
        "Top-100 düzeltmesi ilk haftanın sayılarının içindedir ve tekrar onu sonraki her haftaya taşır.",
      "Prices are held at the captured values; no price change is modelled.":
        "Fiyatlar capture'daki değerlerde tutulur; fiyat değişimi modellenmez.",
      "A chip the plan plays inside the window is valued inside the window only; what it would be worth in a later week is not counted.":
        "Planın pencere içinde oynadığı çip yalnız pencere içinde değerlenir; sonraki bir haftada ne edeceği sayılmaz.",
    },
    controlUnprovenBody: (gap: string) =>
      `Bu fiyatın arkasındaki saf puan planı en iyi diye kanıtlanamadı (fark ≤ ${gap} puan): etiket o sınırla bir okuma, kanıt değil.`,
    overlapLine: (count: number) => `rakibin on birinden ${count} tanesi senin on beşinde`,
    gapLine: (pointsValue: string) => `rakibe karşı beklenen fark ${pointsValue}`,
    captainShared: "aynı kaptan",
    planWithinFree: (cap: number, target: number, applied: number) =>
      `${cap} ücretsiz transfer içinde, hit yok: strateji rakibin on birinden ${target} istedi, ${applied} ulaşılabilirdi.`,
    planWithHits: (cap: number, target: number) =>
      `Rakibin on birinden ${target} tanesine ulaşmak ${cap} ücretsiz transferden fazlasını istedi; hit'ler fiyata dahil ve yine de önde çıktı.`,
    alternativeWithHits: (applied: number, hits: string, cost: string) =>
      `Tercih edilmedi: hit'lerle ${applied} tanesine ulaşmak ${hits} hit puanı, saf puana göre ${cost} beklenen puan mal olurdu.`,
    alternativeWithinFree: (applied: number, cost: string) =>
      `Tercih edilmedi: ücretsiz transferlerde kalmak ${applied} tanesine ulaşırdı, saf puana göre ${cost} beklenen puana.`,
    templatesTitle: "Oyun şablonları",
    templatesBody:
      "Şablon, adlandırılmış bir strateji-pencere çiftidir. Uygulamak, kontrollerin okuduğu paylaşılabilir seçimi kurar; kendi şablonların bu tarayıcıda durur.",
    templateMeta: (strategy: string, window: number, rival: string) =>
      `${strategy} · ${window}h · ${rival}`,
    templateNamePlaceholder: "Bu kombinasyonu adlandır",
    templateSave: "Seçimi kaydet",
    templateRemove: (name: string) => `${name} şablonunu kaldır`,
    loading: "Lig üyeleri yükleniyor…",
    notAvailable: "Lig üye verisi henüz bağlı değil.",
    notAvailableBody:
      "Sayfa son tarih sonrası public entry akışına hazırdır. Örnek kayıtlar production paketine dahil edilmez.",
    loadingEntry: "Üyenin kadrosu yükleniyor…",
    adviceNotComputed: "Bu kombinasyon bu yayın için hesaplanmadı.",
    adviceNotComputedBody:
      "Site, kadrondan gerçekten çözdüğü kararları yayınlar: saf puan ve plan bulunan her rakibe karşı her strateji. Planı olmayan bir çift rakip listesinde bunu söyler.",
    entryNotAvailable: "Bu üye henüz kullanılamıyor.",
    entryNotAvailableBody:
      "Son tarih sonrası public kadro veya öneri bu site paketine henüz yayımlanmadı.",
    invalidEntry: "Bu entry ID geçerli değil.",
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
    gameweekPoints: "OH puanı",
    gameweekPointsFor: (gameweek) => `OH${gameweek} puanı`,
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
    incompleteBody: (fields) =>
      `Kaynak şu alanları sağlamadı: ${fields}. Boşlukları doldurmak için veri uydurulmaz.`,
    entryAssumptionsTitle: "Public Veri Sınırları",
    freeTransfersAssumed: (count) =>
      `Public kaynak banka edilmiş serbest transfer sayısını göstermiyor. Bu plan ${count} varsayıyor; banka edilmiş ikinci transfer görünmüyor olabilir.`,
    currentPriceFallback:
      "Satın alma fiyatları public değildir. Satış fiyatı olarak mevcut fiyat kullanılır; fiyatı yükselen bir oyuncu için kullanılabilir bütçe olduğundan yüksek görünebilir.",
    memberSquad: "Üye kadrosu",
    starterCount: (count) => `${count} ilk 11 oyuncusu`,
    bench: "Yedekler",
    benchCount: (count) => `${count} yedek`,
    emptySquad: "Bu üye için kadro bulunmuyor.",
    emptySquadBody:
      "Boş örnek, public seçimleri henüz gelmeyen bir entry için arayüz davranışını sabitler.",
    advice: "Önerilen Hamleler",
    honestyRule:
      "Öneriler yalnızca puan ödünleşimi etiketi taşır. Kalabalık-göreli pencere diagnostikleri kazanma ihtimali gibi sunulmaz.",
    independentAdviceRule:
      "Sana verilen öneri yalnızca senin kadrondan ve senin hedefinden hesaplanır. Sistemin kendi takımı bu hesaba girmez. Sistem kendi sırasını korumak için kimseye kötü öneri veremez; her üyenin önerisi bağımsız olarak aynı karar fonksiyonundan çıkar.",
    squadoptComparisonTitle: "Kaydedilen puan farkı",
    squadoptComparison: (difference) =>
      `SquadOpt'un bu haftaki kadrosuyla puan farkın: ${difference}`,
    noMove: "Seçilen örnek puan ödünleşimini geçen bir hamle yok.",
    noAdviceMissingData: "Kaynak kadro eksik olduğu için öneri gösterilmiyor.",
    diagnosticOnly:
      "İki kadro aynı projeksiyonla karşılaştırılır. İkinizde de olan oyuncular sadeleşir; farkı paylaşmadığınız oyuncular belirler. Beklenen puan yayınlıyoruz, kazanma ihtimali değil — o iddia kendi ölçümünde üç kez düştü ve hat kapandı.",
    unprovenPlanBadge: "Kanıt tamamlanamadı",
    unprovenPlanBody: (gap: string) =>
      `Çözücü bu planı buldu ama daha iyisinin olmadığını kanıtlayamadı (fark ≤ ${gap} puan). Plan gerçek; eksik olan kanıt.`,
    out: "Çıkan",
    in: "Giren",
    projectedGain: (pointsValue) => `${pointsValue} tahmini kazanç`,
    expectedPointCost: (pointsValue) => `~${pointsValue} beklenen puan maliyeti`,
    windowValueReason: "Uzun pencere, örnek projeksiyonda transfer maliyetini geri kazanıyor.",
    modeTradeoffReason:
      "Mod, rakibi geçme olasılığı iddia etmek yerine puan ödünleşimini değiştirir.",
    planCost: (pointsValue) =>
      `Bu strateji, saf puan seçimine göre ~${pointsValue} beklenen puandan vazgeçiyor (hit'ler dahil).`,
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
    hours: "son tarihe kalan saat",
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
