"""A verified source fact travels through the real writer/reader without a paid call."""

import hashlib
import json
import shutil
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

from squadopt.application import manager_words
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
from squadopt.data.sources import club_news_scope
from squadopt.data.sources.club_news_capture import (
    CodedClub,
    read_captured_responses,
    write_club_news_capture,
)
from squadopt.data.sources.club_news_coding import (
    ROTATION_CLAIM_CODING_CONTRACT_VERSION,
    coding_prompt_sha256,
)
from squadopt.data.sources.club_news_scope import is_whole_sentence
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
    prompt_model="synthetic-stub",
    extra_coded=(),
    extra_documents=(),
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
        documents=(_document(quote if body is None else body), *extra_documents),
        coded=(
            CodedClub(
                "Arsenal",
                _response(quote=quote, label=disposition, version=version),
                version,
                coding_prompt_sha256(prompt_model, contract_version=version),
            ),
            *extra_coded,
        ),
        clubs_declared=("Arsenal", *(entry.club for entry in extra_coded)),
        clubs_covered=("Arsenal", *(entry.club for entry in extra_coded)),
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


def test_forged_legacy_attestation_is_withheld_after_manifest_is_resealed(tmp_path):
    control_path, _, _ = _pair(tmp_path / "control")
    control = pd.read_csv(control_path)
    columns = [
        "rotation_claim_fixture_scope",
        "rotation_claim_scope_verified",
        "rotation_claim_publication_verified",
        "rotation_claim_publication_source",
        "rotation_claim_publication_source_sha256",
    ]
    table_path, manifest_path, source = _pair(
        tmp_path / "legacy", version="rotation_claim_coding_v2"
    )

    def forge(frame):
        frame[columns] = control[columns]
        frame["prompt_sha256"] = coding_prompt_sha256("synthetic-stub")

    _rewrite(table_path, manifest_path, forge)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["prompt_sha256"] = coding_prompt_sha256("synthetic-stub")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    table = read_rotation_evidence_artifact(table_path, manifest_path)
    observed = table.loc[table.rotation_claim_observed].iloc[0]
    assert bool(observed.rotation_claim_scope_verified)
    assert bool(observed.rotation_claim_publication_verified)
    (word,) = load_manager_words(table_path, club_news_source=source).words
    assert word.words is not None
    assert not word.scope_verified and not word.publication_verified
    assert word.role is None


def test_response_index_prompt_digest_must_match_its_recorded_model(tmp_path):
    table_path, manifest_path, source = _pair(tmp_path, prompt_model="different-synthetic-model")
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["prompt_sha256"] = coding_prompt_sha256("synthetic-stub")
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (word,) = load_manager_words(table_path, club_news_source=source).words
    assert word.words is not None
    assert not word.scope_verified and not word.publication_verified


def test_manifest_response_digests_must_match_bound_capture(tmp_path):
    table_path, manifest_path, source = _pair(tmp_path)
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    manifest["response_sha256s"] = ["f" * 64]
    manifest_path.write_text(json.dumps(manifest), encoding="utf-8")
    (word,) = load_manager_words(table_path, club_news_source=source).words
    assert word.words is not None
    assert not word.scope_verified and not word.publication_verified


@pytest.mark.parametrize(
    "mismatch",
    [
        "index-contract",
        "index-prompt",
        "response-model",
        "manifest-prompt",
        "body-contract",
        "completion-time",
        "source-label",
        "empty-responses",
        "empty-declared-digests",
        "empty-declared-digests-nothing-covered",
        "duplicate-declared-digests",
        "foreign-declared-digest",
        "omitted-covered-response",
    ],
)
def test_each_coding_attestation_condition_is_checked_independently(
    tmp_path, monkeypatch, mismatch
):
    table_path, manifest_path, source = _pair(tmp_path)
    table = read_rotation_evidence_artifact(table_path, manifest_path)
    _, kind, label = documents_from_source(source)
    snapshot = manager_words._club_news_snapshot(source, source.parent)
    responses = read_captured_responses(snapshot)
    assert manager_words._coding_attested(table, kind, label, source.parent)
    entry = responses[0]
    if mismatch == "index-contract":
        entry = replace(entry, prompt_contract_version="rotation_claim_coding_v2")
    elif mismatch == "index-prompt":
        entry = replace(entry, prompt_sha256=coding_prompt_sha256("another-model"))
    elif mismatch == "response-model":
        table.attrs["model_identifier"] = "another-model"
    elif mismatch == "manifest-prompt":
        table.attrs["prompt_sha256"] = coding_prompt_sha256("another-model")
    elif mismatch == "body-contract":
        body = json.loads(entry.response.text)
        body["contract_version"] = "rotation_claim_coding_v2"
        entry = replace(entry, response=replace(entry.response, text=json.dumps(body)))
        table.attrs["response_sha256s"] = (
            hashlib.sha256(entry.response.text.encode()).hexdigest(),
        )
    elif mismatch == "completion-time":
        table.attrs["club_news_captured_at_utc"] = "2026-09-12T14:00:00Z"
    elif mismatch == "source-label":
        label = "another-source-label"
    elif mismatch == "empty-responses":
        responses = ()
    elif mismatch == "empty-declared-digests":
        table.attrs["response_sha256s"] = ()
    elif mismatch == "empty-declared-digests-nothing-covered":
        # With no club covered, an omitted response is allowed, so only the
        # nonempty-list check can refuse an empty declaration.
        table.attrs["response_sha256s"] = ()
        table.attrs["clubs_covered"] = ()
    elif mismatch == "duplicate-declared-digests":
        table.attrs["response_sha256s"] *= 2
    elif mismatch == "foreign-declared-digest":
        # Every stored response stays declared, so only the subset check can refuse a
        # declared digest that the bound capture does not hold.
        table.attrs["response_sha256s"] = tuple(
            sorted({*table.attrs["response_sha256s"], "f" * 64})
        )
    elif mismatch == "omitted-covered-response":
        other = replace(
            entry, club="Man Utd", response=replace(entry.response, text=entry.response.text + " ")
        )
        responses = (*responses, other)
        table.attrs["clubs_covered"] = ("Arsenal", "Man Utd")
    if mismatch not in ("empty-responses", "omitted-covered-response"):
        responses = (entry,)
    monkeypatch.setattr(manager_words, "read_captured_responses", lambda _: responses)
    assert not manager_words._coding_attested(table, kind, label, source.parent)


@pytest.mark.parametrize("refused", [False, True])
def test_a_refused_club_response_keeps_the_other_clubs_attestation(tmp_path, refused):
    absent = "Mount will miss the next Premier League match."
    starts = "Mount will start the next Premier League match."
    url = "https://club.example/united/news"
    document = replace(
        _document(absent + "\n" + starts), club="Man Utd", requested_url=url, final_url=url
    )
    response = _response(quote=absent, label="stated_expected_absent")
    body = json.loads(response.text)
    body["documents"][0]["url"] = url
    claim = body["claims"][0]
    claim.update(player_name="Mount", team_name="Man Utd", source_url=url)
    if refused:
        body["claims"].append({**claim, "quote": starts, "disposition": "stated_expected_to_start"})
    response = replace(response, text=json.dumps(body))
    coded = CodedClub(
        "Man Utd",
        response,
        ROTATION_CLAIM_CODING_CONTRACT_VERSION,
        coding_prompt_sha256("synthetic-stub"),
    )
    table_path, manifest_path, source = _pair(
        tmp_path, extra_coded=(coded,), extra_documents=(document,)
    )
    manifest = json.loads(manifest_path.read_text(encoding="utf-8"))
    assert manifest["clubs_covered"] == (["Arsenal"] if refused else ["Arsenal", "Man Utd"])
    assert len(manifest["response_sha256s"]) == (1 if refused else 2)
    words = load_manager_words(table_path, club_news_source=source)
    saka = next(word for word in words.words if word.player_id == 900001)
    assert saka.scope_verified and saka.publication_verified and saka.role == "not_starting"
    assert words.exclusion().not_starting == (
        frozenset({900001}) if refused else frozenset({900001, 900009})
    )


ABSENCE = "Saka will miss the next Premier League match."

CUT_QUOTES = [
    (f"It is not true that {ABSENCE}", ABSENCE),
    ("Neither Timber nor Saka will miss the next Premier League match.", ABSENCE),
    (f"Arteta denied that {ABSENCE}", ABSENCE),
    (f"Reports that {ABSENCE[:-1]} are wrong.", ABSENCE[:-1]),
    (f"{ABSENCE[:-1]} if he fails a late test.", ABSENCE[:-1]),
    (f"{ABSENCE[:-1]}, according to one report the club rejects.", ABSENCE[:-1]),
    (f"Arteta said {ABSENCE}", ABSENCE),
    # A question is not a statement, whichever side of the quote its mark falls.
    (f"{ABSENCE[:-1]}? Not at all, said Arteta.", ABSENCE[:-1]),
    # An ellipsis is not the end of anything.
    (f"{ABSENCE[:-1]}... if he fails a late test.", ABSENCE[:-1]),
]


@pytest.mark.parametrize(("body", "quote"), CUT_QUOTES)
def test_a_quote_cut_from_inside_a_sentence_carries_no_authority(tmp_path, body, quote):
    """The quote's own wording passes the scope rule; the sentence it was cut from says more.

    The words stay readable and their publication stays verified. What is withheld is the
    statement's authority over a player: no role is taken from part of a sentence.
    """

    table_path, manifest_path, source = _pair(tmp_path, quote=quote, body=body)
    row = read_rotation_evidence_artifact(table_path, manifest_path)
    observed = row.loc[row.rotation_claim_observed].iloc[0]
    # The table refuses it too: the parser asks the reader's question of the cited bytes.
    # The label keeps what the quote's own wording says; only the flag is withheld.
    assert not bool(observed.rotation_claim_scope_verified)
    assert observed.rotation_claim_fixture_scope == "upcoming_premier_league"

    (word,) = load_manager_words(table_path, club_news_source=source).words

    assert word.words == quote and word.publication_verified
    assert not word.scope_verified and word.role is None


@pytest.mark.parametrize(("body", "quote"), CUT_QUOTES)
def test_a_table_written_before_the_parser_asked_for_a_sentence_is_refused_by_the_reader(
    tmp_path, body, quote
):
    """A pair exported before the parser checked sentences still says True for a cut quote.

    Such a pair is reused as it is, and no manifest records the parse contract, so the
    reader's own whole-sentence check is what keeps the claim from taking a role.
    """

    table_path, manifest_path, source = _pair(tmp_path, quote=quote, body=body)
    _rewrite(
        table_path,
        manifest_path,
        lambda frame: frame.loc.__setitem__(
            (frame.rotation_claim_observed, "rotation_claim_scope_verified"), True
        ),
    )
    row = read_rotation_evidence_artifact(table_path, manifest_path)
    assert bool(row.loc[row.rotation_claim_observed].iloc[0].rotation_claim_scope_verified)

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
    table_path, manifest_path, source = _pair(tmp_path, quote=quote, body=body)
    row = read_rotation_evidence_artifact(table_path, manifest_path)
    assert bool(row.loc[row.rotation_claim_observed].iloc[0].rotation_claim_scope_verified)

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
        ("He said: Saka is out.", "Saka is out.", True),
        ("Not that Saka is out.", "Saka is out.", False),
        ("Saka is out, they say.", "Saka is out", False),
        ("Saka is out for now", "Saka is out", False),
        ("Saka is outstanding.", "Saka is out", False),
        ("Saka is out? No.", "Saka is out", False),
        ("Saka is out?", "Saka is out?", False),
        ("Saka is out... for now.", "Saka is out...", False),
        ("Saka is out... for now.", "Saka is out", False),
        ("Saka is out\u2026 for now.", "Saka is out", False),
        ("Saka is out!", "Saka is out!", True),
        ("Is he fit? Saka is out.", "Saka is out.", True),
        # The colon that introduces reported words opens a statement; a clause run into
        # the words does not.
        ("Coach: Saka is out.", "Saka is out.", True),
        ('Arteta said: "Saka is out."', "Saka is out.", True),
        ("Arteta on Saka: he is out.", "he is out.", True),
        ("Arteta said Saka is out.", "Saka is out.", False),
        ("It is not true that Saka is out.", "Saka is out.", False),
        ("Not true: Saka is out, he said.", "Saka is out", False),
        ("“Saka is out.”", "Saka is out.", True),
        ("(Saka is out)", "Saka is out", True),
    ],
)
def test_whole_sentence_boundaries(text, quote, expected):
    encoded = text.encode("utf-8")
    first = encoded.index(quote.encode("utf-8"))
    last = first + len(quote.encode("utf-8"))
    assert _is_whole_sentence(encoded, first, last) is expected
    # The parser's copy, which sets the table's flag, answers the same.
    assert is_whole_sentence(encoded, first, last) is expected


def test_a_span_that_cuts_a_character_in_half_is_not_a_sentence():
    encoded = "Şaka is out.".encode()
    assert _is_whole_sentence(encoded, 1, len(encoded)) is False
    assert is_whole_sentence(encoded, 1, len(encoded)) is False


@pytest.mark.parametrize(
    "text",
    [
        'Arteta said: "Saka is out." Is he fit? No\u2026 Timber is.\nCoach: (Saka is out)!',
        "It is not true that Saka is out, he said... Really?! \u201cYes.\u201d\r\nEnd: [no] ",
        "Şaka?\tOut!  Out. 'In'.. ok",
        # Club pages write single quotes and the apostrophe as &rsquo;, which reads as U+2019.
        "Coach: \u2018Saka is out.\u2019 Timber\u2019s fine!\u2026 Wait\u2026\n\u2018Out\u2019",
        # A tab before a line break, a semicolon and a no-break space.
        "Team news\nSaka is out\t\nTimber is fit; Saka is out.\u00a0Odegaard\u00a0is out",
    ],
)
def test_the_parser_and_the_reader_hold_one_definition_of_a_whole_sentence(text):
    """The parser sets the table's flag and the reader refuses a claim by its own copy.

    Every span of each text gets the same answer from both. A few texts cannot show that
    the copies agree everywhere; the next test holds the code itself.
    """

    encoded = text.encode("utf-8")
    for first in range(len(encoded)):
        for last in range(first + 1, len(encoded) + 1):
            assert is_whole_sentence(encoded, first, last) is _is_whole_sentence(
                encoded, first, last
            ), (first, last)


def test_the_parser_and_the_reader_run_the_same_code_for_a_whole_sentence():
    """The two copies are the same function: the same constants and the same code.

    Only the docstrings differ. A change to one copy alone fails here, whatever text it
    would take to show the answers apart.
    """

    for name in ("_SPACE", "_MARKS", "_SENTENCE_END", "_BOUNDARY", "_OPENING", "_STATEMENT_END"):
        assert getattr(club_news_scope, name) == getattr(manager_words, name), name
    parser, reader = is_whole_sentence, _is_whole_sentence
    ours, theirs = parser.__code__, reader.__code__
    assert ours.co_code == theirs.co_code
    assert ours.co_names == theirs.co_names
    assert ours.co_varnames == theirs.co_varnames
    assert [value for value in ours.co_consts if value != parser.__doc__] == [
        value for value in theirs.co_consts if value != reader.__doc__
    ]


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
    news_only = tmp_path / "news-only"
    shutil.copytree(source, news_only / source.name)
    words = manager_words_from_artifact(
        table_path,
        manifest_path,
        documents=documents,
        source_kind=kind,
        source_label=label,
        snapshot_root=news_only,
    )
    (word,) = words.words
    assert word.publication_verified
    assert not word.scope_verified and word.role is None


def test_reader_without_bound_news_capture_withholds_both_attestations(tmp_path):
    table_path, manifest_path, source = _pair(tmp_path)
    documents, kind, label = documents_from_source(source)
    words = manager_words_from_artifact(
        table_path, manifest_path, documents=documents, source_kind=kind, source_label=label
    )
    (word,) = words.words
    assert not word.publication_verified
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
