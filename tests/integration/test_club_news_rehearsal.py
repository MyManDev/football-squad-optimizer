"""The whole lane rehearsed without a key, which is #551's definition of done.

The point of the issue was that on the day a key and a signed terms reading exist, switching
to a real provider should be **an environment variable and a registry row, not a code change**.
A claim like that is only worth anything if it can be walked, so this walks it:

- a fake adapter registered through the generic configuration and selected by environment
  variable alone;
- the acquisition command run end to end against it, printing a capture id;
- that capture id driving the rotation export, exactly as the weekly stage drives it;
- the export's manifest naming the model that was actually asked;
- the timing guard demonstrated, with the refusal shown rather than described.

**What this does not do, and says so rather than implying otherwise.** It drives
``export_rotation_evidence`` with the capture id instead of running the whole weekly runner,
because a weekly run needs a week's captures and a workspace lock. The step between -- that
``--rotation-capture`` reaches the export as ``club_news_snapshot`` and names the artifact --
is pinned by ``test_a_named_capture_reaches_the_export_from_the_stage_that_runs_it`` in
``test_weekly_operations``, which drives the stage itself and reads back the request it built.
What is rehearsed here is the path those two meet on.

Nothing opens a socket, nothing reads a key, and every write is under ``tmp_path``.
"""

import json
import urllib.error
from collections.abc import Sequence
from datetime import UTC, datetime
from pathlib import Path
from typing import Any

import pandas as pd
import pytest
from tests.fixtures.synthetic_rotation_capture import (
    CAPTURED_AT,
    DEADLINE,
    DECISION_SOURCE,
    SEASON,
    TARGET_GAMEWEEK,
    bootstrap_payload,
    fixtures_payload,
)

from squadopt.application.rotation_export import RotationExportRequest, export_rotation_evidence
from squadopt.data.errors import DataError
from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources.club_news import (
    ClaimResponse,
    FixtureClubNewsProvider,
    RawDocument,
    RosterPlayer,
)
from squadopt.data.sources.club_news_coding import CodingFixture
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.features.rotation_evidence_artifact import read_rotation_evidence_artifact
from squadopt.platform.club_news_acquire import main as acquire
from squadopt.platform.club_news_provider import (
    KEY_ENVIRONMENT_VARIABLE,
    MODEL_ENVIRONMENT_VARIABLE,
    PROVIDER_ENVIRONMENT_VARIABLE,
    CodingProviderConfig,
    register_provider,
)

SAMPLE = Path(__file__).resolve().parents[2] / "data" / "sample"
FIXTURE = SAMPLE / "club_news_v1.fixture.json"
CODING_FIXTURE = SAMPLE / "club_news_coding_v1.fixture.json"

COMMIT = "0" * 40
#: Before the decision capture, as the timing rule requires of a week's documents.
FETCHED_AT = datetime(2026, 9, 12, 14, 0, tzinfo=UTC)
#: After it, which is the case the timing guard exists to refuse.
FETCHED_TOO_LATE = datetime(2026, 9, 12, 16, 0, tzinfo=UTC)

#: The provider a real day would name. Nothing about it is in the code under test.
REHEARSAL_PROVIDER = "rehearsal-fake"
REHEARSAL_MODEL = "rehearsal-model-1"


class _Reply:
    def __init__(self, url: str, body: bytes) -> None:
        self._url, self._body = url, body
        self.status = 200
        self.headers = {"Content-Type": "text/html; charset=utf-8"}

    def geturl(self) -> str:
        return self._url

    def read(self, amount: int | None = None) -> bytes:
        return self._body if amount is None else self._body[:amount]

    def __enter__(self) -> "_Reply":
        return self

    def __exit__(self, *_: object) -> None:
        return None


def _host() -> Any:
    """One host serving the committed fixture's bytes, and an allowing robots."""

    provider = FixtureClubNewsProvider(FIXTURE)
    pages = {url: provider.fetch(url) for url in provider.urls}

    def _open(request: Any, timeout: float) -> _Reply:
        url = request.full_url
        if url.endswith("/robots.txt"):
            return _Reply(url, b"User-agent: *\nAllow: /\n")
        document = pages.get(url)
        if document is None:
            raise urllib.error.HTTPError(url, 404, "Not Found", {}, None)  # type: ignore[arg-type]
        return _Reply(document.final_url, document.content)

    return _open


class _RehearsalProvider:
    """Answers about the documents it is handed, from the committed coding fixture.

    It answers per club because the request unit is per club, and it narrows the committed
    response to the documents in front of it for the prompt's own first rule: a model handed
    two pages may not cite a third.
    """

    def __init__(self, config: CodingProviderConfig) -> None:
        self._config = config

    def fetch(self, url: str) -> RawDocument:  # pragma: no cover - never called
        raise AssertionError(f"the rehearsal provider does not fetch {url!r}")

    def code(
        self, documents: Sequence[RawDocument], roster: Sequence[RosterPlayer]
    ) -> ClaimResponse:
        fixture = json.loads(CodingFixture(CODING_FIXTURE).response().text)
        served = {url for d in documents for url in (d.requested_url, d.final_url)}
        return ClaimResponse(
            text=json.dumps(
                {
                    "contract_version": fixture["contract_version"],
                    "documents": [e for e in fixture["documents"] if e["url"] in served],
                    "claims": [e for e in fixture["claims"] if e["source_url"] in served],
                },
                ensure_ascii=False,
            ),
            model_identifier=self._config.model_identifier,
            model_version="rehearsal-1",
        )


def _registry(path: Path) -> Path:
    """One page per club, from the fixture's own URLs."""

    provider = FixtureClubNewsProvider(FIXTURE)
    first: dict[str, str] = {}
    for url in provider.urls:
        first.setdefault(provider.fetch(url).club, url)
    path.write_text(
        json.dumps(
            {
                "contract_version": "club_news_sources_v1",
                "sources": [
                    {"club": club, "url": url, "terms_record": "docs/club_news_sources.md"}
                    for club, url in first.items()
                ],
            }
        ),
        encoding="utf-8",
    )
    return path


def _decision(root: Path) -> str:
    metadata = write_snapshot(
        root,
        source=DECISION_SOURCE,
        captured_at_utc=CAPTURED_AT,
        payloads={BOOTSTRAP_PAYLOAD: bootstrap_payload(), FIXTURES_PAYLOAD: fixtures_payload()},
    )
    return metadata.snapshot_id


def _acquire(tmp_path: Path, *, now: datetime, decision: str) -> int:
    """Run the command as a real day would, against the week's own decision capture.

    The roster comes from that capture rather than from a second one, which is the command's
    own rule: its only network reach is the club hosts the registry names.
    """

    snapshots = tmp_path / "snapshots"
    code = acquire(
        [
            "--roster-snapshot",
            decision,
            "--registry",
            str(_registry(tmp_path / "sources.json")),
            "--snapshot-root",
            str(snapshots),
        ],
        environ={
            PROVIDER_ENVIRONMENT_VARIABLE: REHEARSAL_PROVIDER,
            MODEL_ENVIRONMENT_VARIABLE: REHEARSAL_MODEL,
            KEY_ENVIRONMENT_VARIABLE: "not-a-real-key",
        },
        opener=_host(),
        now=lambda: now,
        sleeper=lambda _: None,
    )
    return code


@pytest.fixture(autouse=True)
def _registered() -> None:
    register_provider(REHEARSAL_PROVIDER, _RehearsalProvider)


def _capture_id(printed: str) -> str:
    lines = [line for line in printed.splitlines() if line.startswith("Capture")]
    assert lines, printed
    return lines[0].split()[-1]


def test_a_week_is_acquired_and_exported_without_a_key(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """The whole path, with the provider chosen by an environment variable and nothing else.

    No code under test names the rehearsal provider. It is registered by this test through
    the same door a second real adapter would use, and selected by the same variable an
    operator would set.
    """

    snapshots = tmp_path / "snapshots"
    decision = _decision(snapshots)

    code = _acquire(tmp_path, now=FETCHED_AT, decision=decision)
    printed = capsys.readouterr().out
    assert code == 0, printed

    capture = _capture_id(printed)
    assert f"provider '{REHEARSAL_PROVIDER}'" in printed
    output = tmp_path / "out"
    export_rotation_evidence(
        RotationExportRequest(
            season=SEASON,
            target_gameweek=TARGET_GAMEWEEK,
            deadline_utc=DEADLINE,
            snapshot=decision,
            snapshot_root=snapshots,
            club_news_fixture=None,
            output_dir=output,
            club_news_snapshot=capture,
            table_name="table",
        ),
        repository_commit=COMMIT,
    )

    table = pd.read_csv(output / "table.csv")
    manifest = json.loads((output / "table.manifest.json").read_text(encoding="utf-8"))

    assert len(table) == manifest["roster_size"]
    # The record names what answered, which is the whole reason genericity is about wiring.
    assert manifest["model_identifier"] == REHEARSAL_MODEL
    # And which adapter was asked. It is not recoverable from the model identifier: this fake
    # names a model no vendor serves, and a real vendor's identifier can be served through
    # another's compatible endpoint. #551's fourth rehearsal item is this line.
    assert manifest["provider"] == REHEARSAL_PROVIDER
    # And a consumer reading the artifact back sees it, which is what makes the field a record
    # rather than a line in a file nobody opens.
    read_back = read_rotation_evidence_artifact(
        output / "table.csv", output / "table.manifest.json"
    )
    assert read_back.attrs["provider"] == REHEARSAL_PROVIDER
    assert read_back.attrs["model_identifier"] == REHEARSAL_MODEL
    assert manifest["clubs_covered"], manifest
    assert set(manifest["clubs_covered"]) <= set(manifest["clubs_declared"])


def test_the_timing_guard_refuses_a_document_read_after_the_decision(
    tmp_path: Path, capsys: pytest.CaptureFixture[str]
) -> None:
    """Shown, not described: a week whose documents were read too late is refused.

    Words fetched after a capture could have been chosen by looking at it first, so the
    export refuses them. This is the rule that puts the acquisition command *before* the
    capture in the week, and it is demonstrated here with its own refusal rather than left
    as a sentence in a runbook.
    """

    snapshots = tmp_path / "snapshots"
    decision = _decision(snapshots)

    code = _acquire(tmp_path, now=FETCHED_TOO_LATE, decision=decision)
    printed = capsys.readouterr().out
    assert code == 0, printed
    capture = _capture_id(printed)
    with pytest.raises(DataError) as refusal:
        export_rotation_evidence(
            RotationExportRequest(
                season=SEASON,
                target_gameweek=TARGET_GAMEWEEK,
                deadline_utc=DEADLINE,
                snapshot=decision,
                snapshot_root=snapshots,
                club_news_fixture=None,
                output_dir=tmp_path / "late",
                club_news_snapshot=capture,
                table_name="table",
            ),
            repository_commit=COMMIT,
        )

    # The distinguishing sentence, not merely the word "capture", which many refusals carry.
    assert "fetched at or after the decision capture" in str(refusal.value), refusal.value
    assert not (tmp_path / "late" / "table.csv").exists()
