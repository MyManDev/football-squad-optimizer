"""Transport-neutral identity and reproducibility inputs for one platform run.

A run id tells operators which execution they are looking at. A reproducibility
fingerprint answers a different question: which code, configuration, inputs, component
versions and seed determined the result? ``RunContext`` records both without importing a
database, HTTP framework, queue client or application implementation.
"""

import hashlib
import json
import re
import secrets
from collections.abc import Mapping
from dataclasses import dataclass, field
from datetime import UTC, datetime
from types import MappingProxyType
from typing import Final

RUN_CONTEXT_CONTRACT_VERSION: Final = "run_context_v1"
_RUN_ID_PATTERN: Final = re.compile(r"^[A-Za-z0-9][A-Za-z0-9._-]{0,127}$")
_NAME_PATTERN: Final = re.compile(r"^[a-z][a-z0-9._-]{0,63}$")
_COMMIT_PATTERN: Final = re.compile(r"^[0-9a-f]{40}$")
_SHA256_PATTERN: Final = re.compile(r"^[0-9a-f]{64}$")
_MAX_SEED: Final = 2**63 - 1


class RunContextError(ValueError):
    """A run context cannot provide an unambiguous reproducibility identity."""


def _require_pattern(value: object, *, label: str, pattern: re.Pattern[str]) -> str:
    if not isinstance(value, str) or not pattern.fullmatch(value):
        raise RunContextError(f"{label} has an invalid format: {value!r}.")
    return value


def _normalize_utc_timestamp(value: object) -> str:
    if not isinstance(value, str) or not value.strip():
        raise RunContextError("created_at_utc must be a non-empty ISO-8601 UTC timestamp.")
    try:
        parsed = datetime.fromisoformat(value.strip().replace("Z", "+00:00"))
    except ValueError as error:
        raise RunContextError(
            f"created_at_utc must be an ISO-8601 UTC timestamp, got {value!r}."
        ) from error
    offset = parsed.utcoffset()
    if parsed.tzinfo is None or offset is None or offset.total_seconds() != 0.0:
        raise RunContextError(f"created_at_utc must state UTC explicitly, got {value!r}.")
    return parsed.isoformat().replace("+00:00", "Z")


def _fingerprint_mapping(value: object, *, label: str) -> Mapping[str, str]:
    if not isinstance(value, Mapping) or not value:
        raise RunContextError(f"{label} must contain at least one named SHA-256 fingerprint.")
    normalized: dict[str, str] = {}
    for name, digest in value.items():
        key = _require_pattern(name, label=f"{label} name", pattern=_NAME_PATTERN)
        normalized[key] = _require_pattern(
            digest,
            label=f"{label}[{key!r}]",
            pattern=_SHA256_PATTERN,
        )
    return MappingProxyType(dict(sorted(normalized.items())))


def _version_mapping(value: object) -> Mapping[str, str]:
    if not isinstance(value, Mapping):
        raise RunContextError("component_versions must be a mapping.")
    normalized: dict[str, str] = {}
    for name, version in value.items():
        key = _require_pattern(name, label="component_versions name", pattern=_NAME_PATTERN)
        if not isinstance(version, str) or not version.strip() or version != version.strip():
            raise RunContextError(
                f"component_versions[{key!r}] must be non-empty text without surrounding spaces."
            )
        normalized[key] = version
    return MappingProxyType(dict(sorted(normalized.items())))


@dataclass(frozen=True, slots=True)
class RunContext:
    """Immutable inputs that identify and reproduce one serious execution.

    ``run_id`` and ``created_at_utc`` distinguish attempts, but deliberately do not
    affect :attr:`reproducibility_fingerprint`. Two attempts with the same determining
    inputs therefore share a reproducibility identity while retaining separate
    operational identities.
    """

    run_id: str
    repository_commit: str
    configuration_fingerprint: str
    input_fingerprints: Mapping[str, str]
    deterministic_seed: int
    created_at_utc: str
    component_versions: Mapping[str, str] = field(default_factory=dict)
    contract_version: str = RUN_CONTEXT_CONTRACT_VERSION

    def __post_init__(self) -> None:
        if self.contract_version != RUN_CONTEXT_CONTRACT_VERSION:
            raise RunContextError(
                f"contract_version must be {RUN_CONTEXT_CONTRACT_VERSION!r}, "
                f"got {self.contract_version!r}."
            )
        object.__setattr__(
            self,
            "run_id",
            _require_pattern(self.run_id, label="run_id", pattern=_RUN_ID_PATTERN),
        )
        object.__setattr__(
            self,
            "repository_commit",
            _require_pattern(
                self.repository_commit,
                label="repository_commit",
                pattern=_COMMIT_PATTERN,
            ),
        )
        object.__setattr__(
            self,
            "configuration_fingerprint",
            _require_pattern(
                self.configuration_fingerprint,
                label="configuration_fingerprint",
                pattern=_SHA256_PATTERN,
            ),
        )
        if (
            isinstance(self.deterministic_seed, bool)
            or not isinstance(self.deterministic_seed, int)
            or not 0 <= self.deterministic_seed <= _MAX_SEED
        ):
            raise RunContextError(
                f"deterministic_seed must be an integer from 0 through {_MAX_SEED}."
            )
        object.__setattr__(
            self,
            "input_fingerprints",
            _fingerprint_mapping(self.input_fingerprints, label="input_fingerprints"),
        )
        object.__setattr__(self, "component_versions", _version_mapping(self.component_versions))
        object.__setattr__(
            self,
            "created_at_utc",
            _normalize_utc_timestamp(self.created_at_utc),
        )

    @classmethod
    def create(
        cls,
        *,
        repository_commit: str,
        configuration_fingerprint: str,
        input_fingerprints: Mapping[str, str],
        deterministic_seed: int,
        component_versions: Mapping[str, str] | None = None,
        run_id: str | None = None,
        now: datetime | None = None,
    ) -> "RunContext":
        """Create a context, generating only its operational id and UTC timestamp.

        Every value that can change a result remains mandatory. ``now`` and ``run_id``
        are injectable so replays and tests never depend on the wall clock or randomness.
        """

        moment = now or datetime.now(UTC)
        if not isinstance(moment, datetime):
            raise RunContextError("now must be a datetime.")
        offset = moment.utcoffset()
        if moment.tzinfo is None or offset is None or offset.total_seconds() != 0.0:
            raise RunContextError("now must be timezone-aware and expressed in UTC.")
        created_at = moment.isoformat().replace("+00:00", "Z")
        identifier = run_id or f"{moment.strftime('%Y%m%dT%H%M%SZ')}-{secrets.token_hex(6)}"
        return cls(
            run_id=identifier,
            repository_commit=repository_commit,
            configuration_fingerprint=configuration_fingerprint,
            input_fingerprints=input_fingerprints,
            deterministic_seed=deterministic_seed,
            created_at_utc=created_at,
            component_versions={} if component_versions is None else component_versions,
        )

    def _reproducibility_payload(self) -> dict[str, object]:
        return {
            "contract_version": self.contract_version,
            "repository_commit": self.repository_commit,
            "configuration_fingerprint": self.configuration_fingerprint,
            "input_fingerprints": dict(self.input_fingerprints),
            "component_versions": dict(self.component_versions),
            "deterministic_seed": self.deterministic_seed,
        }

    @property
    def reproducibility_fingerprint(self) -> str:
        """SHA-256 identity of every declared result-affecting input."""

        encoded = json.dumps(
            self._reproducibility_payload(),
            sort_keys=True,
            separators=(",", ":"),
        ).encode("utf-8")
        return hashlib.sha256(encoded).hexdigest()

    def to_dict(self) -> dict[str, object]:
        """Return the JSON-native, contract-versioned context document."""

        return {
            "contract_version": self.contract_version,
            "run_id": self.run_id,
            "created_at_utc": self.created_at_utc,
            "repository_commit": self.repository_commit,
            "configuration_fingerprint": self.configuration_fingerprint,
            "input_fingerprints": dict(self.input_fingerprints),
            "component_versions": dict(self.component_versions),
            "deterministic_seed": self.deterministic_seed,
            "reproducibility_fingerprint": self.reproducibility_fingerprint,
        }

    @classmethod
    def from_dict(cls, document: Mapping[str, object]) -> "RunContext":
        """Validate and rebuild a context, including its composite fingerprint."""

        expected_keys = {
            "contract_version",
            "run_id",
            "created_at_utc",
            "repository_commit",
            "configuration_fingerprint",
            "input_fingerprints",
            "component_versions",
            "deterministic_seed",
            "reproducibility_fingerprint",
        }
        actual_keys = set(document)
        if actual_keys != expected_keys:
            missing = sorted(expected_keys - actual_keys)
            unexpected = sorted(actual_keys - expected_keys)
            raise RunContextError(
                f"Run context fields do not match {RUN_CONTEXT_CONTRACT_VERSION}: "
                f"missing={missing!r}, unexpected={unexpected!r}."
            )
        seed = document["deterministic_seed"]
        if isinstance(seed, bool) or not isinstance(seed, int):
            raise RunContextError("deterministic_seed must be an integer.")
        context = cls(
            contract_version=document["contract_version"],  # type: ignore[arg-type]
            run_id=document["run_id"],  # type: ignore[arg-type]
            created_at_utc=document["created_at_utc"],  # type: ignore[arg-type]
            repository_commit=document["repository_commit"],  # type: ignore[arg-type]
            configuration_fingerprint=document["configuration_fingerprint"],  # type: ignore[arg-type]
            input_fingerprints=document["input_fingerprints"],  # type: ignore[arg-type]
            component_versions=document["component_versions"],  # type: ignore[arg-type]
            deterministic_seed=seed,
        )
        if document["created_at_utc"] != context.created_at_utc:
            raise RunContextError("created_at_utc must use the canonical UTC spelling ending in Z.")
        recorded = document["reproducibility_fingerprint"]
        if recorded != context.reproducibility_fingerprint:
            raise RunContextError(
                "reproducibility_fingerprint does not match the run context's determining inputs."
            )
        return context
