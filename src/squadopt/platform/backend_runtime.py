"""The composition root: the one place the backend's parts are wired to each other.

Every collaborator the advice backend needs already existed — a file-backed job queue, an
immutable cache, a read store, a submission service, a worker step, an injectable app
factory. What did not exist was anything that built them *together*, so ``create_app()``
came up with ``advice_store=None`` and the advice routes answered 503. This module is that
assembly and nothing more: no framework, no service locator, no second lifecycle. It reads
the deployment's configuration from the server's own environment, opens one store, and
hands the same objects to both processes.

Two rules shape it.

**One store, two processes.** The api writes the queue the worker reads and both must see
the same immutable cache, so every root is derived from a single configured store path
rather than configured separately — a deployment cannot half-wire itself into two stores
that agree about nothing (ADR 0006).

**Nothing about the answer comes from the client.** Roots, the capture, the handoff, the
CORS allowlist and the season are all server configuration. A request names a league, a
member, a strategy and a window; it never names a path.

The api process is not built here. This module may not import ``squadopt.api`` — the api
layer sits *above* platform — so the FastAPI wiring lives in ``squadopt.api.runtime`` and
imports this. That is not a workaround; it is the layer rule doing its job.
"""

from __future__ import annotations

import hashlib
import json
import os
import threading
import time
from collections.abc import Callable, Mapping
from dataclasses import dataclass, replace
from pathlib import Path

from squadopt.application.advice import AdviseEntryRequest
from squadopt.application.advice_capabilities import (
    COMPUTED_MODE,
    COMPUTED_WINDOW,
    advice_capabilities,
    menu_capabilities,
)
from squadopt.application.advice_menu import held_member_chips
from squadopt.application.league_views import LEAGUE_VIEW_CONTRACT_VERSION
from squadopt.application.strategies import STRATEGY_CATALOG
from squadopt.data.errors import SourceRevisionError
from squadopt.data.source_revision import require_source_revision
from squadopt.data.sources import FPL_LIVE_SOURCE
from squadopt.live import SeasonRules, read_season_rules
from squadopt.platform.advice_cache import FileAdviceCache
from squadopt.platform.advice_job_spec import AdviceJobSpecStore, FileAdviceJobSpecStore
from squadopt.platform.advice_observability import AdviceLog, AdviceMetrics, readiness_report
from squadopt.platform.advice_queue import FileJobQueue
from squadopt.platform.advice_read import (
    AdviceBackendNotReadyError,
    AdviceReadStore,
    AdviceRequestContext,
    FileLeagueDirectory,
)
from squadopt.platform.advice_submit import AdviceSubmitService, FixedWindowRateLimiter
from squadopt.platform.advice_switches import (
    AdviceSwitchInputs,
    discovery_signature,
    load_switch_inputs,
)
from squadopt.platform.capture_context import (
    AdviceCaptureContext,
    CaptureIdentity,
    CapturePicksProvider,
    handoff_fingerprint_for,
    latest_snapshot_id,
    load_capture_context,
    load_capture_identity,
)
from squadopt.platform.store_probe import StoreProbeResult, probe_store

__all__ = [
    "CANONICAL_SITE_ORIGIN",
    "PAGES_ALIAS_ORIGIN",
    "SITE_ORIGINS",
    "BackendConfig",
    "BackendConfigError",
    "CaptureContextProvider",
    "StoreProbeGate",
    "backend_from_environment",
    "build_backend",
    "computable_strategies",
    "configuration_fingerprint",
]

CANONICAL_SITE_ORIGIN = "https://squadopt.mymandev.com"
"""The address members open, and therefore the ``Origin`` a real browser sends.

The Pages project answers on two hostnames. This is the one that is reachable: from the
owner's network `squadopt.pages.dev` accepts the TCP connection and is then reset before any
TLS record, while the same request to the same Cloudflare address under another hostname
answers 200 (`docs/architecture/decisions/0004-cloudflare-pages-deployment.md`).
"""

PAGES_ALIAS_ORIGIN = "https://squadopt.pages.dev"
"""The project alias. Still served, still deployed to, and still allowed — it is what CI and
anyone outside the filtered networks uses — but it is not the address given to members."""

SITE_ORIGINS: tuple[str, ...] = (CANONICAL_SITE_ORIGIN, PAGES_ALIAS_ORIGIN)
"""Every hostname the site is published on, canonical first. The CORS allowlist the
deployment sets is this tuple; it is a named fact here so the runbook cannot drift from it.

This is deliberately *not* the ``BackendConfig.allowed_origins`` default. An unset
``SQUADOPT_BACKEND_ALLOWED_ORIGINS`` must keep meaning no cross-origin access at all, so a
deployment that forgets the variable fails closed rather than inheriting an allowlist.
"""

DEFAULT_RATE_LIMIT = 30
DEFAULT_RATE_WINDOW_SECONDS = 60.0
# Long enough that a readiness poll is not a syscall storm, short enough that a store
# which stops working is noticed in the same minute it does.
DEFAULT_PROBE_RECHECK_SECONDS = 30.0


class BackendConfigError(ValueError):
    """The deployment's configuration cannot describe a runnable backend."""


def computable_strategies() -> dict[str, bool]:
    """Every strategy this deployment computes, mapped to whether it needs a rival.

    Derived from the catalogue rather than listed, and derived with **the same condition
    ``advise_entry`` applies** — a band that reaches the solver. A read side that admitted
    a strategy the writer refuses would accept requests nobody can ever answer.
    """

    return {slug: value.requires_rival for slug, value in advice_capabilities().items()}


def configuration_fingerprint() -> str:
    """SHA-256 of the settings that can change an answer.

    Paths are deliberately absent. Where the store is mounted is deployment placement, not
    computation: moving the mount must not invalidate a cache whose entries are still
    correct. What is here is what a different value of would make an old answer wrong —
    the served document's contract, the computed mode and window, and the catalogue's
    bands, which are the constraints the solver actually receives.

    The two switches' rule versions (``TOP100_PRICE_BASIS``, ``MANAGERS_WORD_RULE_VERSION``)
    are deliberately **not** here. This digest is in every plain key already written, so
    adding a field would orphan all of them to version something a plain answer never
    used. They are hashed into the switched-on part of a key instead
    (``advice_switches.switch_identity``), where they reach exactly the answers they can
    change.
    """

    document = {
        "contract_version": "backend_configuration_v1",
        "advice_document_contract": LEAGUE_VIEW_CONTRACT_VERSION,
        "computed_mode": COMPUTED_MODE,
        "computed_window": COMPUTED_WINDOW,
        "strategy_bands": {
            slug: [
                STRATEGY_CATALOG[slug].constraints.overlap_floor,
                STRATEGY_CATALOG[slug].constraints.overlap_ceiling,
            ]
            for slug in sorted(computable_strategies())
            if slug in STRATEGY_CATALOG
        },
    }
    encoded = json.dumps(document, sort_keys=True, separators=(",", ":")).encode("utf-8")
    return hashlib.sha256(encoded).hexdigest()


def _repository_commit() -> str:
    """The commit this deployment runs, resolved by the one resolver that answers that.

    An **identity** use, so it refuses rather than publishing absence: this value is hashed
    into ``advice_cache_key`` and stored on the job spec, and a key assembled without one of
    its ingredients is a key that collides across builds. A deployment that cannot name its
    own code may not fill a cache.

    It deliberately does not ask whether the checkout matched. A container image carries no
    checkout to compare against -- that is why the build stamps
    ``SQUADOPT_REPOSITORY_COMMIT`` in -- and a developer running two processes out of a tree
    they are editing still needs a cache key, which the commit alone gives them.
    """

    try:
        return require_source_revision().commit
    except SourceRevisionError as error:
        raise BackendConfigError(
            "Could not resolve a 40-character repository commit; set "
            "SQUADOPT_REPOSITORY_COMMIT. It is part of every answer's identity, so a "
            "deployment that cannot name its own code may not fill a cache."
        ) from error


@dataclass(frozen=True, slots=True)
class BackendConfig:
    """Everything the deployment tells the backend, and nowhere else it may look."""

    store_root: Path
    """The one shared ReadWrite mount. The queue and the cache are derived from it, so
    the api and the worker cannot be pointed at two different stores."""
    site_data_root: Path
    """What ops publishes: the league tree the read side answers ``connected`` from."""
    snapshot_root: Path
    handoff_root: Path
    allowed_origins: tuple[str, ...] = ()
    season: str | None = None
    rate_limit: int = DEFAULT_RATE_LIMIT
    rate_window_seconds: float = DEFAULT_RATE_WINDOW_SECONDS
    artifact_root: Path | None = None
    """The repository's ``artifacts/`` directory, where the weekly run leaves the Top 100
    evidence export (``phase_b/``) and the rotation table (``rotation/``). Optional: unset,
    neither switch is offered and the backend answers exactly what it did before them."""
    club_news_source: Path | None = None
    """The club-news fixture file, or a club-news capture directory under the snapshot
    root, that the rotation table was coded from. The manager's word needs both this and
    ``artifact_root``."""

    @property
    def queue_root(self) -> Path:
        return self.store_root / "jobs"

    @property
    def cache_root(self) -> Path:
        return self.store_root / "cache"

    @property
    def spec_root(self) -> Path:
        return self.store_root / "specs"

    @classmethod
    def from_environment(cls, environ: Mapping[str, str] | None = None) -> BackendConfig:
        """Read the configuration, naming every variable that is missing at once."""

        source = os.environ if environ is None else environ
        required = {
            "store_root": "SQUADOPT_BACKEND_STORE_ROOT",
            "site_data_root": "SQUADOPT_BACKEND_SITE_DATA_ROOT",
            "snapshot_root": "SQUADOPT_BACKEND_SNAPSHOT_ROOT",
            "handoff_root": "SQUADOPT_BACKEND_HANDOFF_ROOT",
        }
        values: dict[str, Path] = {}
        missing: list[str] = []
        for field_name, variable in required.items():
            raw = source.get(variable, "").strip()
            if not raw:
                missing.append(variable)
                continue
            values[field_name] = Path(raw)
        if missing:
            raise BackendConfigError(f"Unset backend configuration: {', '.join(sorted(missing))}.")
        origins = tuple(
            origin.strip()
            for origin in source.get("SQUADOPT_BACKEND_ALLOWED_ORIGINS", "").split(",")
            if origin.strip()
        )
        if "*" in origins:
            raise BackendConfigError(
                "SQUADOPT_BACKEND_ALLOWED_ORIGINS may not contain a wildcard; the "
                "allowlist is the Pages domains (ADR 0006)."
            )
        season = source.get("SQUADOPT_BACKEND_SEASON", "").strip() or None
        artifact_root = source.get("SQUADOPT_BACKEND_ARTIFACT_ROOT", "").strip()
        club_news_source = source.get("SQUADOPT_BACKEND_CLUB_NEWS_SOURCE", "").strip()
        return cls(
            store_root=values["store_root"],
            site_data_root=values["site_data_root"],
            snapshot_root=values["snapshot_root"],
            handoff_root=values["handoff_root"],
            allowed_origins=origins,
            season=season,
            rate_limit=_positive_int(source, "SQUADOPT_BACKEND_RATE_LIMIT", DEFAULT_RATE_LIMIT),
            rate_window_seconds=_positive_float(
                source, "SQUADOPT_BACKEND_RATE_WINDOW_SECONDS", DEFAULT_RATE_WINDOW_SECONDS
            ),
            artifact_root=Path(artifact_root) if artifact_root else None,
            club_news_source=Path(club_news_source) if club_news_source else None,
        )


def _positive_int(source: Mapping[str, str], variable: str, default: int) -> int:
    raw = source.get(variable, "").strip()
    if not raw:
        return default
    try:
        value = int(raw)
    except ValueError as error:
        raise BackendConfigError(f"{variable} must be an integer, got {raw!r}.") from error
    if value < 1:
        raise BackendConfigError(f"{variable} must be at least 1, got {value}.")
    return value


def _positive_float(source: Mapping[str, str], variable: str, default: float) -> float:
    raw = source.get(variable, "").strip()
    if not raw:
        return default
    try:
        value = float(raw)
    except ValueError as error:
        raise BackendConfigError(f"{variable} must be a number, got {raw!r}.") from error
    if value <= 0.0:
        raise BackendConfigError(f"{variable} must be positive, got {value}.")
    return value


class CaptureContextProvider:
    """The current context, re-resolved cheaply and re-read only when it changes.

    ``current()`` runs inside a request, so it must be quick and it must never raise: a
    capture that cannot be read is a backend that is not ready, not a five-hundred on a
    member's page. The reason is kept for the operator, logged once per context rather
    than once per request.

    "Changed" means more than a new capture. A cache key is seven fields, and ops can
    republish a **corrected handoff for the capture already loaded** — same capture id,
    different projection. Keying the cache on the capture id alone made that correction
    invisible for the life of the process, so the handoff's fingerprint is re-read on
    every resolve. It is one small JSON; the expensive halves (the capture and its
    projection) stay cached behind it.

    Both processes use this class, which is what makes "the worker computes under the
    context the api validated" a property of the code rather than of a convention.
    """

    def __init__(
        self,
        config: BackendConfig,
        *,
        repository_commit: str,
        fingerprint: str,
        log: AdviceLog | None = None,
    ) -> None:
        self._config = config
        self._commit = repository_commit
        self._fingerprint = fingerprint
        self._log = log
        self._lock = threading.Lock()
        self._identity: CaptureIdentity | None = None
        self._context: AdviceCaptureContext | None = None
        self._switch_signature: tuple[object, ...] | None = None
        self._reported: dict[tuple[str, str], str] = {}
        self._directory = FileLeagueDirectory(config.site_data_root)
        self._chip_identity: CaptureIdentity | None = None
        self._chip_source: tuple[CapturePicksProvider, SeasonRules] | None = None
        self._chip_members: dict[tuple[int, int], tuple[str, ...] | None] = {}

    def identity(self) -> CaptureIdentity | None:
        """The current capture's identity, reading it only when the capture changed."""

        published = self._directory.published_snapshot_id()
        published_id = None if published is None else published[0]
        latest_id = latest_snapshot_id(self._config.snapshot_root)
        if published is None:
            if self._directory.published_capture_unusable_reason is not None:
                self._report(
                    "advice_published_capture_unusable",
                    reason=self._directory.published_capture_unusable_reason,
                )
        else:
            self._reported.pop(("advice_published_capture_unusable", ""), None)
            held = self._identity
            if (
                held is None or held.context.capture_snapshot_id != published_id
            ) and handoff_fingerprint_for(
                self._config.handoff_root, published[1], published[2], published[0]
            ) is None:
                if published_id != latest_id:
                    self._report(
                        "advice_context_unreadable",
                        snapshot_id=published_id,
                        reason="The published capture has no unambiguous matching handoff.",
                    )
                published_id = None
        if published_id is None and latest_id is None:
            # Names the source, because the root is shared: it can hold cohort and
            # elite-picks captures and still hold nothing this adapter can serve advice
            # from. "No capture at all" would send an operator to look at the mount.
            self._report(
                "advice_context_absent",
                reason=f"no {FPL_LIVE_SOURCE} capture under the snapshot root",
            )
            return None
        for snapshot_id in dict.fromkeys((published_id, latest_id)):
            if snapshot_id is None:
                continue
            identity = self._identity_for(snapshot_id)
            if identity is not None:
                return identity
        return None

    def _identity_for(self, snapshot_id: str) -> CaptureIdentity | None:
        with self._lock:
            held = self._identity
            if held is not None and held.context.capture_snapshot_id == snapshot_id:
                published = handoff_fingerprint_for(
                    self._config.handoff_root,
                    held.context.season,
                    held.context.gameweek,
                    snapshot_id,
                )
                if published == held.context.projection_handoff_fingerprint:
                    return held
                # A handoff that cannot be confirmed counts as changed: falling through
                # rebuilds, and a rebuild that fails reports unready rather than serving
                # answers under a projection identity nobody can name any more.
                self._identity = None
                self._context = None
            try:
                identity = load_capture_identity(
                    snapshot_root=self._config.snapshot_root,
                    snapshot_id=snapshot_id,
                    handoff_root=self._config.handoff_root,
                    advice_contract_version=LEAGUE_VIEW_CONTRACT_VERSION,
                    repository_commit=self._commit,
                    configuration_fingerprint=self._fingerprint,
                    season=self._config.season,
                )
            except Exception as error:  # readiness, not a request failure
                self._report(
                    "advice_context_unreadable", snapshot_id=snapshot_id, reason=str(error)
                )
                return None
            self._identity = identity
            self._context = None  # the projection belongs to the capture that produced it
            self._reported.pop(("advice_context_unreadable", snapshot_id), None)
            if self._log is not None:
                self._log.event(
                    "advice_context_loaded",
                    snapshot_id=identity.context.capture_snapshot_id,
                    season=identity.context.season,
                    gameweek=identity.context.gameweek,
                )
            return identity

    def current(self) -> AdviceRequestContext | None:
        identity = self.identity()
        return None if identity is None else identity.context

    def capture(self, context: AdviceRequestContext) -> AdviceCaptureContext | None:
        """The projected bundle for one **whole** context, or ``None`` if it is not current.

        The argument is the entire ``AdviceRequestContext`` rather than a capture id, and
        the comparison is equality over all seven fields, because all seven are in the
        cache key. Matching on the capture alone left three ways to compute an answer with
        inputs the key does not describe: a redeployed commit, a changed configuration, and
        a republished handoff. Answering "here is the current bundle" to a question about
        any other context is the silent-corruption path this exists to close.
        """

        identity = self.identity()
        if identity is None or identity.context != context:
            return None
        with self._lock:
            held = self._context
            if held is None or held.context != context:
                held = load_capture_context(identity)
                self._context = held
                self._switch_signature = None
            return self._with_current_switches(held)

    def _with_current_switches(self, held: AdviceCaptureContext) -> AdviceCaptureContext:
        """``held`` with the switch inputs as they are on disk now; called under the lock.

        The projection is kept for the life of the context; the switch inputs are read
        again whenever what they would be read from has changed. The api and the worker
        are two processes, and an export that lands after one of them looked must not
        leave them disagreeing about an address until the next capture.
        """

        if self._config.artifact_root is None:
            return held
        signature = discovery_signature(
            artifact_root=self._config.artifact_root,
            club_news_source=self._config.club_news_source,
            season=held.context.season,
            gameweek=held.context.gameweek,
            capture_snapshot_id=held.context.capture_snapshot_id,
        )
        if signature == self._switch_signature:
            return held
        try:
            switches = load_switch_inputs(
                artifact_root=self._config.artifact_root,
                club_news_source=self._config.club_news_source,
                snapshot_root=self._config.snapshot_root,
                inputs=held.inputs,
                projection=held.projection,
            )
        except Exception as error:  # an unreadable input turns a switch off, nothing more
            switches = AdviceSwitchInputs(notes=(f"switch inputs unreadable: {error}",))
        refreshed = replace(held, switches=switches)
        self._context = refreshed
        self._switch_signature = signature
        if self._log is not None:
            self._log.event(
                "advice_switch_inputs_loaded",
                snapshot_id=held.context.capture_snapshot_id,
                top100=switches.top100_counts is not None,
                managers_word=switches.manager_words is not None,
                notes=" | ".join(switches.notes),
            )
        return refreshed

    def switch_inputs(self, context: AdviceRequestContext) -> AdviceSwitchInputs | None:
        """What ``context`` offers the switches, or ``None`` when it is not current.

        Runs inside a request, so it never raises. Without an artifact root it answers
        at once and projects nothing, which keeps the api process the reader it was; with
        one, the first question about a switch pays for the projection once per context,
        because the Top 100 gate is the handoff's own and needs the projected table.
        """

        if self._config.artifact_root is None:
            identity = self.identity()
            if identity is None or identity.context != context:
                return None
            return AdviceSwitchInputs()
        try:
            bundle = self.capture(context)
        except Exception as error:
            self._report(
                "advice_switch_inputs_unreadable",
                snapshot_id=context.capture_snapshot_id,
                reason=str(error),
            )
            return AdviceSwitchInputs()
        return None if bundle is None else bundle.switches

    def held_chips(
        self, context: AdviceRequestContext, league_id: int, entries: tuple[int, ...]
    ) -> Mapping[int, tuple[str, ...] | None]:
        """Read the requested members once per identity, without projecting the capture."""
        identity = self.identity()
        if identity is None or identity.context != context:
            raise AdviceBackendNotReadyError("The capture context is no longer current.")
        with self._lock:
            if self._chip_identity is not identity:
                self._chip_identity = identity
                self._chip_source = None
                self._chip_members = {}
                try:
                    self._chip_source = (
                        CapturePicksProvider(identity.snapshot, identity.inputs.snapshot_id),
                        read_season_rules(identity.snapshot, season=identity.inputs.season),
                    )
                except Exception as error:
                    self._report(
                        "advice_chip_history_unreadable",
                        snapshot_id=context.capture_snapshot_id,
                        reason=str(error),
                    )
            if self._chip_source is None:
                raise AdviceBackendNotReadyError("The capture's chip inputs are unreadable.")
            provider, rules = self._chip_source
            for entry in entries:
                key = (league_id, entry)
                if key in self._chip_members:
                    continue
                try:
                    self._chip_members[key] = held_member_chips(
                        AdviseEntryRequest(context.season, context.gameweek, league_id, entry),
                        provider=provider,
                        inputs=identity.inputs,
                        rules=rules,
                    )
                except Exception as error:
                    self._chip_members[key] = None
                    self._report(
                        "advice_chip_history_unreadable",
                        snapshot_id=context.capture_snapshot_id,
                        entry_id=entry,
                        reason=str(error),
                    )
            return {entry: self._chip_members[(league_id, entry)] for entry in entries}

    def _report(self, event: str, **fields: object) -> None:
        key = event, str(fields.get("snapshot_id", ""))
        marker = str(fields.get("reason", ""))
        if marker == self._reported.get(key):
            return
        self._reported[key] = marker
        if self._log is not None:
            self._log.event(event, **fields)


class StoreProbeGate:
    """ADR 0006's capability probe, held for a short while rather than for ever.

    A pass is remembered so a proven mount is not re-exercised on every readiness poll,
    but only for ``recheck_seconds``: a store can stop working after it started, and a
    gate that cached its first success would keep reporting a mount that has since gone
    away. A failure is never cached, so a mount that arrives late brings the service up
    without a restart.

    There is deliberately no local-disk fallback. A failed probe keeps the service
    unready, which is a loud problem rather than a quiet correctness one.
    """

    def __init__(
        self,
        root: Path,
        *,
        recheck_seconds: float = DEFAULT_PROBE_RECHECK_SECONDS,
        clock: Callable[[], float] = time.monotonic,
        log: AdviceLog | None = None,
    ) -> None:
        self._root = root
        self._recheck = recheck_seconds
        self._clock = clock
        self._log = log
        self._passed: StoreProbeResult | None = None
        self._passed_at = 0.0

    def result(self) -> StoreProbeResult:
        held = self._passed
        if held is not None and self._clock() - self._passed_at < self._recheck:
            return held
        outcome = probe_store(self._root)
        if outcome.ok:
            self._passed = outcome
            self._passed_at = self._clock()
            if self._log is not None:
                self._log.event("advice_store_probe_passed", root=str(self._root))
        else:
            self._passed = None
            if self._log is not None:
                self._log.event(
                    "advice_store_probe_failed",
                    root=str(self._root),
                    failed=",".join(outcome.failures()),
                )
        return outcome

    def passed(self) -> bool:
        return self.result().ok


@dataclass(frozen=True, slots=True)
class AdviceBackend:
    """The wired backend: the objects both processes share, built once."""

    config: BackendConfig
    queue: FileJobQueue
    cache: FileAdviceCache
    reader: AdviceReadStore
    submit: AdviceSubmitService
    contexts: CaptureContextProvider
    job_specs: AdviceJobSpecStore
    probe: StoreProbeGate
    metrics: AdviceMetrics
    log: AdviceLog

    def queue_depth(self) -> int:
        """Open work, not history: a terminal job is not something a member waits for."""

        return sum(1 for job in self.queue.jobs() if not job.is_terminal)

    def jobs_by_status(self) -> dict[str, int]:
        """One current store read inside the owning API, never in the status script."""
        counts = dict.fromkeys(("queued", "running", "completed", "failed"), 0)
        for job in self.queue.jobs():
            counts[job.status] += 1
        return counts

    def readiness(self) -> tuple[bool, Mapping[str, bool]]:
        """Ready means this process can actually answer, checked rather than assumed."""

        context = self.contexts.current()
        directory = FileLeagueDirectory(self.config.site_data_root)
        return readiness_report(
            context_loaded=context is not None,
            league_tree_readable=directory.readable(),
            cache_writable=self.probe.passed(),
            # Season and gameweek are already in the context; nothing is projected for it.
            league_tree_matches_capture=directory.matches(context),
        )


def build_backend(
    config: BackendConfig,
    *,
    log: AdviceLog | None = None,
    probe: StoreProbeGate | None = None,
    metrics: AdviceMetrics | None = None,
) -> AdviceBackend:
    """Open one store and wire every collaborator that reads or writes it.

    ``probe`` is injectable for the same reason ``log`` is: the gate holds a pass for a
    staleness budget, and a caller that wants to observe a store failing after it passed
    supplies a gate that rechecks immediately rather than fabricating a clock.
    """

    component_log = log if log is not None else AdviceLog("backend")
    metrics = metrics if metrics is not None else AdviceMetrics()
    queue = FileJobQueue(config.queue_root)
    cache = FileAdviceCache(config.cache_root)
    specs = FileAdviceJobSpecStore(config.spec_root)
    gate = probe if probe is not None else StoreProbeGate(config.store_root, log=component_log)
    contexts = CaptureContextProvider(
        config,
        repository_commit=_repository_commit(),
        fingerprint=configuration_fingerprint(),
        log=component_log,
    )
    reader = AdviceReadStore(
        FileLeagueDirectory(config.site_data_root),
        cache,
        contexts,
        computable_strategies(),
        capabilities=menu_capabilities(),
        switches=contexts,
        chip_availability=contexts.held_chips,
    )
    submit = AdviceSubmitService(
        reader,
        queue,
        rate_limiter=FixedWindowRateLimiter(config.rate_limit, config.rate_window_seconds),
        specs=specs,
        # Accepting work the store cannot hold is a promise the deployment cannot keep:
        # the job write would fail, or succeed onto storage nobody will read again.
        store_ready=gate.passed,
    )
    return AdviceBackend(
        config=config,
        queue=queue,
        cache=cache,
        reader=reader,
        submit=submit,
        contexts=contexts,
        job_specs=specs,
        probe=gate,
        metrics=metrics,
        log=component_log,
    )


def backend_from_environment(
    environ: Mapping[str, str] | None = None, *, metrics: AdviceMetrics | None = None
) -> AdviceBackend:
    """The deployment's backend, read from the server's own environment."""

    return build_backend(BackendConfig.from_environment(environ), metrics=metrics)
