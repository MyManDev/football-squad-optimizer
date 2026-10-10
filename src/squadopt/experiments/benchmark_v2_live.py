"""One prospective Benchmark V2 reading from explicitly frozen live captures."""

import hashlib
import json
from collections.abc import Mapping, Sequence
from dataclasses import dataclass
from pathlib import Path
from statistics import mean, median
from typing import Any

import pandas as pd

from squadopt.data.atomic import document_bytes, write_bytes_once
from squadopt.data.errors import DataError
from squadopt.data.snapshots import CapturedSnapshot
from squadopt.data.sources.fpl_live import (
    BOOTSTRAP_PAYLOAD,
    entry_history_payload,
    entry_picks_payload,
    fpl_entry_picks,
    gameweek_deadlines,
    live_event_outcomes,
    live_payload,
    player_codes,
    player_snapshot,
    scored_gameweeks,
)
from squadopt.data.timestamps import as_instant
from squadopt.evaluation import (
    OWNERSHIP_TEMPLATE_V2,
    TOP_MANAGER_COHORT_VERSION,
    EvaluationValidationError,
    FrozenSquadDecision,
    ScoringPolicy,
    audit_unconstrained_template_v1,
    build_constrained_ownership_template,
    score_frozen_squad_decision,
)
from squadopt.experiments.benchmark_v2 import (
    _decision_from_record,
    _v1_score,
    validate_top100_capture,
)
from squadopt.optimization import OptimizationConfig
from squadopt.scenarios.rivals import template_rival_from_ownership

LIVE_CONTRACT = "benchmark_v2_live_v1"
SEASON = "2026-27"
MINIMUM_WEEKS = 8
READING_FILE = "benchmark-v2-live-2026-27.json"
CLAIM_FILE = "benchmark-v2-live-2026-27.reading"
# Match the named committed-measurement limits in scripts/_experiment_cli.py.
MEASUREMENT_DETERMINISTIC_TIME_LIMIT = 5.0
MEASUREMENT_WALL_TIME_LIMIT_SECONDS = 600.0
# Stable exclusion codes. A record names why a week or a cohort entry is missing, never
# an exception class or a raw entry id.
WEEK_EXCLUSION_CODES = (
    "invalid_gameweek",
    "provenance_mismatch",
    "late_capture",
    "early_capture",
    "stale_cohort",
    "invalid_configuration",
    "unchecked_outcome",
    "insufficient_coverage",
    "missing_outcome",
    "invalid_capture",
)
ENTRY_EXCLUSION_CODES = ("chip_unresolved", "unreadable", "invalid_picks", "missing_outcome")


class LiveWeekRefusal(EvaluationValidationError):
    """A refused week, with its stable exclusion code and any cohort coverage already read."""

    def __init__(
        self, code: str, message: str, *, coverage: Mapping[str, Any] | None = None
    ) -> None:
        if code not in WEEK_EXCLUSION_CODES:
            raise ValueError(f"Unknown Benchmark V2 week exclusion code {code!r}.")
        super().__init__(message)
        self.code = code
        self.coverage = dict(coverage or {})


class UnresolvedChipError(EvaluationValidationError):
    """An entry played a roster-changing chip that the protocol does not yet normalize."""


class _MissingEntryOutcome(EvaluationValidationError):
    """A cohort entry names a player without a realized outcome."""


@dataclass(frozen=True)
class LiveBenchmarkWeek:
    gameweek: int
    decision: CapturedSnapshot
    freeze: CapturedSnapshot
    cohort: CapturedSnapshot
    picks: CapturedSnapshot
    outcome: CapturedSnapshot


@dataclass(frozen=True)
class PreparedLiveWeek:
    gameweek: int
    system: FrozenSquadDecision
    template: FrozenSquadDecision
    managers: tuple[FrozenSquadDecision, ...]
    outcomes: pd.DataFrame
    provenance: Mapping[str, Any]
    v1_starters: tuple[object, ...]
    v1_captain: object


def _json(snapshot: CapturedSnapshot, name: str) -> Any:
    document = json.loads(snapshot.payloads[name])
    if not isinstance(document, dict):
        raise EvaluationValidationError("Benchmark payload must be a JSON object.")
    return document


def _original_picks(raw: bytes, *, entry_id: int, gameweek: int) -> bytes:
    """Reverse recorded FPL autosub position swaps, then normalize chip multipliers."""
    document = json.loads(raw)
    if document.get("active_chip") not in (None, "bboost", "3xc"):
        raise UnresolvedChipError(
            "Roster-changing chip normalization needs a frozen protocol decision."
        )
    picks = {row["element"]: dict(row) for row in document["picks"]}
    changed: set[int] = set()
    for substitution in document.get("automatic_subs", []):
        outgoing, incoming = substitution["element_out"], substitution["element_in"]
        if (substitution.get("entry"), substitution.get("event")) != (entry_id, gameweek):
            raise EvaluationValidationError("Autosubstitution belongs to another entry/week.")
        if outgoing in changed or incoming in changed or outgoing == incoming:
            raise EvaluationValidationError("Ambiguous captured autosubstitutions.")
        changed.update((outgoing, incoming))
        # Some captured representations already retain the original positions.
        if picks[outgoing]["position"] > 11 and picks[incoming]["position"] <= 11:
            picks[outgoing]["position"], picks[incoming]["position"] = (
                picks[incoming]["position"],
                picks[outgoing]["position"],
            )
        elif not (picks[outgoing]["position"] <= 11 and picks[incoming]["position"] > 11):
            raise EvaluationValidationError(
                "Autosubstitution cannot recover an original bench slot."
            )
    for row in picks.values():
        row["multiplier"] = 2 if row["is_captain"] else int(row["position"] <= 11)
    document["picks"] = sorted(picks.values(), key=lambda row: row["position"])
    document["active_chip"] = None
    document["automatic_subs"] = []
    return json.dumps(document).encode()


def prepare_live_week(week: LiveBenchmarkWeek) -> PreparedLiveWeek:
    """Validate timing, identities and complete scoring inputs before any comparison."""
    if type(week.gameweek) is not int or not 3 <= week.gameweek <= 38:
        raise LiveWeekRefusal("invalid_gameweek", "Live Benchmark V2 requires gameweeks 3 to 38.")
    sources = {
        "decision": "fpl-live",
        "freeze": "fpl-benchmark-decision",
        "cohort": "fpl-top100",
        "picks": "fpl-benchmark-picks",
        "outcome": "fpl-live",
    }
    for role, source in sources.items():
        snapshot = getattr(week, role)
        if snapshot.metadata.source != source:
            raise LiveWeekRefusal(
                "provenance_mismatch", f"Invalid live Benchmark V2 {role} source."
            )
        # A live-only admission window keeps archived seasons outside this reader.
        at = as_instant(snapshot.metadata.captured_at_utc)
        if not as_instant("2026-08-01T00:00:00Z") <= at < as_instant("2027-08-01T00:00:00Z"):
            raise LiveWeekRefusal(
                "provenance_mismatch", "Live Benchmark V2 refuses another season."
            )
    bootstrap = week.decision.payloads[BOOTSTRAP_PAYLOAD]
    deadlines = {item.gameweek: item.deadline_utc for item in gameweek_deadlines(bootstrap)}
    deadline = as_instant(deadlines[week.gameweek])
    for snapshot in (week.decision, week.freeze, week.cohort):
        if as_instant(snapshot.metadata.captured_at_utc) >= deadline:
            raise LiveWeekRefusal(
                "late_capture", "Benchmark decision, freeze and cohort must precede deadline."
            )
    # As-of membership: a cohort taken before the previous deadline ranks an older week.
    previous = deadlines.get(week.gameweek - 1)
    if previous is None or as_instant(week.cohort.metadata.captured_at_utc) <= as_instant(previous):
        raise LiveWeekRefusal(
            "stale_cohort", "Benchmark cohort must follow the previous gameweek deadline."
        )
    for snapshot in (week.picks, week.outcome):
        if as_instant(snapshot.metadata.captured_at_utc) < deadline:
            raise LiveWeekRefusal(
                "early_capture", "Benchmark picks and outcomes cannot precede deadline."
            )
    if week.freeze.payloads[BOOTSTRAP_PAYLOAD] != bootstrap:
        raise LiveWeekRefusal(
            "provenance_mismatch", "Benchmark freeze changed the decision-time ownership pool."
        )
    binding = _json(week.freeze, "benchmark.json")
    picks_binding = _json(week.picks, "benchmark.json")
    for record in (binding, picks_binding):
        if (record.get("season"), record.get("gameweek"), record.get("cohort_snapshot_id")) != (
            SEASON,
            week.gameweek,
            week.cohort.metadata.snapshot_id,
        ):
            raise LiveWeekRefusal(
                "provenance_mismatch", "Benchmark capture differs from its frozen cohort/week."
            )
    if (binding.get("decision_snapshot_id"), binding.get("decision_fingerprint")) != (
        week.decision.metadata.snapshot_id,
        week.decision.metadata.fingerprint,
    ):
        raise LiveWeekRefusal(
            "provenance_mismatch", "Benchmark freeze differs from its decision capture."
        )
    frozen = _json(week.freeze, "system-decision.json")
    if (
        frozen.get("snapshot_id"),
        frozen.get("season"),
        frozen.get("gameweek"),
        frozen.get("captured_at_utc"),
    ) != (
        week.decision.metadata.snapshot_id,
        SEASON,
        week.gameweek,
        week.decision.metadata.captured_at_utc,
    ) or as_instant(frozen["deadline_utc"]) != deadline:
        raise LiveWeekRefusal(
            "provenance_mismatch", "Frozen system decision differs from the captured week."
        )
    if hashlib.sha256(week.freeze.payloads["system-decision.json"]).hexdigest() != binding.get(
        "system_decision_sha256"
    ):
        raise LiveWeekRefusal("provenance_mismatch", "Frozen system decision digest differs.")
    config_record = binding.get("template_configuration")
    if not isinstance(config_record, dict) or set(config_record) != {
        "budget_tenths",
        "max_players_per_team",
        "expected_points_scale",
    }:
        raise LiveWeekRefusal(
            "invalid_configuration", "Missing decision-time template configuration."
        )
    if config_record["max_players_per_team"] != 3 or config_record["expected_points_scale"] != 1000:
        raise LiveWeekRefusal(
            "invalid_configuration", "Template configuration changes the declared FPL policy."
        )
    config = OptimizationConfig(
        **config_record,
        solver_deterministic_time_limit=MEASUREMENT_DETERMINISTIC_TIME_LIMIT,
        solver_time_limit_seconds=MEASUREMENT_WALL_TIME_LIMIT_SECONDS,
    )
    pool = player_snapshot(bootstrap)
    ownership = {
        row["code"]: float(row["selected_by_percent"]) for row in json.loads(bootstrap)["elements"]
    }
    pool = pool.assign(ownership=pool.player_id.map(ownership))
    indexed = pool.set_index("player_id", drop=False)
    system = FrozenSquadDecision(
        squad=indexed.loc[frozen["squad_player_ids"]].reset_index(drop=True),
        starting_xi=tuple(frozen["starting_xi_player_ids"]),
        bench=tuple(frozen["ordered_bench_player_ids"]),
        captain_id=frozen["captain_player_id"],
        vice_captain_id=frozen["vice_captain_player_id"],
        completion_policy=str(frozen["completion_policy"]),
    )
    template = build_constrained_ownership_template(pool, config).decision
    v1_template = template_rival_from_ownership(pool, optimization_config=config)
    v1_audit = audit_unconstrained_template_v1(pool, v1_template.starter_ids, config)
    cohort, _ = validate_top100_capture(week.cohort, target_gameweek=week.gameweek)
    if as_instant(cohort.deadline_timestamp_utc) != deadline:
        raise LiveWeekRefusal(
            "provenance_mismatch", "Cohort deadline differs from the frozen decision."
        )
    for snapshot in (week.picks, week.outcome):
        observed = {
            item.gameweek: as_instant(item.deadline_utc)
            for item in gameweek_deadlines(snapshot.payloads[BOOTSTRAP_PAYLOAD])
        }
        if observed.get(week.gameweek) != deadline:
            raise LiveWeekRefusal(
                "provenance_mismatch", "Benchmark picks or outcomes name a different deadline."
            )
    if week.gameweek not in scored_gameweeks(week.outcome.payloads[BOOTSTRAP_PAYLOAD]):
        raise LiveWeekRefusal("unchecked_outcome", "Benchmark outcome is not finished and checked.")
    outcomes = live_event_outcomes(
        week.outcome.payloads[live_payload(week.gameweek)],
        week.outcome.payloads[BOOTSTRAP_PAYLOAD],
        gameweek=week.gameweek,
    )
    codes = player_codes(week.picks.payloads[BOOTSTRAP_PAYLOAD])
    managers = []
    entry_exclusions = dict.fromkeys(ENTRY_EXCLUSION_CODES, 0)
    outcome_ids = set(outcomes.player_id)
    for entry_id in cohort.entry_ids:
        picks_name = entry_picks_payload(entry_id, week.gameweek)
        history_name = entry_history_payload(entry_id)
        if picks_name not in week.picks.payloads or history_name not in week.picks.payloads:
            # The collector leaves an unreadable member's payloads out.
            entry_exclusions["unreadable"] += 1
            continue
        try:
            record = fpl_entry_picks(
                _original_picks(
                    week.picks.payloads[picks_name],
                    entry_id=entry_id,
                    gameweek=week.gameweek,
                ),
                week.picks.payloads[history_name],
                entry_id=entry_id,
                season=SEASON,
                gameweek=week.gameweek,
                source_snapshot_id=week.picks.metadata.snapshot_id,
            )
            decision = _decision_from_record(record, player_pool=pool, codes=codes)
            if not set(decision.squad.player_id) <= outcome_ids:
                raise _MissingEntryOutcome("Missing cohort player's realized outcome.")
            score_frozen_squad_decision(decision, outcomes.assign(total_points=0))
        except UnresolvedChipError:
            entry_exclusions["chip_unresolved"] += 1
        except _MissingEntryOutcome:
            entry_exclusions["missing_outcome"] += 1
        except (DataError, EvaluationValidationError, KeyError, ValueError, TypeError):
            entry_exclusions["invalid_picks"] += 1
        else:
            managers.append(decision)
    coverage = {
        "cohort_valid": len(managers),
        "cohort_excluded": sum(entry_exclusions.values()),
        "cohort_exclusions": entry_exclusions,
    }
    if len(managers) < 80:
        raise LiveWeekRefusal(
            "insufficient_coverage",
            "Benchmark cohort has fewer than 80 valid frozen members.",
            coverage=coverage,
        )
    for decision in (system, template):
        if not set(decision.squad.player_id) <= outcome_ids:
            raise LiveWeekRefusal(
                "missing_outcome",
                "Missing system or template realized outcome.",
                coverage=coverage,
            )
        score_frozen_squad_decision(decision, outcomes.assign(total_points=0))
    return PreparedLiveWeek(
        week.gameweek,
        system,
        template,
        tuple(managers),
        outcomes,
        {
            "captures": {
                role: {
                    "snapshot_id": getattr(week, role).metadata.snapshot_id,
                    "fingerprint": getattr(week, role).metadata.fingerprint,
                    "captured_at_utc": getattr(week, role).metadata.captured_at_utc,
                }
                for role in sources
            },
            "deadline_utc": deadlines[week.gameweek],
            "template_configuration": config_record,
            "solver_configuration": {
                "deterministic_time_limit": config.solver_deterministic_time_limit,
                "wall_time_limit_seconds": config.solver_time_limit_seconds,
                "binding_limit": "deterministic_time",
            },
            "system_decision_sha256": binding["system_decision_sha256"],
            "model_version": frozen.get("model_version"),
            **coverage,
            "v1_feasibility": dict(v1_audit),
        },
        tuple(v1_template.starter_ids),
        v1_template.captain_id,
    )


def _score(decision: FrozenSquadDecision, outcomes: pd.DataFrame) -> dict[str, Any]:
    scored = score_frozen_squad_decision(decision, outcomes)
    minutes = dict(outcomes[["player_id", "minutes"]].itertuples(index=False, name=None))
    points = dict(outcomes[["player_id", "total_points"]].itertuples(index=False, name=None))
    previous = _v1_score(decision.starting_xi, decision.captain_id, points)
    return {
        "points": scored.total_points,
        "zero_minute_starters": int(sum(minutes[player] == 0 for player in decision.starting_xi)),
        "v1_points": previous,
        "v1_to_v2_score_change": scored.total_points - previous,
        "autosub_recovery": scored.autosub_points,
        "bench_contribution": scored.autosub_points,
        "vice_captain_recovery": scored.captain_bonus_points
        if (scored.captain_bonus_player_id == decision.vice_captain_id)
        else 0.0,
    }


def read_live_benchmark_once(
    weeks: Sequence[LiveBenchmarkWeek],
    *,
    record_root: Path,
    repository_commit: str,
    preregistration_sha256: str,
) -> dict[str, Any]:
    """Refuse early/duplicate readings; claim once before calculating paired scores."""
    claim = record_root / CLAIM_FILE
    if claim.exists() or (record_root / READING_FILE).exists():
        raise EvaluationValidationError("Benchmark V2 live reading has already been claimed.")
    if len(weeks) < MINIMUM_WEEKS:
        raise EvaluationValidationError("Benchmark V2 needs eight valid paired gameweeks.")
    if len({week.gameweek for week in weeks}) != len(weeks):
        raise EvaluationValidationError("Benchmark V2 gameweeks must be unique.")
    prepared: list[PreparedLiveWeek] = []
    exclusions: list[dict[str, Any]] = []
    for week in sorted(weeks, key=lambda item: item.gameweek):
        try:
            prepared.append(prepare_live_week(week))
        except LiveWeekRefusal as error:
            # Report stable codes and counts, never raw entry ids from parsing failures.
            exclusions.append({"gameweek": week.gameweek, "reason": error.code, **error.coverage})
        except (DataError, EvaluationValidationError, KeyError, ValueError, TypeError):
            exclusions.append({"gameweek": week.gameweek, "reason": "invalid_capture"})
    if len(prepared) < MINIMUM_WEEKS:
        raise EvaluationValidationError("Benchmark V2 needs eight valid paired gameweeks.")
    record_root.mkdir(parents=True, exist_ok=True)
    try:
        with claim.open("xb") as handle:
            handle.write(
                document_bytes(
                    {
                        "contract_version": LIVE_CONTRACT,
                        "repository_commit": repository_commit,
                        "preregistration_sha256": preregistration_sha256,
                    }
                )
            )
    except FileExistsError as error:
        raise EvaluationValidationError(
            "Benchmark V2 live reading has already been claimed."
        ) from error
    rows = []
    for prepared_week in prepared:
        system = _score(prepared_week.system, prepared_week.outcomes)
        template = _score(prepared_week.template, prepared_week.outcomes)
        managers = [_score(decision, prepared_week.outcomes) for decision in prepared_week.managers]
        cohort = {key: mean(float(row[key]) for row in managers) for key in system}
        points = dict(
            prepared_week.outcomes[["player_id", "total_points"]].itertuples(index=False, name=None)
        )
        v1_template_points = (
            _v1_score(prepared_week.v1_starters, prepared_week.v1_captain, points)
            if (set(prepared_week.v1_starters) | {prepared_week.v1_captain}) <= points.keys()
            else None
        )
        rows.append(
            {
                "gameweek": prepared_week.gameweek,
                "system": system,
                "template": template,
                "cohort": cohort,
                "v1_template_points": v1_template_points,
                "system_minus_template": system["points"] - template["points"],
                "system_minus_cohort": system["points"] - cohort["points"],
                "provenance": dict(prepared_week.provenance),
            }
        )
    summary = {
        f"{stat}_{arm}": function(row[arm] for row in rows)
        for stat, function in (("mean", mean), ("median", median))
        for arm in ("system_minus_template", "system_minus_cohort")
    }
    result = {
        "contract_version": LIVE_CONTRACT,
        "season": SEASON,
        "scoring_basis": ScoringPolicy.OFFICIAL_AUTOSUB_CAPTAIN_V2.value,
        "template_policy": OWNERSHIP_TEMPLATE_V2,
        "cohort_policy": TOP_MANAGER_COHORT_VERSION,
        "paired_gameweeks": len(rows),
        "repository_commit": repository_commit,
        "preregistration_sha256": preregistration_sha256,
        "summary": summary,
        "per_season": {SEASON: summary},
        "rows": rows,
        "exclusions": exclusions,
        "locked_holdout_accessed": False,
        "interpretation": "eight_or_more_valid_paired_weeks"
        if len(rows) < 12
        else "twelve_or_more_valid_paired_weeks",
    }
    write_bytes_once(document_bytes(result), record_root / READING_FILE)
    write_bytes_once(
        render_live_reading_markdown(result).encode(),
        record_root / READING_FILE.replace(".json", ".md"),
    )
    return result


def render_live_reading_markdown(result: Mapping[str, Any]) -> str:
    """Render the Markdown twin with fixed decimals, every table in gameweek order."""

    def number(value: float) -> str:
        return f"{value:.3f}"

    def signed(value: float) -> str:
        return f"{value:+.3f}"

    summary = result["summary"]
    rows = sorted(result["rows"], key=lambda row: row["gameweek"])
    exclusions = sorted(result["exclusions"], key=lambda row: row["gameweek"])
    lines = [
        "# Benchmark V2 live reading",
        "",
        f"- Season: {result['season']}",
        f"- Contract: `{result['contract_version']}`",
        f"- Interpretation: `{result['interpretation']}`",
        f"- Scoring policy: `{result['scoring_basis']}`",
        f"- Template policy: `{result['template_policy']}`",
        f"- Cohort policy: `{result['cohort_policy']}`",
        f"- Repository commit: `{result['repository_commit']}`",
        f"- Preregistration SHA256: `{result['preregistration_sha256']}`",
        f"- Paired gameweeks: {result['paired_gameweeks']}",
        f"- Excluded gameweeks: {len(exclusions)}",
        "",
        "## Summary",
        "",
        "| Comparison | Mean | Median |",
        "| --- | ---: | ---: |",
        "| System minus template "
        f"| {signed(summary['mean_system_minus_template'])} "
        f"| {signed(summary['median_system_minus_template'])} |",
        "| System minus cohort "
        f"| {signed(summary['mean_system_minus_cohort'])} "
        f"| {signed(summary['median_system_minus_cohort'])} |",
        "",
        "## Paired gameweeks",
        "",
        "| GW | System | Template | Cohort | System minus template | System minus cohort "
        "| Cohort valid | Cohort excluded |",
        "| --- | ---: | ---: | ---: | ---: | ---: | ---: | ---: |",
    ]
    lines.extend(
        f"| {row['gameweek']} | {number(row['system']['points'])} "
        f"| {number(row['template']['points'])} | {number(row['cohort']['points'])} "
        f"| {signed(row['system_minus_template'])} | {signed(row['system_minus_cohort'])} "
        f"| {row['provenance']['cohort_valid']} | {row['provenance']['cohort_excluded']} |"
        for row in rows
    )
    lines.extend(["", "## Excluded gameweeks", ""])
    if exclusions:
        lines.extend(
            [
                "| GW | Reason | Cohort valid | Cohort excluded |",
                "| --- | --- | ---: | ---: |",
            ]
        )
        lines.extend(
            f"| {row['gameweek']} | `{row['reason']}` "
            f"| {row.get('cohort_valid', 'not read')} | {row.get('cohort_excluded', 'not read')} |"
            for row in exclusions
        )
    else:
        lines.append("None.")
    return "\n".join(lines) + "\n"
