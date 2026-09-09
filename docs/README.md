# Documentation

Start with the area you are changing. These indexes organize the existing documents without
relocating immutable measurement records or changing their embedded source references.

| Area | Start here | What belongs here |
| --- | --- | --- |
| Product | [Product guide](product/README.md) | League-member flow, strategies, public contracts and UI |
| Operations | [Operations guide](operations/README.md) | Weekly execution, deployment, ledger and recovery procedures |
| Research | [Research guide](research/README.md) | Prediction, preregistrations, measurements and promotion evidence |
| Architecture | [System map](architecture/system_map.md) | Package boundaries, ownership and design decisions |
| Public schemas | [Contract directory](contracts/) | Versioned API, job, view, run and artifact schemas |
| Development | [Contributing](../CONTRIBUTING.md) | Current branch workflow and required checks |

## Runtime, research and local state

`src/squadopt` remains one installed package. A research module being present in main does
not activate its model or selector. Promotion and calibration boundaries still decide that.
The member website can read static publications; a deployed job API is a separate runtime
with separate acceptance evidence.

`data/` contains private operational inputs and records; generated `web/public/data` is the
published view. Git history and a site artifact do not replace a backup of private state.
`artifacts/` is for regenerable experiment expansions. Temporary work belongs in ignored
worktree scratch directories, not in product source.

## Historical records

Existing Markdown and JSON records remain at their established paths. Some paths are used
by tests or embedded in fingerprints/provenance. Follow
[the measurement-artifact decision](architecture/decisions/0003-measurement-artifacts.md)
before moving a record. Add a current-status note rather than rewriting a historical result.

The preserved pre-alignment development tree and retired topic commits are on
`archive/pre-main-alignment-20260909`; its `docs/archive/README.md` explains recovery.
That aggregate archive is not a branch to merge wholesale into develop.
