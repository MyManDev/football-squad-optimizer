<img align="right" src="web/public/favicon.svg" alt="SquadOpt" width="40" height="40" />

# SquadOpt

[![CI](https://github.com/MyManDev/football-squad-optimizer/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/MyManDev/football-squad-optimizer/actions/workflows/ci.yml)
[![MIT license](https://img.shields.io/badge/license-MIT-17402a)](LICENSE)

SquadOpt helps Fantasy Premier League managers plan the next gameweek, compare transfers
and keep up with their team.

**[Open SquadOpt](https://squadopt.mymandev.com)**: enter your classic league or FPL team number.
Our mini-league is **352490**.

The member page puts your squad on the pitch, with transfer suggestions, captain choices
and upcoming fixtures. One-week plans run on your device. After the deadline, the live score
includes captain points, automatic substitutions and transfer hits.

The app is built with Python, React and TypeScript, with HiGHS for device calculations.
See the [web guide](web/README.md) for how it works and the
[product roadmap](docs/product/roadmap.md#current-position) for the project record.

## Run locally

For the website, use Node.js 22:

```console
cd web
npm ci
npm run dev
```

The checkout includes the published data needed to browse the site.
See the [web guide](web/README.md) for frontend checks, or
[Contributing](CONTRIBUTING.md#setup) to set up Python and the backend.

<a id="do-the-work-in-a-worktree-not-in-this-checkout"></a>

Use a separate Git worktree for changes and keep the main checkout clean on `develop`.
The [worktree guide](docs/architecture/local_checkout.md) explains the commands and why
this matters for the weekly run.

## Repository map

| Path | Holds |
| --- | --- |
| [`src/squadopt/`](src/squadopt/README.md) | The Python package: data, prediction, optimization, the weekly run, the advice API and the research laboratory |
| [`scripts/`](scripts/README.md) | Operator commands, measurement runners, fixture generators and the release recipe |
| [`web/`](web/README.md) | The member website, its in-browser device solver and its browser tests |
| [`workers/`](workers/README.md) | Cloudflare Workers deployed apart from the static site |
| [`deploy/`](deploy/README.md) | Configuration examples and definitions for the advice backend and its supporting processes |
| [`config/`](config/README.md) | Operator configuration read at run time: the leagues the site serves |
| [`tests/`](tests/README.md) | Offline Python tests: unit, architecture, integration and shared fixtures |
| [`docs/`](docs/README.md) | Product, operations, architecture, research and contract documents |
| [`data/`](data/README.md) | Private local operational state, mostly ignored by Git; a checkout is not its backup |
| `.github/` | The CI, deployment and uptime workflows, Dependabot and code owners |
| [`ARCHITECTURE.md`](ARCHITECTURE.md) | Rings, deployment units, enforcement and known violations |
| [`CONTRIBUTING.md`](CONTRIBUTING.md) | Setup, checks and the pull request workflow |
| [`CHANGELOG.md`](CHANGELOG.md) | Software releases, newest first |
| `pyproject.toml` | Package metadata, tool settings and the import contracts |
| `constraints.txt` | Pinned versions the container and measurement checks install |
| `Dockerfile` | The one image the advice API and worker run from |
| [`LICENSE`](LICENSE) | The MIT license |

## Documentation

- [Documentation index](docs/README.md): start here for the full guide.
- [Architecture](ARCHITECTURE.md): how the code is organised and where a change belongs.
- [Operations](docs/operations/README.md): weekly publication, the API and deployment.
- [Research](docs/research/README.md): experiments, protocols and recorded results.
- [Contributing](CONTRIBUTING.md): setup, tests and the PR workflow.
