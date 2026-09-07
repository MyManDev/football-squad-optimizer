"""The publish flow's pure half: names, refusals, and the printed outward steps.

The git/gh subprocess half is deliberately thin and exercised by the operator; what a
test can pin is everything derived and everything refused.
"""

import pytest
from scripts.publish_gameweek_site import KINDS, PublishError, PublishNames, next_steps


def test_the_names_are_derived_from_season_gameweek_and_kind() -> None:
    names = PublishNames(season="2026-27", gameweek=2, kind="decision")
    assert names.branch == "feature/gw02-decision-site"
    assert names.worktree_directory == "../squadopt-gw02-decision"
    assert names.site_tag == "site-2026-27-gw02-decision"
    assert names.commit_message == "site: publish the gw02 decision view"


def test_settled_names_match_the_deploy_workflow_pattern() -> None:
    names = PublishNames(season="2026-27", gameweek=1, kind="settled")
    # The trusted workflow accepts ^site-\d{4}-\d{2}-gw\d{2}-(decision|settled|fix\d+)$.
    assert names.site_tag == "site-2026-27-gw01-settled"


@pytest.mark.parametrize(
    ("season", "gameweek", "kind"),
    [
        ("2026-27", 0, "decision"),
        ("2026-27", 39, "settled"),
        ("2026/27", 1, "decision"),
        ("2026-27", 1, "preview"),
    ],
)
def test_impossible_inputs_are_refused(season: str, gameweek: int, kind: str) -> None:
    with pytest.raises(PublishError):
        PublishNames(season=season, gameweek=gameweek, kind=kind)


def test_every_kind_has_a_distinct_tag() -> None:
    tags = {PublishNames(season="2026-27", gameweek=3, kind=kind).site_tag for kind in KINDS}
    assert len(tags) == len(KINDS)


def test_the_next_steps_name_the_tag_and_the_dispatch() -> None:
    names = PublishNames(season="2026-27", gameweek=2, kind="decision")
    text = next_steps(names, "https://example.invalid/pr/1")
    assert "site-2026-27-gw02-decision" in text
    assert "Deploy Pages" in text
    assert "https://example.invalid/pr/1" in text
    # The outward half is printed, never performed: these are instructions, not calls.
    assert "git tag -a" in text


def test_the_league_tree_is_built_from_a_live_capture_with_absolute_roots() -> None:
    from pathlib import Path

    from scripts.publish_gameweek_site import LeaguePublish

    league = LeaguePublish(
        league_id=352490,
        snapshot_id="fpl-live-20260911T100000Z-abc123def456",
        in_season_projection=Path("data/handoffs/2026-27-gw04.json"),
        workers=8,
    )
    arguments = league.build_arguments(Path("/tmp/site/web/public"))
    assert arguments[1:3] == ["-m", "scripts.build_league_site"]
    assert "--snapshot-root" in arguments and "--registry" in arguments
    assert arguments[arguments.index("--workers") + 1] == "8"
    assert arguments[arguments.index("--in-season-projection") + 1].endswith("2026-27-gw04.json")
    for flag in ("--snapshot-root", "--registry", "--archive-root"):
        assert Path(arguments[arguments.index(flag) + 1]).is_absolute()
    with pytest.raises(PublishError, match="live capture"):
        LeaguePublish(league_id=352490, snapshot_id="fpl-top100-x", in_season_projection=None)
    with pytest.raises(PublishError, match="workers"):
        LeaguePublish(
            league_id=352490, snapshot_id="fpl-live-x", in_season_projection=None, workers=0
        )


def test_the_scoreboard_is_built_beside_the_tree_from_the_same_capture_and_the_ledger() -> None:
    from pathlib import Path

    from scripts.publish_gameweek_site import LeaguePublish

    league = LeaguePublish(
        league_id=352490,
        snapshot_id="fpl-live-20260911T100000Z-abc123def456",
        in_season_projection=None,
        cohort_snapshot="fpl-top100-20260911T090000Z-abc123def456",
    )
    arguments = league.scoreboard_arguments(Path("/tmp/site/web/public"))
    assert arguments[1:3] == ["-m", "scripts.build_scoreboard"]
    assert arguments[arguments.index("--snapshot-id") + 1] == league.snapshot_id
    assert arguments[arguments.index("--cohort-snapshot") + 1] == league.cohort_snapshot
    for flag in ("--snapshot-root", "--registry", "--ledger-root"):
        assert Path(arguments[arguments.index(flag) + 1]).is_absolute()
    # Without a cohort capture the scoreboard is still built; its Top-100 column is null.
    bare = LeaguePublish(league_id=352490, snapshot_id="fpl-live-x", in_season_projection=None)
    assert "--cohort-snapshot" not in bare.scoreboard_arguments(Path("/tmp/site"))
    with pytest.raises(PublishError, match="fpl-top100"):
        LeaguePublish(
            league_id=352490,
            snapshot_id="fpl-live-x",
            in_season_projection=None,
            cohort_snapshot="fpl-live-y",
        )
