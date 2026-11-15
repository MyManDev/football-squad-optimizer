import { useQuery, type UseQueryResult } from "@tanstack/react-query";
import { useEffect, useMemo, useRef, useState, type FormEvent } from "react";
import { Link, useParams } from "react-router";

import { EmptyState } from "../../../design/components/EmptyState";
import { PageLoading } from "../../../design/components/PageLoading";
import { useLanguage } from "../../../i18n/context";
import { money } from "../../../lib/format";
import { entryAddress, memberAddress } from "../../../lib/leagueAddresses";
import { useFixtures } from "../../fixtures/data";
import { capabilitiesForPage } from "../advice/adviceCapabilities";
import { createAdviceClient, type AdviceRequest } from "../advice/adviceClient";
import { gameweekDeadline, useDeadlineClock } from "../advice/deadline";
import {
  checkedPreferences,
  holdsOpeningTransfers,
  type FrozenPlanWeek,
} from "../advice/decisionPreferences";
import { sameAdviceRequest, useAdviceJob, type ComputePhase } from "../advice/useAdviceJob";
import { LEAGUE_READ, useEntrySquad } from "../queries";
import type { EntryAdvice, EntrySquad } from "../types";
import { useLeague } from "../useLeague";
import { LLMOPT_COPY, ruleLabel } from "./copy";
import { InfeasibilityResult } from "./InfeasibilityResult";
import {
  EMPTY_DRAFT,
  IntentError,
  MAX_MESSAGE_LENGTH,
  constraintKey,
  needsThreeWeeks,
  preparePlans,
  readIntent,
  readIntentCatalog,
  type CatalogPlayer,
  type Clarification,
  type Constraint,
  type PlanDraft,
} from "./intent";
import { PlanResult, type PreferencePrice } from "./PlanResult";
import {
  expectedNet,
  meaningfulOpeningAlternative,
  openingAlternatives,
  sameOpeningDecision,
  samePlan,
} from "./planComparison";
import { explainDraftConflict } from "./planConflicts";
import {
  freezeReference,
  referenceWeeks,
  summarizeRevision,
  type PlanRevision,
} from "./planRevision";
import {
  ALTERNATIVE_COUNT,
  checkedPlanSession,
  readPlanSession,
  writePlanSession,
  type PlanConfirmation,
  type PlanSessionContext,
  type StartedAlternative,
} from "./planSession";
import { RevisionComparison } from "./RevisionComparison";
import { RuleEditor } from "./RuleEditor";
import styles from "./LLMOptPage.module.css";

const ORIGIN = (import.meta.env.VITE_ADVICE_API_ORIGIN ?? "").replace(/\/$/, "");

function squadBasis(squad: EntrySquad) {
  return JSON.stringify([
    squad.source_snapshot_id,
    squad.season,
    squad.gameweek,
    squad.league_id,
    squad.entry.entry_id,
    squad.squad_basis,
    squad.free_transfers,
    squad.free_transfers_known,
    squad.bank_tenths,
    squad.squad_sell_value_tenths,
    squad.purchase_prices_known,
    [...squad.starting_xi, ...squad.bench].map(({ player_id }) => player_id).sort((a, b) => a - b),
  ]);
}

function isWorking(phase: string) {
  return phase === "requesting" || phase === "waiting";
}

interface ChatLine {
  id: number;
  role: "user" | "assistant";
  message: string;
}

type PreparedPlan = NonNullable<ReturnType<typeof preparePlans>["base"]>;
type PlanRequest = AdviceRequest & Pick<PreparedPlan, "preferences">;
type ExplicitTitle = "with" | "without" | "alternative";
type ReservedAlternative =
  | { kind: "explicit"; title: ExplicitTitle; request: PlanRequest | null; conflict: boolean }
  | { kind: "priced"; request: PlanRequest };

interface PriceTarget {
  rule: Constraint;
  outcome: number | "same" | "conflict" | "unavailable" | "skipped";
}

interface PlanRun {
  baseRequest: PlanRequest | null;
  baseTitle: "base" | "without";
  baseConflict: boolean;
  automaticBasis: PlanRequest | null;
  slots: ReservedAlternative[];
  prices: PriceTarget[];
  wildcardUnavailable: boolean;
}

function requestFor(
  squad: EntrySquad,
  forwarded: boolean | undefined,
  window: AdviceRequest["window"],
): AdviceRequest {
  return {
    publicEntry: forwarded,
    leagueId: squad.league_id,
    entryId: squad.entry.entry_id,
    strategy: "saf-puan",
    window,
    season: squad.season,
    gameweek: squad.gameweek,
  };
}

function prepareRun(
  draft: PlanDraft,
  held: ReadonlySet<number>,
  request: AdviceRequest,
  plans: ReturnType<typeof preparePlans>,
  wildcardNotHeld: boolean,
  frozenWeeks?: readonly FrozenPlanWeek[],
): PlanRun {
  const pricing = draft.soft.length > 0;
  const compareBoth = draft.comparison?.both === true;
  const hardDraft = {
    window: plans.window,
    hard: draft.hard,
    soft: [],
    keep_weeks: draft.keep_weeks,
    min_bank: draft.min_bank,
  };
  const hard = compareBoth ? preparePlans(hardDraft, held, frozenWeeks).base : plans.base;
  const baseline = pricing ? hard : plans.base;
  let wildcardUnavailable = false;
  const submit = (plan: PreparedPlan | null) => {
    if (!plan) return null;
    if (wildcardNotHeld && plan.chip === "wildcard") {
      wildcardUnavailable = true;
      return null;
    }
    return {
      ...request,
      ...plan,
      preferences: pricing
        ? checkedPreferences({ ...plan.preferences, net_points_priority: true })
        : plan.preferences,
    };
  };
  const baseRequest = submit(baseline);
  const automaticBasis = pricing || !compareBoth ? baseRequest : submit(hard);
  const slots: ReservedAlternative[] = [];
  function addExplicit(plan: PreparedPlan | null, conflict: boolean, title: ExplicitTitle) {
    const request = submit(plan);
    if (request || conflict) slots.push({ kind: "explicit", title, request, conflict });
  }
  if (pricing && compareBoth) addExplicit(plans.base, plans.baseConflict, "without");
  if (draft.comparison)
    addExplicit(plans.alternative, plans.alternativeConflict, compareBoth ? "with" : "alternative");
  const prices = draft.soft.map((rule): PriceTarget => {
    if (compareBoth) return { rule, outcome: "skipped" };
    const branch = preparePlans({ ...hardDraft, soft: [rule] }, held, frozenWeeks);
    if (branch.alternativeConflict) return { rule, outcome: "conflict" };
    if (!branch.alternative) return { rule, outcome: "same" };
    const request = submit(branch.alternative);
    if (!request) return { rule, outcome: "unavailable" };
    const existing = slots.findIndex(
      (slot) => slot.request && sameAdviceRequest(slot.request, request),
    );
    if (existing >= 0) return { rule, outcome: existing };
    if (slots.length === ALTERNATIVE_COUNT) return { rule, outcome: "skipped" };
    const outcome = slots.length;
    slots.push({ kind: "priced", request });
    return { rule, outcome };
  });
  return {
    baseTitle: !pricing && compareBoth ? "without" : "base",
    baseConflict: pricing ? plans.hardConflict : plans.baseConflict,
    baseRequest,
    automaticBasis,
    slots,
    prices,
    wildcardUnavailable,
  };
}

function restoredSlot(run: PlanRun, index: number, started?: StartedAlternative | null) {
  const slot = run.slots[index];
  if (slot?.kind === "explicit") return slot.request;
  if (slot?.kind === "priced") return started?.kind === "priced" ? slot.request : null;
  const basis = run.automaticBasis;
  if (!basis || run.prices.length || !started || started.kind === "priced") return null;
  try {
    return {
      ...basis,
      preferences: checkedPreferences({
        ...basis.preferences,
        ...(started.kind === "bank"
          ? { min_opening_bank_tenths: started.floor }
          : { hold_opening_transfers: true }),
      }),
    };
  } catch {
    return null;
  }
}

function preferencePrice(
  target: PriceTarget,
  label: string,
  reference: ComputePhase,
  alternatives: readonly ComputePhase[],
  canStart: boolean,
): PreferencePrice {
  const review = { key: constraintKey(target.rule), label, ceiling: target.rule.max_cost_tenths };
  const { outcome } = target;
  if (outcome === "conflict" || outcome === "unavailable" || outcome === "skipped")
    return { ...review, status: outcome };
  if (reference.phase !== "done")
    return {
      ...review,
      status: isWorking(reference.phase) ? "pending" : "unavailable",
    };
  const referencePlan = reference.envelope.payload;
  if (outcome === "same")
    return {
      ...review,
      status: "priced",
      cost: 0,
      aboveCeiling: false,
      unproven: referencePlan.solver_status !== "OPTIMAL",
    };
  const candidate = alternatives[outcome];
  if (candidate?.phase !== "done")
    return {
      ...review,
      status:
        candidate && (isWorking(candidate.phase) || (candidate.phase === "idle" && canStart))
          ? "pending"
          : "unavailable",
    };

  const candidatePlan = candidate.envelope.payload;
  const referenceNet = expectedNet(referencePlan);
  const candidateNet = expectedNet(candidatePlan);
  if (referenceNet === null || candidateNet === null) return { ...review, status: "unavailable" };
  const cost = samePlan(reference, candidate) ? 0 : Math.max(0, referenceNet - candidateNet);
  return {
    ...review,
    status: "priced",
    cost,
    aboveCeiling: review.ceiling !== undefined && cost - review.ceiling / 10 > 1e-9,
    unproven:
      referencePlan.solver_status !== "OPTIMAL" || candidatePlan.solver_status !== "OPTIMAL",
  };
}

function visibleAutomatic(
  state: ComputePhase,
  reference?: EntryAdvice,
  previous: readonly EntryAdvice[] = [],
) {
  if (state.phase !== "done" || !reference) return null;
  const plan = state.envelope.payload;
  const preferences = state.request.preferences;
  const kind =
    preferences?.min_opening_bank_tenths !== undefined
      ? "bank"
      : preferences?.hold_opening_transfers
        ? "roll"
        : null;
  return kind &&
    meaningfulOpeningAlternative(reference, plan, kind) &&
    !previous.some((shown) => sameOpeningDecision(shown, plan))
    ? { kind, state, plan }
    : null;
}

function Session({ squad }: { squad: EntrySquad }) {
  const { messages } = useLanguage();
  const { forwarded } = useLeague();
  const fixtures = useFixtures();
  const deadline = gameweekDeadline(fixtures.data, squad.season, squad.gameweek);
  const roster = useQuery({
    queryKey: ["llmopt-roster", ORIGIN, squad.season, squad.source_snapshot_id],
    queryFn: ({ signal }) => readIntentCatalog(ORIGIN, squad.season, signal),
    enabled: !!ORIGIN,
    ...LEAGUE_READ,
  });
  const context =
    ORIGIN && deadline && squad.source_snapshot_id
      ? {
          key: `squadopt.llmopt:${JSON.stringify([ORIGIN, forwarded === true, squad.league_id, squad.entry.entry_id])}`,
          basis: squadBasis(squad),
          deadline,
        }
      : null;
  const saved = context ? readPlanSession(context) : null;
  if (fixtures.isPending || (saved && roster.isPending))
    return <PageLoading label={messages.common.loading} />;
  return (
    <Workspace
      key={context ? `${context.key}:${context.deadline}` : undefined}
      squad={squad}
      deadline={deadline}
      fixturesUnavailable={fixtures.isError}
      roster={roster}
      context={context}
      saved={saved}
    />
  );
}

function Workspace({
  squad,
  deadline,
  fixturesUnavailable,
  roster,
  context,
  saved,
}: {
  squad: EntrySquad;
  deadline: string | null;
  fixturesUnavailable: boolean;
  roster: UseQueryResult<CatalogPlayer[]>;
  context: PlanSessionContext | null;
  saved: unknown;
}) {
  const { language, locale } = useLanguage();
  const copy = LLMOPT_COPY[language];
  const { tree, forwarded } = useLeague();
  const now = useDeadlineClock(deadline);
  const closed = deadline !== null && now >= Date.parse(deadline);
  const owned = [...squad.starting_xi, ...squad.bench];
  const held = new Set(owned.map(({ player_id }) => player_id));
  const players = (
    roster.data ?? owned.map((p) => ({ id: p.player_id, name: p.name, team: p.team }))
  ).map((p) => ({ ...p, held: held.has(p.id) }));
  const client = useMemo(() => createAdviceClient(tree.entryAdvice), [tree]);
  const base = useAdviceJob(client, false, squad.source_snapshot_id, true);
  const first = useAdviceJob(client, false, squad.source_snapshot_id, true);
  const second = useAdviceJob(client, false, squad.source_snapshot_id, true);
  const [restored] = useState(() => checkedPlanSession(saved, players, squad.gameweek));
  const [restoredRun] = useState(() => {
    if (!restored?.confirmation) return null;
    const { draft, confirmation } = restored;
    const frozen = freezeReference(restored.reference, draft.keep_weeks);
    const plans = preparePlans({ ...draft, soft: [] }, held, frozen);
    if (plans.hardConflict) return null;
    return prepareRun(
      draft,
      held,
      requestFor(squad, forwarded, plans.window),
      plans,
      confirmation.wildcardNotHeld,
      frozen,
    );
  });
  const [draft, setDraft] = useState<PlanDraft>(restored?.draft ?? EMPTY_DRAFT);
  const [reference, setReference] = useState<PlanRevision | undefined>(restored?.reference);
  const [message, setMessage] = useState("");
  const [conversation, setConversation] = useState<ChatLine[]>(() =>
    restored?.clarification
      ? [
          { id: 0, role: "user", message: restored.clarification.message },
          { id: 1, role: "assistant", message: restored.clarification.question },
        ]
      : [],
  );
  const [clarification, setClarification] = useState<Clarification | undefined>(
    restored?.clarification,
  );
  const [feedback, setFeedback] = useState(
    restoredRun?.wildcardUnavailable ? copy.wildcardUnavailable : "",
  );
  const [checkingSquad, setCheckingSquad] = useState(false);
  const [basisChanged, setBasisChanged] = useState(false);
  const [reading, setReading] = useState(false);
  const [run, setRun] = useState<PlanRun | null>(restoredRun);
  const confirmation = useRef<PlanConfirmation | undefined>(restored?.confirmation);
  const chatInput = useRef<HTMLTextAreaElement>(null);
  const computeButton = useRef<HTMLButtonElement>(null);
  const interpret = useRef<AbortController | null>(null);
  const nextChatLine = useRef(conversation.length);
  const confirming = useRef(false);
  const mounted = useRef(true);

  useEffect(() => {
    mounted.current = true;
    return () => {
      mounted.current = false;
      interpret.current?.abort();
    };
  }, []);

  function change(next: PlanDraft, previous = revised ?? reference) {
    base.reset();
    first.reset();
    second.reset();
    setRun(null);
    setFeedback("");
    setClarification(undefined);
    setDraft(next);
    setReference(previous);
    confirmation.current = undefined;
    writePlanSession(context, { draft: next, reference: previous });
  }

  function revisePlan(plan: EntryAdvice) {
    const selected = summarizeRevision(plan);
    if (!selected) return;
    change(draft, selected);
    chatInput.current?.focus();
  }

  function applyRepair(next: PlanDraft) {
    change(next, reference);
    setFeedback(copy.repairApplied);
    computeButton.current?.focus();
  }

  function setQuestion(next?: Clarification) {
    setClarification(next);
    writePlanSession(context, {
      draft,
      reference,
      clarification: next,
      confirmation: confirmation.current,
    });
  }

  async function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    const text = message.trim();
    if (!text || !ORIGIN || interpret.current || checkingSquad || roster.isPending) return;
    const controller = new AbortController();
    const previous = revised ?? reference;
    interpret.current = controller;
    setReading(true);
    setFeedback("");
    try {
      const answer = await readIntent(
        ORIGIN,
        text,
        language,
        draft,
        players,
        controller.signal,
        clarification,
        referenceWeeks(previous),
      );
      if (controller.signal.aborted) return;
      if (answer.status === "draft") change(answer.draft, previous);
      else setQuestion({ message: clarification?.message ?? text, question: answer.message });
      const reply = answer.status === "clarification" ? answer.message : copy.understood;
      const userLine = nextChatLine.current++;
      const replyLine = nextChatLine.current++;
      setConversation((before) => [
        ...before.slice(-18),
        { id: userLine, role: "user", message: text },
        { id: replyLine, role: "assistant", message: reply },
      ]);
      setMessage("");
    } catch (error) {
      if (!controller.signal.aborted)
        setFeedback(
          error instanceof IntentError && error.status === 429
            ? copy.limited
            : copy.intentUnavailable,
        );
    } finally {
      if (interpret.current === controller) interpret.current = null;
      if (!controller.signal.aborted) setReading(false);
    }
  }

  const frozen = freezeReference(reference, draft.keep_weeks);
  const plans = preparePlans(
    {
      ...draft,
      window: draft.window ?? (needsThreeWeeks(draft) ? 3 : 1),
      soft: [],
    },
    held,
    frozen,
  );
  const canCalculate =
    !plans.hardConflict && (draft.soft.length > 0 || plans.base || plans.alternative);
  const conflictContext = {
    gameweek: squad.gameweek,
    window: plans.window,
    held,
    frozen,
    players,
    copy,
  };
  const hardConflict = plans.hardConflict
    ? (explainDraftConflict(draft, conflictContext) ?? copy.hardConflict)
    : undefined;

  function explainBranchConflict(title: "base" | ExplicitTitle) {
    const comparison = draft.comparison;
    if (title === "base" || !comparison) return hardConflict;
    const rule: Constraint =
      title === "without" && comparison.kind === "include_player"
        ? { kind: "avoid_player", player_id: comparison.player_id, week: comparison.week }
        : comparison;
    return explainDraftConflict({ ...draft, hard: [...draft.hard, rule] }, conflictContext);
  }

  const computing = [base.state, first.state, second.state].some(({ phase }) => isWorking(phase));
  const busy = checkingSquad || reading || computing;
  const diagnosis = (state: ComputePhase) =>
    state.phase === "failed" && state.infeasibility ? (
      <InfeasibilityResult
        diagnosis={state.infeasibility}
        request={state.request}
        draft={draft}
        players={players}
        disabled={busy}
        change={applyRepair}
      />
    ) : undefined;
  const baseState = base.state;
  const { resume: resumeBase, readCached: readBase } = base;
  const { compute: computeFirst } = first;
  const { resume: resumeFirst, readCached: readFirst } = first;
  const { compute: computeSecond } = second;
  const { resume: resumeSecond, readCached: readSecond } = second;
  useEffect(() => {
    if (!run || run !== restoredRun) return;
    let active = true;
    // React can replay mount effects. Wait until their cleanup has completed before resuming.
    queueMicrotask(() => {
      if (!active) return;
      if (run.baseRequest && !resumeBase?.(run.baseRequest)) readBase?.(run.baseRequest);
      const followups = restored?.confirmation?.followups;
      const firstRequest = restoredSlot(run, 0, followups?.[0]);
      const secondRequest = restoredSlot(run, 1, followups?.[1]);
      if (firstRequest && !resumeFirst?.(firstRequest)) readFirst?.(firstRequest);
      if (secondRequest && !resumeSecond?.(secondRequest)) readSecond?.(secondRequest);
    });
    return () => {
      active = false;
    };
  }, [
    run,
    restoredRun,
    restored,
    resumeBase,
    readBase,
    resumeFirst,
    readFirst,
    resumeSecond,
    readSecond,
  ]);

  useEffect(() => {
    if (
      !run?.automaticBasis ||
      baseState.phase !== "done" ||
      baseState.request !== run.baseRequest ||
      !confirmation.current ||
      confirmation.current.followups !== undefined
    )
      return;
    if (deadline === null || Date.now() >= Date.parse(deadline)) return;

    type Candidate = { request: PlanRequest; alternative: StartedAlternative };
    const candidates = run.slots.map((slot): Candidate | null =>
      slot.kind === "priced" ? { request: slot.request, alternative: { kind: "priced" } } : null,
    );
    if (!run.prices.length && run.slots.length < ALTERNATIVE_COUNT) {
      const basis = run.automaticBasis;
      const reserved = run.slots.flatMap((slot) => (slot.request ? [slot.request] : []));
      const { roll, bank } = openingAlternatives(
        baseState.envelope.payload,
        basis.preferences,
        basis.chip,
      );
      const bankFloor = bank?.min_opening_bank_tenths;
      const available: Candidate[] = [];
      if (roll && !reserved.some(({ preferences }) => holdsOpeningTransfers(preferences)))
        available.push({ request: { ...basis, preferences: roll }, alternative: { kind: "roll" } });
      if (bank && bankFloor !== undefined)
        available.push({
          request: { ...basis, preferences: bank },
          alternative: { kind: "bank", floor: bankFloor },
        });
      candidates.push(
        ...available
          .filter(({ request }) => !reserved.some((other) => sameAdviceRequest(request, other)))
          .slice(0, ALTERNATIVE_COUNT - run.slots.length),
      );
    }
    confirmation.current = {
      ...confirmation.current,
      followups: candidates.map((candidate) => candidate?.alternative ?? null),
    };
    writePlanSession(context, {
      draft,
      reference,
      clarification,
      confirmation: confirmation.current,
    });
    const jobs = [computeFirst, computeSecond];
    candidates.forEach((candidate, index) => {
      if (candidate) jobs[index]?.(candidate.request);
    });
  }, [
    baseState,
    run,
    deadline,
    computeFirst,
    computeSecond,
    draft,
    reference,
    clarification,
    context,
  ]);

  async function compute() {
    if (
      busy ||
      confirming.current ||
      clarification !== undefined ||
      !ORIGIN ||
      !squad.source_snapshot_id ||
      deadline === null ||
      Date.now() >= Date.parse(deadline) ||
      !canCalculate
    )
      return;
    confirming.current = true;
    setFeedback("");
    setCheckingSquad(true);
    try {
      const [fresh, capabilities] = await Promise.all([
        tree.entrySquad(squad.entry.entry_id),
        forwarded
          ? client.readPublicCapabilities?.(squad.league_id, squad.entry.entry_id)
          : client.readCapabilities?.(squad.league_id),
      ]);
      if (!mounted.current) return;
      if (!capabilities?.preferences) {
        setFeedback(copy.serviceUnavailable);
        return;
      }
      if (!capabilities.strategies["saf-puan"]?.windows.includes(plans.window)) {
        setFeedback(copy.windowUnavailable);
        return;
      }
      if (
        squadBasis(fresh.payload) !== squadBasis(squad) ||
        !capabilitiesForPage(capabilities, {
          leagueId: squad.league_id,
          season: squad.season,
          gameweek: squad.gameweek,
          snapshotId: squad.source_snapshot_id,
        }) ||
        Date.now() >= Date.parse(deadline)
      ) {
        setBasisChanged(true);
        setRun(null);
        setReference(undefined);
        confirmation.current = undefined;
        writePlanSession(context, { draft });
        return;
      }
      const request = requestFor(squad, forwarded, plans.window);
      // A public team may have no chip list until its FPL inputs are pinned.
      const heldChips = capabilities.chipsByEntry?.[String(squad.entry.entry_id)];
      const wildcardNotHeld = heldChips !== undefined && !heldChips.includes("wildcard");
      const next = prepareRun(draft, held, request, plans, wildcardNotHeld, frozen);
      if (next.wildcardUnavailable) setFeedback(copy.wildcardUnavailable);
      if (
        !next.baseRequest &&
        !next.slots.some((slot) => slot.kind === "explicit" && slot.request)
      ) {
        setRun(null);
        confirmation.current = undefined;
        writePlanSession(context, { draft, reference });
        return;
      }
      first.reset();
      second.reset();
      setRun(next);
      confirmation.current = { wildcardNotHeld };
      writePlanSession(context, { draft, reference, confirmation: confirmation.current });
      if (next.baseRequest) {
        base.compute(next.baseRequest);
      } else base.reset();
      const jobs = [computeFirst, computeSecond];
      next.slots.forEach((slot, index) => {
        if (slot.kind === "explicit" && slot.request) jobs[index]?.(slot.request);
      });
    } catch {
      if (mounted.current) setFeedback(copy.squadUnavailable);
    } finally {
      confirming.current = false;
      if (mounted.current) setCheckingSquad(false);
    }
  }

  const baseAnswer = baseState.phase === "done" ? baseState.envelope.payload : undefined;
  const states = [first.state, second.state];
  const priceReview =
    run?.prices.map((target) => {
      const price = preferencePrice(
        target,
        ruleLabel(target.rule, players, copy),
        baseState,
        states,
        !closed && (run !== restoredRun || restored?.confirmation?.followups === undefined),
      );
      if (target.outcome === "conflict")
        price.detail = explainDraftConflict(
          { ...draft, hard: [...draft.hard, target.rule] },
          conflictContext,
        );
      return { outcome: target.outcome, price };
    }) ?? [];
  const results: {
    title: string;
    state: ComputePhase;
    conflict?: boolean;
    conflictMessage?: string;
  }[] = [];
  let same = false;
  if (run) {
    states.forEach((state, index) => {
      const slot = run.slots[index];
      if (slot?.kind === "explicit") {
        // A requested with/without pair remains visible alongside an independent pricing reference.
        if (
          !slot.conflict &&
          slot.title !== "without" &&
          (run.baseTitle === "without" || slot.title === "alternative") &&
          samePlan(baseState, state)
        ) {
          same = true;
        } else {
          results.push({
            title: copy[slot.title],
            state,
            conflict: slot.conflict,
            conflictMessage: slot.conflict ? explainBranchConflict(slot.title) : undefined,
          });
        }
      } else if (slot?.kind === "priced") {
        if (state.phase === "failed" && state.infeasibility) {
          const reason = priceReview.find(({ outcome }) => outcome === index);
          if (reason) results.push({ title: copy.pricedPlan(reason.price.label), state });
          return;
        }
        if (
          state.phase !== "done" ||
          samePlan(baseState, state) ||
          results.some((shown) => samePlan(shown.state, state))
        )
          return;
        const approved = priceReview.find(
          ({ outcome, price }) =>
            outcome === index && price.status === "priced" && !price.aboveCeiling,
        );
        if (approved) results.push({ title: copy.pricedPlan(approved.price.label), state });
      } else if (!states.slice(0, index).some(({ phase }) => isWorking(phase))) {
        const previous = results.flatMap(({ state }) =>
          state.phase === "done" ? [state.envelope.payload] : [],
        );
        const automatic = visibleAutomatic(state, baseAnswer, previous);
        if (automatic)
          results.push({ title: automatic.kind === "roll" ? copy.rollPlan : copy.bankPlan, state });
      }
    });
  }
  const team = squad.entry.team_name ?? squad.entry.manager_name;
  const alternative = results.find(({ state }) => state.phase === "done")?.state;
  const revisionAnswer =
    baseAnswer ?? (alternative?.phase === "done" ? alternative.envelope.payload : undefined);
  const revised = revisionAnswer && summarizeRevision(revisionAnswer);
  const bank = draft.min_bank;
  const bankRule =
    bank &&
    (bank.week === undefined
      ? copy.minimumBank(money(bank.tenths, locale))
      : copy.minimumWeekBank(money(bank.tenths, locale), squad.gameweek + bank.week - 1));
  const teamPath =
    squad.league_id === 0
      ? entryAddress(squad.entry.entry_id)
      : memberAddress(squad.league_id, squad.entry.entry_id);

  return (
    <div className={styles.page}>
      <header className={styles.header}>
        <Link to={teamPath}>{copy.back}</Link>
        <h1>LLMOPT</h1>
        <p>
          {team ? `${team} · ` : ""}
          {copy.week} {squad.gameweek}
        </p>
      </header>
      {!ORIGIN && (
        <p className={styles.notice} role="status">
          {copy.serviceUnavailable}
        </p>
      )}
      {ORIGIN && roster.isError && (
        <p className={styles.notice} role="status">
          {copy.rosterUnavailable}{" "}
          <button className={styles.textButton} onClick={() => void roster.refetch()} type="button">
            {copy.retry}
          </button>
        </p>
      )}
      <section className={styles.workspace} aria-label={copy.chat}>
        {conversation.length > 0 && (
          <ol className={styles.conversation} aria-live="polite">
            {conversation.map(({ id, role, message }) => (
              <li key={id} data-role={role}>
                <strong>{role === "user" ? copy.user : "LLMOPT"}</strong>
                <span>{message}</span>
              </li>
            ))}
          </ol>
        )}
        <form className={styles.chat} onSubmit={(event) => void send(event)}>
          <label htmlFor="llmopt-message">{copy.chat}</label>
          <textarea
            id="llmopt-message"
            ref={chatInput}
            placeholder={copy.placeholder}
            value={message}
            maxLength={MAX_MESSAGE_LENGTH}
            rows={2}
            onChange={(event) => setMessage(event.target.value)}
            disabled={!ORIGIN || reading || checkingSquad}
          />
          <button
            className={styles.primary}
            type="submit"
            disabled={!ORIGIN || busy || roster.isPending || !message.trim()}
          >
            {reading ? copy.interpreting : copy.send}
          </button>
          {clarification && (
            <button
              className={styles.secondary}
              type="button"
              disabled={busy}
              onClick={() => setQuestion()}
            >
              {copy.dismissQuestion}
            </button>
          )}
        </form>
        <label className={styles.windowChoice}>
          {copy.window}
          <select
            value={plans.window}
            disabled={busy}
            onChange={(event) => change({ ...draft, window: event.target.value === "3" ? 3 : 1 })}
          >
            <option value={1} disabled={needsThreeWeeks(draft)}>
              {copy.oneWeek}
            </option>
            <option value={3}>{copy.threeWeeks}</option>
          </select>
        </label>
        {feedback && (
          <p role="status" className={styles.notice}>
            {feedback}
          </p>
        )}
        <RuleEditor draft={draft} players={players} copy={copy} disabled={busy} change={change} />
        {(Boolean(draft.keep_weeks?.length) || bankRule) && (
          <div className={styles.ruleGroup}>
            <h3>{copy.revisionRules}</h3>
            <ul>
              {draft.keep_weeks?.map((week) => {
                const label = copy.frozenWeek(squad.gameweek + week - 1);
                return (
                  <li key={week}>
                    {label}
                    <button
                      className={styles.remove}
                      type="button"
                      disabled={busy}
                      aria-label={`${copy.remove} · ${label}`}
                      onClick={() => {
                        const keep = draft.keep_weeks?.filter((item) => item !== week);
                        change({ ...draft, keep_weeks: keep?.length ? keep : undefined });
                      }}
                    >
                      ×
                    </button>
                  </li>
                );
              })}
              {bankRule && (
                <li>
                  {bankRule}
                  <button
                    className={styles.remove}
                    type="button"
                    disabled={busy}
                    aria-label={`${copy.remove} · ${bankRule}`}
                    onClick={() => change({ ...draft, min_bank: undefined })}
                  >
                    ×
                  </button>
                </li>
              )}
            </ul>
          </div>
        )}
        {draft.comparison && draft.soft.length > 0 && (
          <p className={styles.muted}>{copy.comparisonScope}</p>
        )}
        {hardConflict && (
          <p role="alert" className={styles.notice}>
            {hardConflict}
          </p>
        )}
        {closed && (
          <p role="status" className={styles.notice}>
            {copy.deadline}
          </p>
        )}
        {fixturesUnavailable && deadline === null && (
          <p role="status" className={styles.notice}>
            {copy.deadlineUnknown}
          </p>
        )}
        <button
          className={styles.primary}
          ref={computeButton}
          type="button"
          disabled={
            busy ||
            clarification !== undefined ||
            !ORIGIN ||
            !squad.source_snapshot_id ||
            closed ||
            deadline === null ||
            !canCalculate ||
            basisChanged
          }
          onClick={() => void compute()}
        >
          {checkingSquad ? copy.checkSquad : computing ? copy.computing : copy.compute}
        </button>
        {basisChanged && (
          <p className={styles.notice} role="status">
            {copy.newSquad}{" "}
            <button
              type="button"
              className={styles.textButton}
              onClick={() => window.location.reload()}
            >
              {copy.reload}
            </button>
          </p>
        )}
      </section>
      {reference && <RevisionComparison previous={reference} revised={revised} />}
      {run && (
        <section
          className={styles.results}
          aria-label={copy.results}
          aria-busy={isWorking(baseState.phase)}
        >
          <h2>{copy.results}</h2>
          <div className={styles.planGrid}>
            {(run.baseRequest || run.baseConflict) && (
              <PlanResult
                title={copy[run.baseTitle]}
                state={base.state}
                squad={squad}
                conflict={run.baseConflict}
                conflictMessage={
                  run.baseConflict ? explainBranchConflict(run.baseTitle) : undefined
                }
                diagnosis={diagnosis(base.state)}
                prices={priceReview.map(({ price }) => price)}
                onRevise={baseAnswer ? () => revisePlan(baseAnswer) : undefined}
                reviseDisabled={busy}
              />
            )}
            {results.map(({ title, state, conflict, conflictMessage }) => (
              <PlanResult
                key={title}
                title={title}
                state={state}
                squad={squad}
                baseline={baseAnswer}
                conflict={conflict}
                conflictMessage={conflictMessage}
                diagnosis={diagnosis(state)}
                onRevise={
                  state.phase === "done" ? () => revisePlan(state.envelope.payload) : undefined
                }
                reviseDisabled={busy}
              />
            ))}
          </div>
          {same && (
            <p role="status" className={styles.muted}>
              {copy.same}
            </p>
          )}
        </section>
      )}
    </div>
  );
}

export function LLMOptPage() {
  const { messages, language } = useLanguage();
  const copy = LLMOPT_COPY[language];
  const { entryId: entryParam } = useParams();
  const entryId = Number(entryParam);
  const valid = Number.isSafeInteger(entryId) && entryId > 0;
  const result = useEntrySquad(entryId, valid);
  if (!valid) return <EmptyState page title={messages.leagueMembers.invalidEntry} />;
  if (result.isPending) return <PageLoading label={messages.common.loading} />;
  if (result.isError) return <EmptyState page title={copy.squadUnavailable} />;
  return <Session key={squadBasis(result.data.payload)} squad={result.data.payload} />;
}
