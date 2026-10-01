"""A bounded real-provider trial cannot fetch or bill unselected clubs."""

from pathlib import Path

import pytest
from tests.unit.test_club_news_acquire import (
    ARSENAL,
    FETCHED_AT,
    SOURCES,
    _opener,
    _Provider,
    _registry,
    _roster_snapshot,
)

from squadopt.data.snapshots import read_snapshot
from squadopt.data.sources.club_news import ClubNewsError
from squadopt.data.sources.club_news_capture import read_captured_coverage
from squadopt.platform import club_news_acquire as acquisition
from squadopt.platform.club_news_provider import CodingProviderConfig


def test_selection_preserves_all_pages_without_duplicate_calls() -> None:
    assert acquisition.select_club_sources(SOURCES, ["Man Utd", "Man Utd"]) == SOURCES[1:]
    assert acquisition.select_club_sources(SOURCES, None) == SOURCES


@pytest.mark.parametrize("clubs", [[], [""], ["arsenal"], ["Arsenal", "missing"]])
def test_invalid_selection_cannot_broaden_a_run(clubs: list[str]) -> None:
    with pytest.raises(ClubNewsError, match="exactly match"):
        acquisition.select_club_sources(SOURCES, clubs)


def test_selected_club_reaches_one_model_and_separate_capture_root(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch, capsys: pytest.CaptureFixture[str]
) -> None:
    registry = _registry(tmp_path / "sources.json", SOURCES)
    roster_root = tmp_path / "roster"
    snapshot = _roster_snapshot(roster_root)
    capture_root = tmp_path / "news"
    requested: list[str] = []
    coded: list[str] = []
    opener = _opener()

    def fetch(request, timeout):
        requested.append(request.full_url)
        return opener(request, timeout)

    class Provider(_Provider):
        def code(self, documents, roster):
            coded.append(documents[0].club)
            return super().code(documents, roster)

    config = CodingProviderConfig("gemini", "synthetic-model", "synthetic-key")
    monkeypatch.setattr(acquisition, "build_coding_provider", lambda *a, **k: (Provider(), config))
    result = acquisition.main(
        [
            "--roster-snapshot",
            snapshot,
            "--snapshot-root",
            str(roster_root),
            "--registry",
            str(registry),
            "--club",
            "Arsenal",
            "--capture-root",
            str(capture_root),
        ],
        environ={},
        opener=fetch,
        now=lambda: FETCHED_AT,
        sleeper=lambda _: None,
    )
    assert result == 0
    printed = capsys.readouterr().out
    assert "Read and coded: 1 [Arsenal]" in printed
    assert "Registered, not selected: 1 [Man Utd]" in printed
    assert "Not registered:" in printed
    assert coded == ["Arsenal"]
    assert all(url.endswith("/robots.txt") or url == ARSENAL for url in requested)
    assert capture_root.is_dir()
    assert len(list(roster_root.iterdir())) == 1
    captures = list(capture_root.iterdir())
    assert len(captures) == 1
    assert read_captured_coverage(read_snapshot(capture_root, captures[0].name)) == (
        ("Arsenal",),
        ("Arsenal",),
        (),
    )


def test_unknown_club_refuses_before_roster_provider_or_network(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    registry = _registry(tmp_path / "sources.json", SOURCES)

    def forbidden(*args, **kwargs):
        raise AssertionError("Selection must be checked first.")

    monkeypatch.setattr(acquisition, "read_snapshot", forbidden)
    monkeypatch.setattr(acquisition, "build_coding_provider", forbidden)
    assert (
        acquisition.main(
            ["--roster-snapshot", "not-read", "--registry", str(registry), "--club", "Missing"],
            environ={},
            opener=forbidden,
        )
        == 1
    )


@pytest.mark.parametrize("teams", [{1: "Arsenal", 2: "Arsenal"}, {1: "Unknown FC"}])
def test_invalid_roster_scope_refuses_before_provider_or_fetch(
    teams: dict[int, str],
    tmp_path: Path,
    monkeypatch: pytest.MonkeyPatch,
    capsys: pytest.CaptureFixture[str],
) -> None:
    registry = _registry(tmp_path / "sources.json", SOURCES)
    roster_root = tmp_path / "roster"
    snapshot = _roster_snapshot(roster_root)

    def forbidden(*args, **kwargs):
        raise AssertionError("No provider setup or request before the roster is valid.")

    monkeypatch.setattr(acquisition, "team_names", lambda bootstrap: teams)
    monkeypatch.setattr(acquisition, "build_coding_provider", forbidden)
    assert (
        acquisition.main(
            [
                "--roster-snapshot",
                snapshot,
                "--snapshot-root",
                str(roster_root),
                "--registry",
                str(registry),
                "--club",
                "Arsenal",
            ],
            environ={},
            opener=forbidden,
        )
        == 1
    )
    assert capsys.readouterr().out.startswith("Refused:")
