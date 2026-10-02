"""Held synthetic playlist shapes from the official injury widget; no network."""

import json
from dataclasses import replace
from datetime import UTC, date, datetime
from pathlib import Path

import pytest

from squadopt.contracts import injuries as injury_contract
from squadopt.data.snapshots import read_snapshot, write_snapshot
from squadopt.data.sources.fpl_live import BOOTSTRAP_PAYLOAD, FPL_LIVE_SOURCE
from squadopt.data.sources.premier_league_injuries import (
    API_PREFIX,
    PAGE_URL,
    injury_playlist_url,
    read_official_injuries,
)
from squadopt.platform.club_news_fetch import ClubSource
from squadopt.platform.official_injury_capture import (
    capture_official_injuries,
    read_official_injury_capture,
    registered_details_links,
)

NOW = "2026-10-02T10:00:00Z"
PAGE = (
    b"<p>During the 2026/27 season</p><p>Last updated: 16:50 BST, 1 October 2026.</p>"
    b'<section data-widget="injury-news/injury-news" data-playlist-id="123"></section>'
)

URL = API_PREFIX + "123?detail=DETAILED"


def documents():
    bootstrap = {
        "teams": [{"id": 1, "name": "Liverpool"}, {"id": 2, "name": "Man Utd"}],
        "elements": [
            {
                "code": 10,
                "team": 1,
                "web_name": "Alpha",
                "first_name": "Alice",
                "second_name": "Alpha",
            },
            {"code": 20, "team": 2, "web_name": "Beta", "first_name": "Bob", "second_name": "Beta"},
        ],
        "events": [{"id": 1, "deadline_time": "2026-08-15T10:00:00Z", "finished": False}],
    }
    row = {
        "response": {
            "type": "promo",
            "title": "Alice Alpha",
            "description": "Ankle",
            "date": "2026-09-20T10:00:00Z",
            "publishFrom": 1790325911951,
            "lastModified": 1790325953891,
            "links": [{"promoUrl": "https://www.liverpoolfc.com/news/alpha-injury-update"}],
            "references": [{"type": "SDP_FOOTBALL_PLAYER", "sid": "9999"}],
        }
    }
    section = {
        "response": {
            "type": "playlist",
            "title": "Injury News - Liverpool",
            "items": [row],
            "pageInfo": {"numPages": 1, "numEntries": 1},
        }
    }
    return bootstrap, {"id": 123, "type": "playlist", "items": [section]}


def report(bootstrap=None, playlist=None, page=PAGE):
    base_boot, base_list = documents()
    return read_official_injuries(
        page=page,
        playlist=json.dumps(
            base_list if playlist is None else playlist, ensure_ascii=False, indent=2
        ).encode(),
        bootstrap=json.dumps(base_boot if bootstrap is None else bootstrap).encode(),
        observed_at=NOW,
        season="2026-27",
    )


def test_nested_source_sections_and_clocks_are_distinct_and_spans_replay():
    boot, source = documents()
    raw = json.dumps(source, ensure_ascii=False, indent=2).encode()
    found = report(boot, source)
    assert found.received_clubs == ("Liverpool",)
    assert found.missing_clubs == ("Man Utd",)
    assert found.source_updated_at == "2026-10-01T15:50:00Z"
    fact = found.facts[0]
    assert fact.player_id == 10 and fact.identity_reason == "exact_name"
    assert fact.source_date == "2026-09-20T10:00:00Z" and fact.source_date != found.observed_at
    span = fact.source_span
    assert span.json_pointer == "/items/0/response/items/0/response"
    assert (
        json.loads(raw[span.start : span.end])
        == source["items"][0]["response"]["items"][0]["response"]
    )


def test_official_alias_is_checked_against_the_actual_roster():
    boot, source = documents()
    source["items"][0]["response"]["title"] = "Injury News - Manchester United"
    found = report(boot, source)
    assert found.received_clubs == ("Man Utd",)
    assert found.facts[0].player_id is None  # another club's exact name cannot cross-join


def test_unknown_club_and_sdp_player_id_do_not_fabricate_roster_matches():
    boot, source = documents()
    row = source["items"][0]["response"]["items"][0]["response"]
    row["title"] = "Unknown Player"
    row["references"][0]["sid"] = "10"
    assert report(boot, source).facts[0].player_id is None
    source["items"][0]["response"]["title"] = "Injury News - Unknown FC"
    found = report(boot, source)
    assert found.unknown_source_clubs == ("Unknown FC",)
    assert found.received_clubs == () and found.facts == ()


def test_ambiguous_exact_names_are_unmapped():
    boot, source = documents()
    boot["elements"].append({**boot["elements"][0], "code": 11})
    fact = report(boot, source).facts[0]
    assert fact.player_id is None and fact.identity_reason == "ambiguous_name"


def test_empty_section_is_not_an_absence_or_healthy_claim():
    boot, source = documents()
    section = source["items"][0]["response"]
    section["items"] = []
    section["pageInfo"]["numEntries"] = 0
    found = report(boot, source)
    assert found.received_clubs == ("Liverpool",) and found.facts == ()


def test_bad_row_does_not_erase_other_clubs_or_healthy_rows():
    boot, source = documents()
    section = source["items"][0]["response"]
    section["items"].append({"response": {"type": "promo", "title": None}})
    section["pageInfo"]["numEntries"] = 2
    found = report(boot, source)
    assert len(found.facts) == 1 and found.incomplete_clubs == ("Liverpool",)
    assert len(found.refusals) == 1


@pytest.mark.parametrize(
    "page", [b"<p>No widget</p>", PAGE + PAGE, PAGE.replace(b"123", b"../123")]
)
def test_missing_duplicate_or_unsafe_widget_refused(page):
    with pytest.raises(ValueError):
        injury_playlist_url(page)


def test_wrong_season_or_playlist_identity_refused():
    with pytest.raises(ValueError, match="season"):
        report(page=PAGE.replace(b"2026/27", b"2024/25"))
    boot, source = documents()
    source["id"] = 124
    with pytest.raises(ValueError, match="identity"):
        report(boot, source)


def test_details_only_route_within_existing_exact_club_origin_and_path():
    found = report()
    fact = found.facts[0]
    found = replace(
        found,
        facts=(
            replace(
                fact,
                details_urls=(
                    *fact.details_urls,
                    "https://www.liverpoolfc.com/tickets/alpha",
                    "https://www.liverpoolfc.com.evil.test/news/a",
                    "https://www.liverpoolfc.com/news/%2e%2e/tickets",
                    "https://www.liverpoolfc.com@evil.test/news/a",
                ),
            ),
        ),
    )
    source = ClubSource("Liverpool", "https://www.liverpoolfc.com/news", date(2026, 10, 1))
    links = registered_details_links(found, (source,))
    assert links == {source.url: (fact.details_urls[0],)}


def test_capture_is_four_requests_no_provider_and_exact_offline_replay(tmp_path: Path, monkeypatch):
    # Exercise dormant transport only with synthetic bytes, never an operational override.
    monkeypatch.setattr(injury_contract, "OFFICIAL_INJURY_SOURCE_ENABLED", True)
    boot, source = documents()
    roster = write_snapshot(
        tmp_path / "roster",
        source=FPL_LIVE_SOURCE,
        captured_at_utc="2026-10-01T10:00:00Z",
        payloads={BOOTSTRAP_PAYLOAD: json.dumps(boot).encode()},
    )
    requested = []

    def fetch(url):
        requested.append(url)
        if url.endswith("/robots.txt"):
            return b"User-agent: *\nAllow: /\n"
        return PAGE if url == PAGE_URL else json.dumps(source).encode()

    meta, found = capture_official_injuries(
        roster_snapshot=read_snapshot(tmp_path / "roster", roster.snapshot_id),
        capture_root=tmp_path / "central",
        terms_read_on=date(2026, 10, 1),
        fetch=fetch,
        now=lambda: datetime(2026, 10, 2, 10, tzinfo=UTC),
        sleeper=lambda _: None,
    )
    assert requested == [
        "https://www.premierleague.com/robots.txt",
        PAGE_URL,
        "https://api.premierleague.com/robots.txt",
        URL,
    ]
    assert (
        read_official_injury_capture(read_snapshot(tmp_path / "central", meta.snapshot_id)) == found
    )


def test_stale_terms_refuse_before_any_fetch(tmp_path: Path, monkeypatch):
    monkeypatch.setattr(injury_contract, "OFFICIAL_INJURY_SOURCE_ENABLED", True)
    boot, _ = documents()
    meta = write_snapshot(
        tmp_path,
        source=FPL_LIVE_SOURCE,
        captured_at_utc=NOW,
        payloads={BOOTSTRAP_PAYLOAD: json.dumps(boot).encode()},
    )
    with pytest.raises(ValueError, match="current dated"):
        capture_official_injuries(
            roster_snapshot=read_snapshot(tmp_path, meta.snapshot_id),
            capture_root=tmp_path / "out",
            terms_read_on=date(2026, 1, 1),
            fetch=lambda _: pytest.fail("No request before terms validation"),
            now=lambda: datetime(2026, 10, 2, tzinfo=UTC),
        )


@pytest.mark.parametrize("field,value", [("items", None), ("pageInfo", "malformed")])
def test_malformed_received_section_is_explicitly_incomplete(field, value):
    boot, source = documents()
    source["items"][0]["response"][field] = value
    found = report(boot, source)
    assert found.received_clubs == ("Liverpool",)
    assert found.incomplete_clubs == ("Liverpool",)
    assert len(found.refusals) == 1


def test_utf8_second_row_span_is_into_original_bytes():
    boot, source = documents()
    section = source["items"][0]["response"]
    second = {
        "response": {"type": "promo", "title": "Émile André", "description": "Knee", "links": []}
    }
    section["items"].append(second)
    section["pageInfo"]["numEntries"] = 2
    boot["elements"].append(
        {"code": 30, "team": 1, "web_name": "André", "first_name": "Émile", "second_name": "André"}
    )
    raw = json.dumps(source, ensure_ascii=False, indent=2).encode()
    fact = report(boot, source).facts[1]
    assert fact.player_id == 30
    assert json.loads(raw[fact.source_span.start : fact.source_span.end]) == second["response"]


def test_public_record_is_explicitly_bounded_and_keeps_unmapped_rows_as_counts():
    found = report()
    assert found.public_record()["facts"] == []
    public = found.public_record([10])
    assert public["listed_rows"] == public["mapped_rows"] == 1
    assert public["facts"][0]["player_id"] == 10
    assert "source_span" not in json.dumps(public)
    assert "sha256" not in json.dumps(public)
    with pytest.raises(ValueError, match="at most fifty"):
        found.public_record(range(1, 52))
    with pytest.raises(ValueError, match="positive player"):
        found.public_record([True])


def test_public_record_filters_unsafe_links_without_rewriting_captured_facts():
    found = report()
    links = (
        "https://www.liverpoolfc.com/news/held",
        "javascript:alert(1)",
        "https://name:secret@example.com/held",
        "https://example.com\\other",
        "https://example.com:invalid/held",
        "https://example.com:0/held",
        "https://example.com:65536/held",
        "https://example.com/held\x00",
    )
    found = replace(found, facts=(replace(found.facts[0], details_urls=links),))
    public = found.public_record([10])
    assert public["facts"][0]["details_urls"] == [links[0]]
    assert found.facts[0].details_urls == links


def test_disabled_source_refuses_capture_before_clock_fetch_or_write(tmp_path):
    assert injury_contract.OFFICIAL_INJURY_SOURCE_ENABLED is False
    boot, _ = documents()
    meta = write_snapshot(
        tmp_path / "roster",
        source=FPL_LIVE_SOURCE,
        captured_at_utc=NOW,
        payloads={BOOTSTRAP_PAYLOAD: json.dumps(boot).encode()},
    )
    with pytest.raises(ValueError, match="central official injury source is disabled"):
        capture_official_injuries(
            roster_snapshot=read_snapshot(tmp_path / "roster", meta.snapshot_id),
            capture_root=tmp_path / "not-created",
            terms_read_on=date(2026, 10, 2),
            fetch=lambda _: pytest.fail("Disabled source must not fetch"),
            now=lambda: pytest.fail("Disabled source must refuse before acquisition starts"),
        )
    assert not (tmp_path / "not-created").exists()


def test_disabled_capture_cli_refuses_before_reading_roster(tmp_path, monkeypatch, capsys):
    from squadopt.platform import official_injury_capture as capture_module

    monkeypatch.setattr(capture_module, "read_snapshot", lambda *_: pytest.fail("No source reads"))
    assert (
        capture_module.main(
            [
                "--snapshot-root",
                str(tmp_path),
                "--roster-snapshot",
                "not-read",
                "--capture-root",
                str(tmp_path / "not-created"),
                "--terms-read-on",
                "2026-10-02",
            ]
        )
        == 1
    )
    assert "central official injury source is disabled" in capsys.readouterr().out
    assert not (tmp_path / "not-created").exists()


def test_disabled_held_capture_reader_refuses_before_payload_use(tmp_path):
    meta = write_snapshot(
        tmp_path,
        source="official-pl-injuries",
        captured_at_utc=NOW,
        payloads={"not-an-injury-report.json": b"{}"},
    )
    with pytest.raises(ValueError, match="central official injury source is disabled"):
        read_official_injury_capture(read_snapshot(tmp_path, meta.snapshot_id))


def test_duplicate_unknown_club_labels_are_one_public_coverage_name():
    from jsonschema import Draft202012Validator

    boot, source = documents()
    source["items"][0]["response"]["title"] = "Injury News - Unknown FC"
    source["items"].append(source["items"][0])
    found = report(boot, source)
    assert found.unknown_source_clubs == ("Unknown FC",)
    Draft202012Validator(injury_contract.official_injuries_schema()).validate(found.public_record())


@pytest.mark.parametrize("value", ["2026-10-03T00:00:00Z", "2026-10-02T10:00:01Z", "2026-10-03"])
def test_future_row_clock_is_withheld_without_losing_the_fact(value):
    boot, source = documents()
    source["items"][0]["response"]["items"][0]["response"]["date"] = value
    found = report(boot, source)
    assert len(found.facts) == 1 and found.facts[0].injury == "Ankle"
    assert found.facts[0].source_date is None
    assert found.public_record([10])["facts"][0]["source_date"] is None
    assert found.incomplete_clubs == ("Liverpool",)
    assert "date is after observation" in found.refusals[0]


def test_missing_link_target_does_not_discard_the_row_or_its_valid_link():
    boot, source = documents()
    links = source["items"][0]["response"]["items"][0]["response"]["links"]
    links.extend([{"label": "Details"}, None])
    found = report(boot, source)
    assert len(found.facts) == 1 and found.facts[0].injury == "Ankle"
    assert found.facts[0].details_urls == (links[0]["promoUrl"],)
    assert found.incomplete_clubs == ("Liverpool",)
    assert len(found.refusals) == 2
    assert all("promoUrl; link withheld" in reason for reason in found.refusals)


def test_afc_bournemouth_alias_requires_bournemouth_in_the_captured_roster():
    boot, source = documents()
    source["items"][0]["response"]["title"] = "Injury News - AFC Bournemouth"
    assert report(boot, source).unknown_source_clubs == ("AFC Bournemouth",)
    boot["teams"][0]["name"] = "Bournemouth"
    found = report(boot, source)
    assert found.received_clubs == ("Bournemouth",)
    assert found.facts[0].player_id == 10
