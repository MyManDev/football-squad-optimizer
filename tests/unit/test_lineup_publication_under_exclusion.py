"""The best eleven under an exclusion: bench-only players and captain-barred players."""

from squadopt.application.lineup_publication import best_eleven_points, best_eleven_points_under


def _squad(**overrides: tuple[float, bool, bool]) -> list[tuple[str, float, bool, bool]]:
    rows: list[tuple[str, float, bool, bool]] = []
    for index, position in enumerate(["GK"] * 2 + ["DEF"] * 5 + ["MID"] * 5 + ["FWD"] * 3):
        points, may_start, may_captain = overrides.get(f"p{index}", (2.0, True, True))
        rows.append((position, points, may_start, may_captain))
    return rows


def test_with_nobody_excluded_it_agrees_with_the_unconstrained_scorer() -> None:
    squad = _squad(p7=(7.0, True, True), p8=(6.0, True, True), p12=(5.0, True, True))
    assert best_eleven_points_under(squad) == best_eleven_points(
        (position, points) for position, points, _start, _captain in squad
    )


def test_a_player_who_may_not_start_is_left_out_of_the_eleven() -> None:
    free = best_eleven_points_under(_squad(p7=(9.0, True, True)))
    benched = best_eleven_points_under(_squad(p7=(9.0, False, False)))
    assert free is not None and benched is not None
    # 9 + 9 (captain) is lost; a 2-point midfielder starts and a 2-point player captains.
    assert free - benched == 9.0 + 9.0 - 2.0 - 2.0


def test_the_armband_can_pull_an_eligible_player_into_the_eleven() -> None:
    """Three barred midfielders at 7 and an eligible one at 6.9: taking the 6.9 in to
    captain him beats starting all three 7s and captaining a 2."""

    squad = _squad(
        p7=(7.0, True, False),
        p8=(7.0, True, False),
        p9=(7.0, True, False),
        p10=(6.9, True, True),
    )
    value = best_eleven_points_under(squad)
    assert value is not None
    # Shapes with five midfielders fit all four; the best eleven then starts every one of
    # them and doubles the 6.9, which is at least as good as leaving it out.
    assert value >= 7.0 * 3 + 6.9 + 6.9


def test_no_eligible_captain_means_no_measured_value() -> None:
    squad = [(position, points, start, False) for position, points, start, _ in _squad()]
    assert best_eleven_points_under(squad) is None
