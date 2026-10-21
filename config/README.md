# Configuration

Operator configuration that the code reads at run time and that belongs in Git. Secrets and
machine-specific settings never go here; their examples are under [`deploy/`](../deploy/README.md).

## `leagues.json`

The list of classic leagues the site serves, in the `league_list_v1` contract. Each line names
a positive `league_id`, and no league appears twice; the committed file also gives each line a
`label` for people. The list names at least one league. Today it names one, league 352490.

`menu` is `full` or `device`; omitting it keeps `full`. A device league publishes the
standings, member squads, chip states and a device index without solving member advice.
The weekly journal reports preparation, projection, member and publication timings for
each league. League 352490 keeps its full menu during the transition.

| Reader | How it reads the list |
| --- | --- |
| `squadopt.contracts.league_list` | Defines the contract, the default path (`LEAGUE_LIST_FILE`) and `read_league_list`, which refuses a document that is not `league_list_v1` |
| The weekly run | `python -m squadopt.platform.weekly_operations --league-list config/leagues.json` captures every listed league's standings, renders each league's tree and writes the site's league directory |
| `scripts/seed_entry_registry.py` | `--league-list config/leagues.json` rebuilds the private entry registry for every listed league from a captured standings page |
| `scripts/measure_strategy_rule_scale.py` | Reads the list at the recorded revision for its measurement |

The path is part of the code (`LEAGUE_LIST_FILE`) and the operator's commands, so the file does
not move.

## Adding a league

A second league is the subject of issue #981 (one device-plan table per capture and a
device-first member page). The owner decided on 2026-10-07 that it is a classic league with
about 20 to 50 members in which the owner or İbo plays, and that it is named on #981
([docs/decisions.md](../docs/decisions.md)). Adding a line here changes what the weekly run
captures and renders; the member page finds a league through the published directory,
`web/public/data/leagues.json`, which the run writes.
