"""The roadmap's current position agrees with the records it cites.

`docs/product/roadmap.md` is where the README sends a reader for where the product is, and
its current-position section promises that each line names the code or the record it can be
checked against. A review of the rewrite that made that promise found four lines that the
records contradict:

- GW4 was cited as a decision on the bare component base through
  `web/public/data/2026-27/gw04/recommendation.json`. That file is the control replay written
  after the deadline (its `mode` is `replay`, and so is the ledger's row); the advice members
  were given for GW4 was solved on the Top-100 uplift, as `docs/top100_effect_prereg.md`
  records.
- The eighth prospective gameweek of the Phase A exit was put at GW11 by counting ledger rows,
  GW1 among them, although the exit counts paired gameweeks and the benchmark protocol says
  GW1 can never be one.
- The declared strategy rule's suggestion was listed under what the backend computes on
  request. Only the static build computes it.
- "The last outage issue" named one that a later issue, opened and closed the same day, had
  already replaced.

A second review found a fifth: the roadmap said model-read club news reaches members as the
manager's word. Every published member index that ever carried the word named the committed
synthetic fixture as its source (GW5), and GW6 carries none.

Each test below reads the record and holds the roadmap to it. The records are the authority;
what a test needs from the roadmap's wording is kept to one phrase or one list, so a line that
stops agreeing with its record fails here before a reader finds it.
"""

from __future__ import annotations

import json
import re
from pathlib import Path

from squadopt.application.manager_words import SOURCE_CLUB_NEWS_CAPTURE
from squadopt.application.strategies.rule import STRATEGY_RULE_ID
from squadopt.prediction.elite_evidence import COMPONENT_ELITE_MODEL_VERSION

REPOSITORY_ROOT = Path(__file__).resolve().parents[2]
ROADMAP = REPOSITORY_ROOT / "docs" / "product" / "roadmap.md"
SEASON_DATA = REPOSITORY_ROOT / "web" / "public" / "data" / "2026-27"
MEMBER_ADVICE = REPOSITORY_ROOT / "web" / "public" / "data" / "league" / "advice"
TOP100_PROTOCOL = REPOSITORY_ROOT / "docs" / "top100_effect_prereg.md"
BENCHMARK_PROTOCOL = REPOSITORY_ROOT / "docs" / "benchmark_v2_prereg.md"
UPTIME_WORKFLOW = REPOSITORY_ROOT / ".github" / "workflows" / "backend-uptime.yml"
BACKEND_PACKAGES = (
    REPOSITORY_ROOT / "src" / "squadopt" / "platform",
    REPOSITORY_ROOT / "src" / "squadopt" / "api",
)

#: How many paired gameweeks the Phase A exit asks for (`benchmark_v2_prereg.md`).
PAIRED_WEEKS_REQUIRED = 8

#: The Top-100 protocol's words for a gameweek whose deciding handoff carried the uplift.
DECIDED_ON_THE_UPLIFT = "the handoff that decided carried the uplift"

#: The phrases that put a real club's news in front of members.
REAL_CLUB_NEWS_CLAIMS = re.compile(
    r"\breach(?:es|ed)? (?:the )?members\b|\bevidence in the product\b", flags=re.I
)


def _flat(text: str) -> str:
    return re.sub(r"\s+", " ", text).strip()


def _sentences(text: str) -> list[str]:
    """Every sentence of the document, with its line breaks folded.

    Paragraphs and list items are split first, so a sentence never runs across two of them;
    a sentence ends at a full stop followed by white space. A dotted file name has no space
    after its dot and is not split.
    """

    found: list[str] = []
    for block in re.split(r"\n\s*\n|\n(?=\s*- )", text):
        found.extend(part for part in re.split(r"(?<=\.)\s+", _flat(block)) if part)
    return found


def _ledger_rows() -> list[dict[str, object]]:
    document = json.loads((SEASON_DATA / "ledger.json").read_text(encoding="utf-8"))
    rows: list[dict[str, object]] = document["payload"]["rows"]
    return rows


def _week(gameweek: int) -> re.Pattern[str]:
    return re.compile(rf"\bGW{gameweek}\b")


def test_a_replay_is_never_cited_as_a_decision_without_being_called_one() -> None:
    """A replay's model version is not what members were given that week.

    For every gameweek the published ledger holds as a replay, a sentence that names that
    week together with the replay's file or the model version the replay names has to say
    it is a replay.
    """

    text = ROADMAP.read_text(encoding="utf-8")
    replays = [int(str(row["gameweek"])) for row in _ledger_rows() if row["mode"] == "replay"]
    assert replays, "the ledger holds no replay, so this test no longer checks anything"

    unlabelled: list[str] = []
    for gameweek in replays:
        path = f"gw{gameweek:02d}/recommendation.json"
        replay = json.loads((SEASON_DATA / path).read_text(encoding="utf-8"))
        assert replay["payload"]["metadata"]["mode"] == "replay"
        version = str(replay["payload"]["model_version"])
        for sentence in _sentences(text):
            names_the_week = path in sentence or _week(gameweek).search(sentence) is not None
            names_the_replay = path in sentence or version in sentence
            if names_the_week and names_the_replay and "replay" not in sentence.lower():
                unlabelled.append(sentence)
    assert not unlabelled, "\n".join(["these cite a replay as a decision:", *unlabelled])


def test_a_week_decided_on_the_uplift_is_named_with_the_uplift() -> None:
    """The Top-100 protocol records which week's deciding handoff carried the uplift.

    The roadmap has to name that week beside the uplift's model version in one sentence, so
    it cannot say, as it once did, that no published decision carried the uplift.
    """

    rows = [
        line
        for line in TOP100_PROTOCOL.read_text(encoding="utf-8").splitlines()
        if line.startswith("| ") and DECIDED_ON_THE_UPLIFT in line
    ]
    weeks = sorted(int(row.split("|")[1].strip()) for row in rows)
    assert weeks, f"the Top-100 protocol no longer says '{DECIDED_ON_THE_UPLIFT}' of any week"

    sentences = _sentences(ROADMAP.read_text(encoding="utf-8"))
    unnamed = [
        f"GW{gameweek}"
        for gameweek in weeks
        if not any(
            _week(gameweek).search(sentence) and COMPONENT_ELITE_MODEL_VERSION in sentence
            for sentence in sentences
        )
    ]
    assert not unnamed, (
        f"the roadmap never names {', '.join(unnamed)} with `{COMPONENT_ELITE_MODEL_VERSION}`, "
        "although the members' advice that week was solved on it"
    )


def test_the_eighth_paired_gameweek_is_not_put_earlier_than_the_ledger_allows() -> None:
    """A paired gameweek needs a live decision and a cohort, and GW1 has no cohort.

    The earliest week that could be the eighth assumes every live ledger week after GW1 is
    paired and every week after the ledger's last is decided live. A roadmap that names an
    earlier week counted something the benchmark protocol does not.
    """

    protocol = _flat(BENCHMARK_PROTOCOL.read_text(encoding="utf-8"))
    assert "Gameweek 1 has no honest current-season prior ranking" in protocol
    assert "fewer than eight valid paired gameweeks" in protocol

    rows = _ledger_rows()
    candidates = sorted(
        int(str(row["gameweek"]))
        for row in rows
        if row["mode"] == "live" and int(str(row["gameweek"])) > 1
    )
    last = max(int(str(row["gameweek"])) for row in rows)
    earliest = (
        candidates[PAIRED_WEEKS_REQUIRED - 1]
        if len(candidates) >= PAIRED_WEEKS_REQUIRED
        else last + PAIRED_WEEKS_REQUIRED - len(candidates)
    )

    stated = [
        int(week)
        for week in re.findall(
            r"\bGW(\d+) (?:is|would be|will be) the eighth\b",
            _flat(ROADMAP.read_text(encoding="utf-8")),
        )
    ]
    early = [f"GW{week}" for week in stated if week < earliest]
    assert not early, (
        f"the roadmap names {', '.join(early)} as the eighth; GW{earliest} is the earliest"
    )


def test_the_backend_is_not_said_to_compute_what_only_the_static_build_does() -> None:
    """The strategy rule's suggestion is built with the static tree, not on request."""

    backend_suggests = any(
        "suggest_strategy" in source.read_text(encoding="utf-8")
        or STRATEGY_RULE_ID in source.read_text(encoding="utf-8")
        for package in BACKEND_PACKAGES
        for source in package.rglob("*.py")
    )
    text = ROADMAP.read_text(encoding="utf-8")
    on_request = re.search(
        r"\*\*Computed on request\*\*(?P<block>.*?)(?=\nWhat a strategy may publish|\n### )",
        text,
        flags=re.DOTALL,
    )
    assert on_request is not None, "the roadmap no longer has its 'Computed on request' list"
    block = on_request["block"]
    if not backend_suggests:
        assert STRATEGY_RULE_ID not in block
        assert "suggest" not in block.lower()


def test_the_outage_record_is_the_label_listing_not_a_latest_issue() -> None:
    """The uptime workflow opens a new issue at every outage, so "the last one" goes stale.

    The roadmap points at the listing by the label the workflow actually applies, and makes
    no claim about which outage was the most recent.
    """

    workflow = UPTIME_WORKFLOW.read_text(encoding="utf-8")
    assert '"backend-down"' in workflow
    text = ROADMAP.read_text(encoding="utf-8")
    assert "gh issue list --label backend-down --state all" in text
    recency = [
        sentence
        for sentence in _sentences(text)
        if re.search(r"\b(?:last|latest|most recent)\b[^.]*\boutage", sentence, flags=re.I)
    ]
    assert not recency, "\n".join(["these name a latest outage, which goes stale:", *recency])


def test_the_managers_word_is_not_said_to_carry_club_news_no_published_week_read() -> None:
    """A member index says where its manager's word came from, and so far none read a club.

    Each published member index names the source of the words it carries
    (`evidence.source_kind`); only a club-news capture is a real club's page, and the
    committed fixture is example data. The published tree holds the latest week only, so this
    reads what it holds: while no index in it carries a real read, no sentence about the
    manager's word or club news may say it reaches members or is evidence in the product,
    and the roadmap has to say the switch has run on example data.
    """

    indexes = sorted(MEMBER_ADVICE.glob("*/index.json"))
    assert indexes, "the published tree holds no member index, so this test checks nothing"
    sources = set()
    for index in indexes:
        evidence = json.loads(index.read_text(encoding="utf-8"))["payload"].get("evidence")
        if isinstance(evidence, dict) and evidence.get("available") is True:
            sources.add(str(evidence.get("source_kind")))
    if SOURCE_CLUB_NEWS_CAPTURE in sources:
        return

    about_the_word = [
        sentence
        for sentence in _sentences(ROADMAP.read_text(encoding="utf-8"))
        if re.search(r"manager's word|club[ -]news", sentence, flags=re.I)
    ]
    claims = [sentence for sentence in about_the_word if REAL_CLUB_NEWS_CLAIMS.search(sentence)]
    assert not claims, "\n".join(
        ["these put club news in front of members, which no published index shows:", *claims]
    )
    assert any("example data" in sentence for sentence in about_the_word), (
        "the roadmap never says the manager's word has run on example data"
    )
