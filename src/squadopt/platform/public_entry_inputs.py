"""Pin one requested team's public inputs without changing the weekly capture."""

from __future__ import annotations

import hashlib
import json
import threading
from collections.abc import Callable, Mapping
from dataclasses import dataclass
from typing import Any
from urllib.error import HTTPError, URLError
from urllib.request import HTTPRedirectHandler, Request, build_opener

from squadopt.application.capture_entries import CapturePicksProvider
from squadopt.platform.advice_cache import AdviceCacheConflictError, AdviceCacheRepository
from squadopt.platform.advice_read import AdviceBackendNotReadyError, AdviceRequestContext

PUBLIC_ENTRY_SWITCH = "public_entry"
MAX_BUNDLE_BYTES = 2 * 1024 * 1024
FORWARDER_ORIGIN = "https://squadopt.mymandev.com"


class _NoRedirect(HTTPRedirectHandler):
    def redirect_request(
        self, req: Any, fp: Any, code: int, msg: str, headers: Any, newurl: str
    ) -> None:
        return None


def fetch_public_entry(entry_id: int, gameweek: int) -> bytes:
    """One bounded read from the deployed, allowlisted FPL forwarder."""
    request = Request(
        f"{FORWARDER_ORIGIN}/api/v1/fpl/entry/{entry_id}/bundle?gw={gameweek}",
        headers={"User-Agent": "squadopt-entry-compute/1.0", "Accept": "application/json"},
    )
    try:
        with build_opener(_NoRedirect()).open(request, timeout=15) as response:
            if response.headers.get("x-squadopt-fpl") != "1":
                raise ValueError("The entry response has no forwarder marker.")
            if response.headers.get_content_type() != "application/json":
                raise ValueError("The entry response is not JSON.")
            raw: bytes = response.read(MAX_BUNDLE_BYTES + 1)
    except (HTTPError, URLError, TimeoutError, OSError, ValueError) as error:
        raise AdviceBackendNotReadyError("This team's public inputs are unavailable.") from error
    if len(raw) > MAX_BUNDLE_BYTES:
        raise AdviceBackendNotReadyError("The public entry response exceeds its size limit.")
    return raw


def _canonical(bundle: object, context: AdviceRequestContext, entry_id: int) -> bytes:
    if not isinstance(bundle, dict):
        raise ValueError("The public entry bundle is not an object.")
    if (
        bundle.get("contract_version") != "fpl_entry_bundle_v1"
        or type(bundle.get("entry_id")) is not int
        or bundle["entry_id"] != entry_id
        or type(bundle.get("gameweek")) is not int
        or bundle["gameweek"] != context.gameweek
    ):
        raise ValueError("The public entry bundle names another team or week.")
    entry, history, transfers, picks = (
        bundle.get("entry"),
        bundle.get("history"),
        bundle.get("transfers"),
        bundle.get("picks"),
    )
    if not isinstance(entry, dict) or type(entry.get("id")) is not int or entry["id"] != entry_id:
        raise ValueError("The entry identity differs from the requested team.")
    if (
        not isinstance(history, dict)
        or not isinstance(transfers, list)
        or not isinstance(picks, list)
    ):
        raise ValueError("The public entry's held inputs are unreadable.")
    weeks: set[int] = set()
    for document in picks:
        held = document.get("entry_history") if isinstance(document, dict) else None
        week = held.get("event") if isinstance(held, dict) else None
        if type(week) is not int or not 1 <= week < context.gameweek or week in weeks:
            raise ValueError("The entry's held weeks are invalid or repeated.")
        weeks.add(week)
    if context.gameweek - 1 not in weeks:
        raise ValueError("The team's last held week is absent.")
    # Source timestamps and the live score do not affect the plan. Only held inputs are pinned.
    return json.dumps(
        {
            "contract_version": "public_entry_inputs_v1",
            "entry_id": entry_id,
            "capture_snapshot_id": context.capture_snapshot_id,
            "season": context.season,
            "gameweek": context.gameweek,
            "entry": entry,
            "history": history,
            "transfers": transfers,
            "picks": picks,
        },
        sort_keys=True,
        separators=(",", ":"),
        ensure_ascii=False,
    ).encode("utf-8")


@dataclass(frozen=True)
class _Payloads:
    payloads: Mapping[str, bytes]


class PublicEntryInputs:
    """First requested input per entry/capture, shared by API and worker; no league sweep."""

    def __init__(
        self,
        store: AdviceCacheRepository,
        fetch: Callable[[int, int], bytes] = fetch_public_entry,
    ) -> None:
        self._store = store
        self._fetch = fetch
        # Bounded lock stripes coalesce duplicate preparation without retaining arbitrary ids.
        self._locks = tuple(threading.Lock() for _ in range(32))

    @staticmethod
    def _key(context: AdviceRequestContext, entry_id: int) -> str:
        raw = (
            f"public-entry-v1:{context.capture_snapshot_id}:"
            f"{context.season}:{context.gameweek}:{entry_id}"
        )
        return hashlib.sha256(raw.encode()).hexdigest()

    def read(self, context: AdviceRequestContext, entry_id: int) -> bytes | None:
        raw = self._store.get(self._key(context, entry_id))
        if raw is None:
            return None
        try:
            if len(raw) > MAX_BUNDLE_BYTES:
                raise ValueError("Entry inputs exceed their bound.")
            document = json.loads(raw)
            if (
                document.get("contract_version") != "public_entry_inputs_v1"
                or document.get("capture_snapshot_id") != context.capture_snapshot_id
                or document.get("season") != context.season
            ):
                raise ValueError("Pinned input identity differs from the capture.")
            checked = _canonical(
                {**document, "contract_version": "fpl_entry_bundle_v1"}, context, entry_id
            )
            if checked != raw:
                raise ValueError("Pinned inputs are not canonical.")
        except (ValueError, TypeError, AttributeError, RecursionError) as error:
            raise AdviceBackendNotReadyError(
                "Pinned public entry inputs are unreadable."
            ) from error
        return raw

    def prepare(self, context: AdviceRequestContext, entry_id: int) -> None:
        key = self._key(context, entry_id)
        with self._locks[int(key[:2], 16) % len(self._locks)]:
            if self.read(context, entry_id) is not None:
                return
            try:
                raw = self._fetch(entry_id, context.gameweek)
                if len(raw) > MAX_BUNDLE_BYTES:
                    raise ValueError("Entry response too large.")
                pinned = _canonical(json.loads(raw), context, entry_id)
                if len(pinned) > MAX_BUNDLE_BYTES:
                    raise ValueError("Pinned inputs exceed their size limit.")
            except (ValueError, TypeError, RecursionError) as error:
                raise AdviceBackendNotReadyError(
                    "This team's public inputs are unreadable."
                ) from error
            try:
                self._store.put(key, pinned)
            except AdviceCacheConflictError:
                # Another API process pinned the first valid input. Keep that immutable winner.
                if self.read(context, entry_id) is None:
                    raise

    def fingerprint(self, context: AdviceRequestContext, entry_id: int) -> str | None:
        raw = self.read(context, entry_id)
        return None if raw is None else hashlib.sha256(raw).hexdigest()

    def provider(
        self,
        context: AdviceRequestContext,
        entry_id: int,
        fingerprint: str,
        captured_payloads: Mapping[str, bytes],
    ) -> CapturePicksProvider:
        return self.provider_for(context, {entry_id: fingerprint}, captured_payloads)

    def provider_for(
        self,
        context: AdviceRequestContext,
        pins: Mapping[int, str],
        captured_payloads: Mapping[str, bytes],
    ) -> CapturePicksProvider:
        """The capture's picks provider with each pinned team's documents beside the capture's.

        ``pins`` maps a team to the fingerprint its request recorded: the member, and the
        rival of a rival strategy. A pin that no longer matches is refused, never recomputed.
        """

        payloads = dict(captured_payloads)

        def encode(value: object) -> bytes:
            return json.dumps(value, sort_keys=True, separators=(",", ":")).encode()

        for entry_id, fingerprint in pins.items():
            raw = self.read(context, entry_id)
            if raw is None or hashlib.sha256(raw).hexdigest() != fingerprint:
                raise AdviceBackendNotReadyError("The queued team's pinned inputs no longer match.")
            document = json.loads(raw)
            payloads[f"entry-{entry_id}.json"] = encode(document["entry"])
            payloads[f"entry-{entry_id}-history.json"] = encode(document["history"])
            payloads[f"entry-{entry_id}-transfers.json"] = encode(document["transfers"])
            for picks in document["picks"]:
                week = picks["entry_history"]["event"]
                payloads[f"entry-{entry_id}-picks-gw{week:02d}.json"] = encode(picks)
        return CapturePicksProvider(_Payloads(payloads), context.capture_snapshot_id)
