"""Expose verified plan provenance without changing the shared immutable answer."""

from __future__ import annotations

import hashlib
import json
import re
from collections.abc import Iterator
from pathlib import Path
from typing import Any

from squadopt.platform.advice_cache import AdviceCacheConflictError, FileAdviceCache


def _plans(document: Any) -> Iterator[tuple[str, dict[str, Any]]]:
    main = document.get("payload") if isinstance(document, dict) else None
    if not isinstance(main, dict):
        return
    yield "main", main
    bundle = main.get("preference_bundle_result")
    if isinstance(bundle, dict) and isinstance(bundle.get("components"), list):
        for index, slot in enumerate(bundle["components"]):
            if isinstance(slot, dict) and isinstance(slot.get("payload"), dict):
                yield str(index), slot["payload"]
        selected = bundle.get("selected")
        if isinstance(selected, dict) and isinstance(selected.get("payload"), dict):
            yield "selected", selected["payload"]


def _encoded(document: Any) -> bytes:
    return json.dumps(document, sort_keys=True, separators=(",", ":")).encode()


def _separate(raw: bytes) -> tuple[bytes, dict[str, str]]:
    if b'"plan_data_id"' not in raw:
        return raw, {}
    document = json.loads(raw)
    identities = {
        slot: plan.pop("plan_data_id") for slot, plan in _plans(document) if "plan_data_id" in plan
    }
    return (_encoded(document) if identities else raw), identities


def _receipt_key(key: str, raw: bytes) -> str:
    # The receipt is valid only for these exact bytes at this advice address.
    return hashlib.sha256(key.encode("ascii") + raw).hexdigest()


class PlanAdviceCache:
    def __init__(self, root: Path, *, llmopt_vnext: bool) -> None:
        self._answers = FileAdviceCache(root)
        self._receipts = FileAdviceCache(root / "plan-provenance")
        self._enabled = llmopt_vnext

    def get(self, key: str) -> bytes | None:
        raw = self._answers.get(key)
        if raw is None:
            return None
        canonical, embedded = _separate(raw)
        if not self._enabled:
            # Also project any older worker's embedded metadata on rollback.
            return canonical
        if embedded:
            return raw
        receipt = self._receipts.get(_receipt_key(key, raw))
        if receipt is None:
            return raw
        identities = json.loads(receipt)
        if not isinstance(identities, dict) or not identities:
            return raw
        document = json.loads(raw)
        plans = dict(_plans(document))
        if not all(
            slot in plans and isinstance(identity, str) and re.fullmatch(r"[0-9a-f]{64}", identity)
            for slot, identity in identities.items()
        ):
            return raw
        for slot, identity in identities.items():
            plans[slot]["plan_data_id"] = identity
        return _encoded(document)

    def put(self, key: str, payload: bytes) -> None:
        raw, identities = _separate(payload)
        if self._enabled and identities:
            self._receipts.put(_receipt_key(key, raw), _encoded(identities))
        try:
            self._answers.put(key, raw)
        except AdviceCacheConflictError:
            # A pre-release answer may contain the same bytes plus embedded provenance.
            previous = self._answers.get(key)
            if previous is None or _separate(previous)[0] != raw:
                raise
