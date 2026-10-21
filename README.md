<img align="right" src="docs/images/brand/squadopt-mark.svg" alt="SquadOpt crest" width="64" />

# SquadOpt

[![CI](https://github.com/MyManDev/football-squad-optimizer/actions/workflows/ci.yml/badge.svg?branch=develop)](https://github.com/MyManDev/football-squad-optimizer/actions/workflows/ci.yml)
[![MIT license](https://img.shields.io/badge/license-MIT-17402a)](LICENSE)

SquadOpt is the app we're building for our Fantasy Premier League mini-league.
It helps us plan the next gameweek, compare transfers and keep up with the league.

**[Open SquadOpt](https://squadopt.mymandev.com)** — enter league **352490**, then choose your name.

The member page puts your squad on the pitch, with transfer suggestions, captain choices
and upcoming fixtures. You can follow the league race and save a squad card to share.
Supported one-week plans can also be calculated on your own device.

The app is built with Python, React and TypeScript, with HiGHS for device calculations.
The [product roadmap](docs/product/roadmap.md#current-position) covers what works today
and what we're still working on.

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

## Documentation

- [Documentation index](docs/README.md) — start here for the full guide.
- [Architecture](ARCHITECTURE.md) — how the code is organised and where a change belongs.
- [Operations](docs/operations/README.md) — weekly publication, the API and deployment.
- [Research](docs/research/README.md) — experiments, protocols and recorded results.
- [Contributing](CONTRIBUTING.md) — setup, tests and the PR workflow.
