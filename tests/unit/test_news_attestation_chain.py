"""A verified source fact travels through the real writer/reader without a paid call."""

import hashlib
import json
from dataclasses import replace
from pathlib import Path

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
from tests.unit.test_club_news_coding_versions import _document, _response
from tests.unit.test_rotation_export_from_capture import _decision

from squadopt.application.manager_words import (
    ManagerWordsError,
    _is_whole_sentence,
    documents_from_source,
    load_manager_words,
    manager_words_from_artifact,
)
from squadopt.application.rotation_export import RotationExportRequest, export_rotation_evidence
from squadopt.data.errors import DataValidationError
from squadopt.data.snapshots import write_snapshot
from squadopt.data.sources.club_news_capture import CodedClub, write_club_news_capture
from squadopt.data.sources.club_news_coding import (
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    coding_prompt_sha256,
)
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FIXTURES_PAYLOAD
from squadopt.features.rotation_evidence_artifact import read_rotation_evidence_artifact


def _pair(
    tmp_path: Path,
    *,
    quote="Saka will miss the next Premier League match.",
    version=ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    extra_fixture=None,
    disposition="stated_expected_absent",
    body=None,
):
    root = tmp_path / "snapshots"
    if extra_fixture is None:
        decision = _decision(root)
    else:
        fixtures = json.loads(fixtures_payload())
        fixtures.append(extra_fixture)
        decision = write_snapshot(
            root,
            source=DECISION_SOURCE,
            captured_at_utc=CAPTURED_AT,
            payloads={
                BOOTSTRAP_PAYLOAD: bootstrap_payload(),
                FIXTURES_PAYLOAD: json.dumps(fixtures).encode(),
            },
        ).snapshot_id
    news = write_club_news_capture(
        root,
        # ``body`` is what the club published, when that is more than the quote itself.
        documents=(_document(quote if body is None else body),),
        coded=(
            CodedClub(
                "Arsenal",
                _response(quote=quote, label=disposition, version=version),
                version,
                coding_prompt_sha256(contract_version=version),
            ),
        ),
        clubs_declared=("Arsenal",),
        clubs_covered=("Arsenal",),
        captured_at_utc="2026-09-12T14:30:00Z",
    )
    result = export_rotation_evidence(
        RotationExportRequest(
            SEASON,
            TARGET_GAMEWEEK,
            DEADLINE,
            decision,
            root,
            None,
            tmp_path / "out",
            club_news_snapshot=news.snapshot_id,
            table_name="table",
        ),
        repository_commit="0" * 40,
    )
    return result["table_path"], result["manifest_path"], root / news.snapshot_id


def test_real_export_and_reader_bind_scope_publication_and_role(tmp_path):
    table_path, manifest_path, source = _pair(tmp_path)
    table = read_rotation_evidence_artifact(table_path, manifest_path)
    row = table[table.rotation_claim_observed].iloc[0]
    assert bool(row.rotation_claim_scope_verified)
    assert bool(row.rotation_claim_publication_verified)
    assert row.rotation_claim_fixture_scope == "upcoming_premier_league"
    words = load_manager_words(table_path, club_news_source=source)
    (word,) = words.words
    assert word.scope_verified and word.publication_verified
    assert word.role == "not_starting"
    assert word.words == "Saka will miss the next Premier League match."
    assert (
        word.publication_source_sha256 == hashlib.sha256(_document(word.words).content).hexdigest()
    )


@pytest.mark.parametrize(
    "quote",
    [
        "Saka will miss the cup match.",
        "Saka will miss the national team game.",
        "Saka missed the previous league match.",
        "Saka might miss the next league match.",
    ],
)
def test_real_export_preserves_wrong_or_uncertain_scope_without_a_role(tmp_path, quote):
    table_path, _, source = _pair(tmp_path, quote=quote)
    words = load_manager_words(table_path, club_news_source=source)
    (word,) = words.words
    assert word.words == quote and word.publication_verified
    assert not word.scope_verified and word.role is None


@pytest.mark.parametrize("version", ["rotation_claim_coding_v1", "rotation_claim_coding_v2"])
def test_replayed_legacy_evidence_never_silently_acquires_attestation(tmp_path, version):
    table_path, _, source = _pair(tmp_path, version=version)
    (word,) = load_manager_words(table_path, club_news_source=source).words
    assert word.words is not None
    assert not word.scope_verified and not word.publication_verified
    assert word.role is None


ABSENCE = "Saka will miss the next Premier League match."


@pytest.mark.parametrize(
    ("body", "quote"),
    [
        (f"It is not true that {ABSENCE}", ABSENCE),
        ("Neither Timber nor Saka will miss the next Premier League match.", ABSENCE),
        (f"Arteta denied that {ABSENCE}", ABSENCE),
        (f"Reports that {ABSENCE[:-1]} are wrong.", ABSENCE[:-1]),
        (f"{ABSENCE[:-1]} if he fails a late test.", ABSENCE[:-1]),
        (f"{ABSENCE[:-1]}, according to one report the club rejects.", ABSENCE[:-1]),
        (f"Arteta said {ABSENCE}", ABSENCE),
    ],
)
def test_a_quote_cut_from_inside_a_sentence_carries_no_authority(tmp_path, body, quote):
    """The quote's own wording passes the scope rule; the sentence it was cut from says more.

    The words stay readable and their publication stays verified. What is withheld is the
    statement's authority over a player: no role is taken from part of a sentence.
    """

    table_path, manifest_path, source = _pair(tmp_path, quote=quote, body=body)
    row = read_rotation_evidence_artifact(table_path, manifest_path)
    observed = row.loc[row.rotation_claim_observed].iloc[0]
    # The table accepts it: its rule reads the quote alone.
    assert bool(observed.rotation_claim_scope_verified)

    (word,) = load_manager_words(table_path, club_news_source=source).words

    assert word.words == quote and word.publication_verified
    assert not word.scope_verified and word.role is None


@pytest.mark.parametrize(
    ("body", "quote"),
    [
        (f"Team news follows. {ABSENCE} Timber is fit.", ABSENCE),
        (f"Team news\n{ABSENCE}\nTimber is fit.", ABSENCE),
        (f'Arteta spoke on Friday. "{ABSENCE}" More to follow.', ABSENCE),
        (f"Fitness update! {ABSENCE[:-1]}!", ABSENCE[:-1]),
        (f"Is he fit? {ABSENCE}", ABSENCE),
    ],
)
def test_a_quote_that_is_a_whole_sentence_of_the_source_still_binds(tmp_path, body, quote):
    table_path, _, source = _pair(tmp_path, quote=quote, body=body)

    (word,) = load_manager_words(table_path, club_news_source=source).words

    assert word.words == quote
    assert word.scope_verified and word.publication_verified
    assert word.role == "not_starting"


@pytest.mark.parametrize(
    ("text", "quote", "expected"),
    [
        ("Saka is out.", "Saka is out.", True),
        ("Saka is out", "Saka is out", True),
        ("First. Saka is out. Last.", "Saka is out.", True),
        ("First.  \t Saka is out", "Saka is out", True),
        ("He said: Saka is out.", "Saka is out.", False),
        ("Not that Saka is out.", "Saka is out.", False),
        ("Saka is out, they say.", "Saka is out", False),
        ("Saka is out for now", "Saka is out", False),
        ("Saka is outstanding.", "Saka is out", False),
        ("“Saka is out.”", "Saka is out.", True),
        ("(Saka is out)", "Saka is out", True),
    ],
)
def test_whole_sentence_boundaries(text, quote, expected):
    encoded = text.encode("utf-8")
    first = encoded.index(quote.encode("utf-8"))
    assert _is_whole_sentence(encoded, first, first + len(quote.encode("utf-8"))) is expected


def test_a_span_that_cuts_a_character_in_half_is_not_a_sentence():
    encoded = "Şaka is out.".encode()
    assert _is_whole_sentence(encoded, 1, len(encoded)) is False


def _rewrite(table_path, manifest_path, change):
    table = pd.read_csv(table_path)
    change(table)
    table.to_csv(table_path, index=False)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["table_sha256"] = hashlib.sha256(table_path.read_bytes()).hexdigest()
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")


def test_reader_rechecks_metadata_bytes_even_after_table_digest_is_updated(tmp_path):
    table_path, manifest_path, source = _pair(tmp_path)
    _rewrite(
        table_path,
        manifest_path,
        lambda frame: frame.loc.__setitem__(
            (frame.rotation_claim_observed, "rotation_claim_publication_source_sha256"), "f" * 64
        ),
    )
    (word,) = load_manager_words(table_path, club_news_source=source).words
    assert not word.publication_verified and word.role is None


def test_reader_rechecks_quoted_scope_even_when_table_claims_it_is_verified(tmp_path):
    table_path, manifest_path, source = _pair(tmp_path, quote="Saka will miss the cup match.")

    def change(frame):
        frame.loc[frame.rotation_claim_observed, "rotation_claim_fixture_scope"] = (
            "upcoming_premier_league"
        )
        frame.loc[frame.rotation_claim_observed, "rotation_claim_scope_verified"] = True

    _rewrite(table_path, manifest_path, change)
    (word,) = load_manager_words(table_path, club_news_source=source).words
    assert not word.scope_verified and word.role is None


def test_incomplete_attestation_is_refused_and_legacy_direct_words_are_safe(tmp_path):
    table_path, manifest_path, source = _pair(tmp_path)
    (word,) = load_manager_words(table_path, club_news_source=source).words
    with pytest.raises(ManagerWordsError, match="resolved complete"):
        replace(word, source_sha256=None, span_start=None, span_end=None)
    legacy = replace(word, scope_verified=False, publication_verified=False)
    assert legacy.role is None
    _rewrite(
        table_path,
        manifest_path,
        lambda frame: frame.loc.__setitem__(
            (frame.rotation_claim_observed, "rotation_claim_publication_source_sha256"), "broken"
        ),
    )
    with pytest.raises(DataValidationError, match="digest"):
        read_rotation_evidence_artifact(table_path, manifest_path)


def test_reader_without_the_exact_decision_snapshot_withholds_target_attestation(tmp_path):
    table_path, manifest_path, source = _pair(tmp_path)
    documents, kind, label = documents_from_source(source)
    words = manager_words_from_artifact(
        table_path,
        manifest_path,
        documents=documents,
        source_kind=kind,
        source_label=label,
    )
    (word,) = words.words
    assert word.publication_verified
    assert not word.scope_verified and word.role is None


@pytest.mark.parametrize(
    "quote",
    [
        "Saka is available. Timber will miss the next Premier League match.",
        "Timber will miss the next Premier League match.",
        "Saka and Timber will miss the next Premier League match.",
    ],
)
def test_wrong_player_predicate_stays_unapplied_even_after_forging_scope(tmp_path, quote):
    table_path, manifest_path, source = _pair(tmp_path, quote=quote)
    original = read_rotation_evidence_artifact(table_path, manifest_path)
    observed = original.loc[original.rotation_claim_observed].iloc[0]
    assert not bool(observed.rotation_claim_scope_verified)

    def change(frame):
        frame.loc[frame.rotation_claim_observed, "rotation_claim_fixture_scope"] = (
            "upcoming_premier_league"
        )
        frame.loc[frame.rotation_claim_observed, "rotation_claim_scope_verified"] = True

    _rewrite(table_path, manifest_path, change)
    (word,) = load_manager_words(table_path, club_news_source=source).words
    assert word.words == quote and word.publication_verified
    assert not word.scope_verified and word.role is None


def test_reader_binds_the_quote_to_the_actual_captured_player_id(tmp_path):
    table_path, manifest_path, source = _pair(tmp_path)

    def change(frame):
        # Keep the same unique roster, but redirect the cited Saka row to Timber.
        frame["player_id"] = frame.player_id.replace({900001: 900002, 900002: 900001})
        frame.sort_values("player_id", inplace=True)

    _rewrite(table_path, manifest_path, change)
    (word,) = load_manager_words(table_path, club_news_source=source).words
    assert word.player_id == 900002 and word.words is not None and "Saka" in word.words
    assert not word.scope_verified and word.role is None


@pytest.mark.parametrize(
    "kickoff,same_club,expected",
    [
        ("2026-09-12T14:00:00Z", True, False),
        ("2026-09-12T18:00:00Z", True, False),
        (None, True, False),
        ("2026-09-11T14:00:00Z", True, True),
        ("2026-09-13T14:00:00Z", True, True),
        (None, False, True),
    ],
)
def test_unassigned_fixture_remains_part_of_next_match_attestation(
    tmp_path, kickoff, same_club, expected
):
    teams = {team["name"]: team["id"] for team in json.loads(bootstrap_payload())["teams"]}
    template = json.loads(fixtures_payload())[0]
    extra = {
        **template,
        "id": 9999,
        "event": None,
        "team_h": teams["Arsenal"] if same_club else teams["Everton"],
        "team_a": teams["Fulham"],
        "kickoff_time": kickoff,
    }
    table_path, manifest_path, source = _pair(tmp_path, extra_fixture=extra)
    table = read_rotation_evidence_artifact(table_path, manifest_path)
    observed = table.loc[table.rotation_claim_observed].iloc[0]
    assert bool(observed.rotation_claim_scope_verified) is expected
    if not expected:
        # The reader must reconstruct the complete calendar instead of trusting a flag.
        _rewrite(
            table_path,
            manifest_path,
            lambda frame: frame.loc.__setitem__(
                (frame.rotation_claim_observed, "rotation_claim_scope_verified"), True
            ),
        )
    (word,) = load_manager_words(table_path, club_news_source=source).words
    assert word.scope_verified is expected
    assert word.role == ("not_starting" if expected else None)


@pytest.mark.parametrize(
    "quote",
    [
        "Saka is a rotation risk for the next Premier League match.",
        "Saka will be rested for the next Premier League match.",
        "Saka will be rotated in the next Premier League match.",
    ],
)
def test_verified_rotation_words_authorize_only_the_existing_captain_restriction(tmp_path, quote):
    table_path, _, source = _pair(tmp_path, quote=quote, disposition="stated_rotation_risk")
    words = load_manager_words(table_path, club_news_source=source)
    (word,) = words.words
    assert word.scope_verified and word.publication_verified and word.words == quote
    assert word.role == "not_captain"
    exclusion = words.exclusion()
    assert exclusion is not None and not exclusion.not_starting
    assert exclusion.not_captain == frozenset({word.player_id})


@pytest.mark.parametrize(
    "quote",
    [
        "Saka is fit for the next league match. Timber is a rotation risk.",
        "Saka is fit for the next league match.",
        "Saka is not a rotation risk for the next league match.",
    ],
)
def test_rotation_reader_rejects_wrong_predicate_even_after_forging_scope(tmp_path, quote):
    table_path, manifest_path, source = _pair(
        tmp_path, quote=quote, disposition="stated_rotation_risk"
    )
    table = read_rotation_evidence_artifact(table_path, manifest_path)
    observed = table.loc[table.rotation_claim_observed].iloc[0]
    assert not bool(observed.rotation_claim_scope_verified)

    def change(frame):
        frame.loc[frame.rotation_claim_observed, "rotation_claim_fixture_scope"] = (
            "upcoming_premier_league"
        )
        frame.loc[frame.rotation_claim_observed, "rotation_claim_scope_verified"] = True

    _rewrite(table_path, manifest_path, change)
    words = load_manager_words(table_path, club_news_source=source)
    (word,) = words.words
    assert word.words == quote and word.publication_verified
    assert not word.scope_verified and word.role is None
    assert words.exclusion() is None
