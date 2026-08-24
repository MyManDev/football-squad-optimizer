# Provisional league UI contract

This note is the Package 5 PR hand-off for Issue #127. The TypeScript types in this
directory remain provisional until the data, application, and web owners freeze a shared
contract. They do not redefine the data-zone dataclass.

## Decisions already reflected

- The capture parser owns a data-zone twin of `EntryPicks`; the web layer does not import a
  Python/application type.
- `free_transfers` carries the usable value and `free_transfers_known` says whether the public
  source proved it. When false, the current rule-implied value is one and the UI warns that a
  banked second transfer may be invisible.
- `purchase_prices_known` is false when the source cannot publish purchase prices. The UI says
  explicitly that current prices are then used as selling prices and may overstate the budget.
- `source_snapshot_id` identifies the post-deadline capture used for the entry view and advice.

## Fields awaiting Issue #127 confirmation

### Envelope

- Final `contract_version` name replacing `provisional_league_ui_v1`.
- Whether `source_kind` remains part of the payload contract or stays a web-only example flag.
- Final production paths for members, entry squads, and per-mode/per-window advice.

### League members

- The stable league name and season/gameweek fields supplied by the standings capture.
- Rank movement semantics and the source of `movement_places`.
- Nullability of gameweek and total points before the first scored gameweek.
- The final representation of the virtual SquadOpt member. Human rows use a positive FPL
  `entry_id`; the system row currently uses `member_kind="system"` and `entry_id=null`.

### Entry squad

- Final manager/team label fields mapped from the entry endpoint.
- Player rows and their alignment with `PlayerView`.
- `bank_tenths`, `chips_used`, and the exact missing-data list.
- Whether the entry view carries `free_transfers_known` and `purchase_prices_known` directly or
  receives equivalent named diagnostics from the application view.
- Whether `squadopt_comparison` is emitted by application code or derived by the static-site
  builder once both settled scores exist.

### Entry advice

- The versioned identity of `mode`, `window`, and each move/reason code.
- Whether expected-point gain and expected-point cost are both emitted, and their rounding.
- The recommendation provenance and path tying the advice to its entry squad and capture.
- The explicit application invariant that every entry is evaluated independently and that the
  virtual SquadOpt team is absent from another member's objective.

Until those decisions land, production loaders fail closed when league JSON is absent; example
fixtures live under `web/src/fixtures` and are excluded from production builds.
