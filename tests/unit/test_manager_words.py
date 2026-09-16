"""The manager's word: a declared rule over coded club news, with the words themselves.

What has to hold: the rule maps each disposition to a role and nothing else; only the
member's own fifteen is constrained; the cited words are cut from the bytes that hash to the
citation and from nothing else; a source without its evidence (or the reverse) is refused.
"""

import hashlib
from pathlib import Path
from typing import Any

import pandas as pd
import pytest

from squadopt.application import manager_words as module
from squadopt.application.league_publication import (
    LeaguePublicationRequest,
    load_publication_manager_words,
)
from squadopt.application.manager_words import (
    SOURCE_SYNTHETIC_FIXTURE,
    ManagerWord,
    ManagerWords,
    ManagerWordsError,
    documents_from_source,
    manager_words_from_artifact,
)
from squadopt.data.errors import DataError
from squadopt.data.sources.club_news import ROTATION_DISPOSITIONS
from squadopt.features.rotation_evidence import ROTATION_EVIDENCE_COLUMNS

FIXTURE = Path(__file__).resolve().parents[2] / "data" / "sample" / "club_news_v1.fixture.json"


def _word(player_id: int, disposition: str) -> ManagerWord:
    return ManagerWord(
        player_id=player_id,
        disposition=disposition,
        speaker="the manager",
        published_at_utc="2026-09-11T14:00:00Z",
        published_precision="instant",
        club="Arsenal",
        source_url="https://club.example/arsenal/news",
        fetched_at_utc="2026-09-12T14:05:00Z",
        words="He will not travel.",
    )


def _words(*words: ManagerWord) -> ManagerWords:
    return ManagerWords(
        season="2026-27",
        gameweek=5,
        source_kind=SOURCE_SYNTHETIC_FIXTURE,
        source_label=FIXTURE.name,
        evidence_table="rotation_evidence_v2_2026-27_gw05.csv",
        clubs_covered=("Arsenal",),
        words=tuple(words),
    )


def test_the_rule_is_declared_over_the_whole_vocabulary() -> None:
    """Every disposition the vocabulary allows maps to exactly one of three outcomes."""

    roles = {disposition: _word(1, disposition).role for disposition in ROTATION_DISPOSITIONS}
    assert roles == {
        "not_addressed": None,
        "no_statement": None,
        "stated_expected_to_start": None,
        "stated_expected_absent": "not_starting",
        "stated_rotation_risk": "not_captain",
        "stated_returning_from_injury": None,
        "stated_minutes_limited": "not_captain",
        "ambiguous": None,
    }


def test_every_named_player_is_excluded_and_only_the_members_own_are_shown() -> None:
    """The solver keeps out everyone the page spoke about, held or not: a player the
    manager ruled out must not be bought and started either. The member reads only the
    statements that touch the players they hold or end up with."""

    words = _words(
        _word(1, "stated_expected_absent"),
        _word(2, "stated_rotation_risk"),
        _word(3, "stated_expected_to_start"),
        _word(4, "stated_expected_absent"),
    )

    exclusion = words.exclusion()
    assert exclusion is not None
    assert exclusion.not_starting == frozenset({1, 4})
    assert exclusion.not_captain == frozenset({1, 2, 4})
    assert [(w.player_id, w.role) for w in words.about((1, 2, 3, 99))] == [
        (1, "not_starting"),
        (2, "not_captain"),
    ]
    assert words.about((3, 99)) == ()
    # A page that spoke about nobody the rule acts on binds nothing: no exclusion, not an
    # empty one.
    assert _words(_word(3, "stated_expected_to_start")).exclusion() is None


def test_the_words_are_cut_from_the_bytes_that_hash_to_the_citation(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    """The span is resolved against the document whose digest the claim cites; a digest
    no held document produces resolves to no words rather than to different ones."""

    documents, kind, label = documents_from_source(FIXTURE)
    assert kind == SOURCE_SYNTHETIC_FIXTURE and label == FIXTURE.name
    arsenal = next(document for document in documents if document.club == "Arsenal")
    sentence = b"Havertz will not travel."
    start = arsenal.readable.index(sentence)
    end = start + len(sentence)
    digest = hashlib.sha256(arsenal.readable).hexdigest()

    def row(
        player_id: int, disposition: str | None, sha: str | None, span: tuple[int, int] | None
    ) -> dict[str, Any]:
        record: dict[str, Any] = dict.fromkeys(ROTATION_EVIDENCE_COLUMNS, pd.NA)
        record.update(season="2026-27", target_gameweek=5, player_id=player_id)
        record["rotation_disposition"] = pd.NA if disposition is None else disposition
        record["rotation_claim_source_sha256"] = pd.NA if sha is None else sha
        if span is not None:
            record["rotation_claim_span_start"], record["rotation_claim_span_end"] = span
        record["rotation_claim_speaker"] = "the manager"
        record["rotation_claim_published_at_utc"] = "2026-09-11T14:00:00Z"
        record["rotation_claim_published_precision"] = "instant"
        return record

    table = pd.DataFrame(
        [
            row(7, "stated_expected_absent", digest, (start, end)),
            row(8, "stated_rotation_risk", "0" * 64, (0, 5)),
            row(9, None, None, None),
        ],
        columns=list(ROTATION_EVIDENCE_COLUMNS),
    )
    monkeypatch.setattr(module, "read_rotation_evidence_artifact", lambda *_: table)

    words = manager_words_from_artifact(
        Path("table.csv"),
        Path("table.manifest.json"),
        documents=documents,
        source_kind=kind,
        source_label=label,
    )

    assert words.season == "2026-27" and words.gameweek == 5
    assert "Arsenal" in words.clubs_covered
    assert [w.player_id for w in words.words] == [7, 8]
    resolved = words.words[0]
    assert resolved.words == "Havertz will not travel."
    assert resolved.club == "Arsenal"
    assert resolved.source_url == arsenal.final_url
    assert resolved.speaker == "the manager"
    unresolved = words.words[1]
    assert unresolved.words is None and unresolved.club is None and unresolved.source_url is None
    assert unresolved.role == "not_captain"


def test_a_source_that_is_neither_fixture_nor_capture_is_refused(tmp_path: Path) -> None:
    with pytest.raises(ManagerWordsError, match="No club-news source"):
        documents_from_source(tmp_path / "nowhere")


def test_evidence_and_its_source_travel_together_or_not_at_all(tmp_path: Path) -> None:
    base = dict(
        snapshot_root=tmp_path,
        snapshot_id="fpl-live-x",
        archive_root=tmp_path,
        registry_path=tmp_path / "registry.json",
        out_dir=tmp_path / "out",
        league_id=352490,
    )
    assert load_publication_manager_words(LeaguePublicationRequest(**base)) is None
    with pytest.raises(DataError, match="one without the other"):
        load_publication_manager_words(
            LeaguePublicationRequest(**base, rotation_evidence=tmp_path / "table.csv")
        )
    with pytest.raises(DataError, match="one without the other"):
        load_publication_manager_words(LeaguePublicationRequest(**base, club_news_source=FIXTURE))
    with pytest.raises(ManagerWordsError, match="No manifest beside"):
        load_publication_manager_words(
            LeaguePublicationRequest(
                **base, rotation_evidence=tmp_path / "table.csv", club_news_source=FIXTURE
            )
        )
