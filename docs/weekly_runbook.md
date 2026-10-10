# Weekly runbook — the league advice loop

One command produces everything the league members' pages need for the coming
gameweek, from the capture to the site pull request, and — when asked — decides our
own squad on the way:

```bash
python -m squadopt.platform.weekly_operations --season 2026-27 --gameweek 5 --league-list config/leagues.json --workers 8 --run-id 2026-27-gw05-decision
```

`config/leagues.json` (`league_list_v1`) is the one place that says which classic leagues the
site serves; `--league <id>`, repeatable, names them on the command line instead (the list
path is relative to `--workspace`). Every league in the list is rendered from the one
capture into its own tree (`data/leagues/<league id>/`), with its own scoreboard, and the
site's directory (`data/leagues.json`) lists them all. Each league is stamped after its own
solves; the directory, written by the last league, carries the latest stamp, which is the
publication's. A league renders the registered entries its captured standings page names.

The capture stage refuses, before any solve, a registry that names its seed leagues and was
not seeded from every listed league (one league or several: a league the registry was not
seeded from would be rendered with only the members the two share), and with more than one
league a capture that lacks a listed league's standings page. So the first run over a new
list stops there, after its capture, and its message names the seed command for exactly the
run's leagues (`python -m scripts.seed_entry_registry --league <id> ... --snapshot-id <that
capture>`, which registers every member of every league once). Then start a new run (new
`--run-id`, no `--snapshot-id`): the registry is a capture input, so a resume is refused, and
only a new capture holds the new members' picks.

The advice record and the member histories name one league
(`weekly_suggestion_eval.SUPPORTED_LEAGUE_ID`); the other leagues are rendered and published,
not recorded, until the record contract carries the league. The league receipt says so per
league (`leagues.<id>.advice_recorded`), and its top-level `advice_recorded` is whether any
league was recorded; a run asked to record whose list has none of them records nothing and
logs `tick.week.advice_record.skipped`. The per-league `member_notes`, `removed` and
`top100_note` sit under `leagues.<id>`; `legacy_tree` (top level) says what became of a tree
from before the directory, and `removed_trees` (top level) names the trees of leagues the list
no longer has, which the run removes so a dropped league's member names leave the site.

By hand, `scripts.build_league_site --league <id>` rebuilds one league from a capture. It
keeps the other leagues the directory lists only when their trees were rendered from the same
capture, and refuses otherwise (the site would serve two captures); it records advice only
for the league the record names.

`--decide` is deliberately absent from that line. It is the members' loop that runs every
week; our own squad is a separate decision with a precondition that is not currently met
(below).

`--run-id` is optional. Left out, the runner generates
`week-<season>-gw<NN>-<UTC stamp>-<hex>` and prints it; an explicit id such as the one above
is accepted as given. Either way it is the id `--resume` needs back.

Run the installed package from the clean checkout you mean to publish from (or pass
`--workspace`). The legacy `python -m scripts.run_week` flags still delegate to this runner.
Start after the previous gameweek's picks are public and inside the lead-time window below — "before the deadline" is a floor, not the policy.
`--dry-run` prints the plan and runs nothing. Without `--decide` the ledger is not
touched and the loop is the members' loop alone.

The preview now defaults to `data/runtime/weekly/<run-id>/preview`, rather than tracked
`web/public`. `--out` still selects another destination. A source-controlled destination can
make the checkout dirty and must be reconciled before a resume; the default avoids that.
Every stage records its inputs, exit/result and output hashes. Reuse the same arguments and
`--run-id` with `--resume`; changed inputs or outputs refuse. `--status --run-id <id>` verifies
results, and `--expected-at <UTC instant>` additionally evaluates missed completion. See
[weekly operations](architecture/weekly_operations.md) for recovery and scheduling limits.

## What it does, in order

| step | service / compatibility command | what it needs | what it leaves |
| --- | --- | --- | --- |
| top100 | `scripts.capture_top100_cohort`, `scripts.capture_elite_picks`, `scripts.export_player_evidence` | before the deadline; target gameweek ≥ 2 | `fpl-top100-*` and `fpl-elite-picks-*` snapshots; `artifacts/phase_b/player_evidence_v1_<season>_gw<NN>_top100.{csv,manifest.json}` |
| capture | `squadopt.platform.fpl_capture.capture` with the entry registry and the league list | `data/entries/registry.json` (`scripts.seed_entry_registry`) | `data/snapshots/fpl-live-<utc>-<hash>/` with bootstrap, fixtures, every played event-live document from GW1, every member's three documents and the standings page |
| settled outcomes | `application.settled_outcomes.export_settled_outcomes` | stored captures no newer than the selected capture; an earlier week with both pre-deadline and finished/checked captures | immutable table/manifest pairs under `artifacts/rotation`, plus per-run reports; unavailable pairs are stated, never filled with zero outcomes |
| rotation | `scripts.export_rotation_evidence --snapshot <capture> --deadline-utc …` (only with `--rotation`) | the capture above, and either the committed synthetic fixture or the real club-news capture selected by `--rotation-capture` | `artifacts/rotation/rotation_evidence_v4_<season>_gw<NN>_<news hash>_decision_<decision hash>.{csv,manifest.json}` for a real club-news capture; `rotation_evidence_v4_<season>_gw<NN>_<decision hash>.{csv,manifest.json}` — one row per roster player in that capture, one categorical claim field, and the citation carried as a document digest plus a byte span rather than as text. Written exactly once per capture; a pair already on disk for it is reused rather than remade. With `--rotation`, the league stage also receives this table and its source, and solves every member one-week pure-points plan with the manager word switched on: `advice/<id>/saf-puan/1/hoca-sozu.json` beside the baseline, the index saying `evidence.available` and where the words came from, the site showing the switch, and an example-data label on every surface while the source is the fixture. Without `--rotation` the index says `no_evidence_this_run`, the switch is disabled with that reason, and a `hoca-sozu.json` an earlier publish left is removed (printed by `scripts.build_league_site`, and recorded under the league stage's `removed` in the run's receipt, with every member note under `member_notes`). **So a publish that should keep the switch must pass `--rotation`** (`--rotation` alone reads the fixture; `--rotation-capture <id>` reads a real club-news capture, which the registered hosts can now produce). A quote whose words carry wording the site never publishes is withheld and the page says so; the constraint still applies |
| handoff | `scripts.build_projection_handoff --snapshot-id <capture> --evidence-table … --evidence-manifest …` | the capture above and the evidence | `data/handoffs/<season>-gw<NN>.json` — the Phase C component projection with the bounded Top-100 uplift on top (`phase-c-component-elite-top100-v1`); `--projection component-only` leaves the uplift out; without settled live history the producer falls back to the legacy blend and says so |
| decide | `squadopt.application.commands.decide`, in-process (only with `--decide`; `--chip` as `squadopt gameweek decide` takes it) | the capture and the handoff, each verified at its own stage; a ledger that holds the previous gameweek, and — with `--chip` — an open, unspent chip window, both checked **before** the first capture, so a week the ledger cannot start refuses without spending one. The mode is derived, never asserted: `live` only when this run took the capture and the clock is still before its deadline; a reused `--snapshot-id`, or a run past the deadline, is recorded `replay`. A gameweek the ledger already holds is skipped rather than refused, so a run that died after the decision can rebuild the rest of the week | `data/ledger/<season>/gw<NN>/` — decision, projections, report, manifest; the report is printed |
| league | `scripts.build_league_site --workers N` | the capture and the handoff | `<preview>/data/leagues/<league id>/**` (and `<preview>/data/leagues.json`, the directory that lists every published league with its tree): `members.json`, `entries/<id>.json`, `advice/<id>/saf-puan/1.json`, `advice/<id>/saf-puan/3.json` and `5.json` (the week-1 projection repeated over the calendar, published with its stated limits), `advice/<id>/<strategy>/1.json` (the standings neighbour), `advice/<id>/<strategy>/1/vs-<rival>.json`, `advice/<id>/index.json` (`windows` names what solved per strategy; a window that did not is in `unavailable` with its reason). Without `--publish` or `--record-advice` this is a local preview and writes no advice record. Either option makes this step write this checkout's `data/advice_records/<season>/gw<NN>/entry-<id>/<snapshot id>/` from the same solve, before `history/<id>.json` reads it, unless `--publish --no-advice-record` turns the record off; the records the season already held are declared as this stage's inputs, so a week whose records moved between two runs shows in the journal |
| site | `scripts.build_site` | the ledger and captures | `<preview>/data/**` season views (they read the ledger, so after the decision) |
| scoreboard | `scripts.build_scoreboard --cohort-snapshot <fpl-top100 id> --elite-snapshot <fpl-elite-picks id>` | the capture, the registry, the ledger, and the Top-100 captures when they were taken or reused | `<preview>/data/leagues/<league id>/scoreboard.json`: per played gameweek: the game's average and highest, every member's gross week, hit cost and net, our ledger row with its mode and its scoring basis, the Top-100 mean for the cohort capture's own week with the basis it is on; `null` wherever a file on disk does not say |
| publish | `platform.weekly_publish.publish` with `copy_preview_builder` (only with `--publish`); by hand, `scripts.publish_gameweek_site --kind decision --gameweek <NN> --run-id <run id>` | a clean `origin/develop` at the run's source revision | an owned `.codex-tmp/publications/gw<NN>-decision[-<suffix>]` worktree, a commit of `web/public/data` holding the preview's `data/` tree, copied in over the tree the worktree carried from `origin/develop` and read back byte for byte before the commit (nothing is solved again: what was previewed is what ships), a push, a pull request; then the printed human steps: merge, release, tag, dispatch. The advice record at this checkout's `data/advice_records/<season>/gw<NN>/entry-<id>/<snapshot id>/` is the league step's, written from the solve that ships when the run was built with `--publish` or `--record-advice`: the immutable record of what each member was told, digests included, so the week can be reviewed after the site has been overwritten. One record per capture: publishing a week twice (mid-week, then again before the deadline from a fresher capture) records both, and the review page reads the last capture that preceded the deadline. What is **refused** is rebuilding *one* capture into different bytes: the handoff, switch artifacts, settings and code revision also affect advice, but cannot overwrite the same capture's immutable record, with the differing fields named; if the deadline will not wait, `--no-advice-record` publishes without recording and leaves the first record and the difference to be reconciled afterwards. Typed by hand, `scripts.publish_gameweek_site --run-id <run id>` publishes the preview a run already built, through the same copy and read-back; it solves nothing and writes no advice record itself. It reads that run's journal and, before any git command, refuses a run that has not completed every stage before `publish` or whose league, site or scoreboard outputs no longer hold the bytes the run recorded, and a run whose league stage recorded no advice: one built without `--publish` or `--record-advice`, as the standard command above is. `--no-advice-record` publishes such a run anyway and says it records nothing, so a week meant to be published by hand is built with `--record-advice`. The publication base is then held to the run's recorded source revision, the check the run's own publish stage makes: if develop has moved, start a new run. A settled view is published with `--kind settled --preview <dir> --source-commit <revision>`; the candidate records no revision of its own, so the base is checked against the revision the operator names. For any gameweek the candidate is built in a clean checkout at `origin/develop`: copy `web/public/data` to `<dir>/data`, then run `scripts.build_site --season <season> --out <dir>`, which writes the settled season views over that copy and leaves the members' league trees (`leagues/<league id>/` and `leagues.json`) and the rest as the site carries them (the build the settled publish used to run inside the publication worktree, over the same carried tree; run from the checkout, it reads that checkout's handoff and archive roots where the old run read the worktree's); `--source-commit` is that checkout's `git rev-parse HEAD`. `scripts.build_settled_site` builds only the 2026-27 GW5 candidate. A candidate that lacks a top-level entry the publication carries (a `scripts.build_site` run into an empty directory lacks `leagues/`, `leagues.json`, `players.json` and `404.html`) is refused before the commit, because the copy would delete it from the site |

The current rotation pair binds the real news capture and the decision capture in its
filename; each hash above is the final 12 characters of the corresponding snapshot ID.
A reused decision with `--rotation-capture` requires that exact readable pair before any
stage spends work. An older news-only filename is not a substitute. V2/V3 pairs remain
readable for historical replay, without claiming the new V4 binding.

Before publishing, run `python -m scripts.check_league_tree <preview>/data` against the
candidate tree, or use the publication worktree's `web/public/data`. It runs the
publication identity, wider menu, Top 100 and manager's-word release checks and exits
non-zero on any finding. Its final verdict covers all four checks.
It expects what each member's `advice/<id>/index.json` declares: an absence the index
states in the producer's shape with a string reason (the menu a `--skip-top100` run leaves
out, a window or rival pair listed in `unavailable`, a member with no advice this week) is
printed as a stated absence and is not a finding, while a document the index names and the
tree lacks is (the one-week `saf-puan/1.json` included), and so is an index that fails the
page's `assertAdviceIndex` (the envelope is not checked) or a Top 100 menu, an `unavailable`
row or a refused member stated without its reason. The manager's word and the chip menu are
read as the producer writes them; their absences are not checked for a reason.
Pass a site origin URL instead to check its published league trees (every tree
`/data/leagues.json` lists, or `/data/league/` on a site from before the directory). The URL
form is narrower: its figure sweep covers only the word files it fetches, while the local
check sweeps every word file under each listed tree. This command only reads the tree;
it does not publish or solve anything.

Existing captures can be named explicitly: `--cohort-snapshot` / `--elite-snapshot`
reuse the Top-100 captures (an export already on disk for that picks capture is reused,
and the named cohort capture also feeds the scoreboard), `--snapshot-id` reuses a live
capture — then the Top-100 captures must be reused or skipped too, because the
projection refuses evidence captured after the decision capture — and `--skip-top100`
leaves the evidence out (the scoreboard's Top-100 column is then `null`). The command
stops at the first refusal and records what refused. An explicit `--handoff` reuses a verified
prebuilt projection for this exact capture and week; it requires `--skip-top100`, bypasses
`--projection` build selection, and records that no new evidence was applied.

**The Top 100 influence menu rides on the evidence stage.** When the Top-100 stages ran,
the league stage receives the export and gives every member their one-week pure-points plan
at each setting 5, 10, 20, 30, 40 and 50: `advice/<id>/saf-puan/1/top100-<w>.json`, and
`top100-<w>-hoca-sozu.json` beside it when `--rotation` ran too. The plan is chosen on
points scaled by `1 + w/100 * count/100` and every number in it is scored on the base
projection; the price is the base-model difference against the member's own plan at 0. The
index's `top100` block names the files, or says why there are none
(`no_top100_this_run`, `top100_inputs_refused`, `published_plan_carries_top100`), and the
league receipt's `leagues.<id>.top100_note` carries the refusal. The export passes the handoff's own gate
before anything is solved, so the menu needs a live capture taken **after** the Top-100
export. **The published plan must stay at 0, so a week that offers the menu is run with
`--projection component-only`**: the default `component` bakes the frozen uplift into the
handoff, and the loader then refuses the menu (`published_plan_carries_top100`) rather than
stack a member's setting on it. The Friday run is therefore
`--rotation --projection component-only --record-advice` with no `--skip-top100` and no
`--snapshot-id`. `--record-advice` records every rendered member in the league stage even
without publication, stamped with the commit that ran. Publishing requires a separate run
with `--publish --publish-suffix 8`. It can reuse that capture with `--snapshot-id <that
capture>` and the corresponding capture-reuse options described above only while develop
has not moved: a record is immutable, so a publish from a later commit cannot record the
same capture again. Keep develop still from the recording run until the publish, or the
reuse is refused. The preflight reads the reused capture's records and refuses before any
capture or solve, naming the capture, the recorded commit and this run's commit. After
develop has moved, either publish from a fresh capture taken before the deadline (no
`--snapshot-id`), or add `--no-advice-record` to publish the reused capture without
recording it: the existing records are kept, and the journal (`no_advice_record` under
`publication_options`, `advice_recorded: false` in the league stage) and the run log
(`tick.week.advice_record.skipped`) say that nothing was recorded. Choose an unused suffix:
GW05 then uses `feature/gw05-decision-site-8`. An existing suffix refuses in preflight,
before capture or solving. Without a suffix the original branch name is unchanged.
`--dry-run` prints the recording choice, suffix and branch; it writes nothing. Options
cannot be added or changed on `--resume`; it must repeat the original run's options.
The menu reaches beyond the one-week pure-points plan, against the **default rival only**:
every pure-points window (`saf-puan/<3|5>/top100-<w>.json`), each rival strategy at one week
(`<strategy>/1/vs-<rival>/top100-<w>.json`), and each rival strategy over a window, at 0
(`<strategy>/<3|5>/vs-<rival>.json`, written whenever the windows are, with or without the
export) and under each setting (`.../vs-<rival>/top100-<w>.json`). The index lists them under
`top100.documents`, `windows` and `computed`. A window's band holds the first week only, at
the level one transfer reaches, and a window's price is against the member's pure-points
window at 0. Since #655 window solves run at a linearization level that proves most of
them: the GW6 rehearsal proved all 300 three-week solves and 241 of the 300 five-week ones.
A price is stated as the cost where both plans are proved, as at most where only the priced
window's proof is missing, and not at all where the pure-points window's proof is missing
(`publish_price_ceiling` in `src/squadopt/application/advice.py`).
This adds about forty window solves per member, so plan the league stage
in hours, not minutes, and start a deadline-day run in the morning: the full menu took 74
minutes with twelve workers on the GW6 rehearsal (timings below). The full menu against
every rival is the on-demand path's work. A hand build passes the export to
`scripts.build_league_site` with `--top100-evidence <csv>`. The same handoff feeds
`--decide`, so on such a week the system's own squad is also decided without the uplift,
which departs from `docs/phase_c_operational_elite_policy.md`'s default; that is the
owner's call before `--decide` is passed, and the policy's rule itself is unchanged.

**The chips a member may choose need no flag and no extra input.** The planner still decides
no chip for anyone (a finite window counts nothing for holding one back). The league stage
reads each member's own chip history from the capture and, for every chip they can still
play this gameweek, solves their one-week pure-points plan with that chip forced:
`advice/<id>/saf-puan/1/chip-<wildcard|freehit|bboost|3xc>.json`. The index's `chips` block
names the files, the chips the member holds, and why any chip has none (`already_played`,
`window_not_open`, `free_hit_played_last_gameweek`, `not_solved_for_member`), or says why
there are none at all (`no_chip_left`, `chip_history_unknown`). Each document states what
the chip week is expected to score above the member's own plan without it, this gameweek
only, beside the sentence saying a later gameweek's value is not measured; it combines with
neither the manager's word nor a Top 100 setting. With `--record-advice` or `--publish`,
the advice record includes every published choice, including chip and switch documents,
with their selection settings and file digests. A Wildcard or Free Hit solve is a
whole-squad problem: on the GW5 capture one took 25 to 42
seconds with three members solved side by side on a machine already running a league
build, so budget about a minute and a half per member. A chip file an earlier publish wrote
and this one did not is removed and printed with the other removals.

An optional second live capture in the final 24 hours before the deadline can be
compared with the earlier capture using `squadopt.platform.capture_measurement`
([commands and interpretation](operations/capture_measurement.md)). This offline
audit counts availability and news changes; it does not change the weekly decision.

**`rotation` is the one step that works the other way round: it is off unless `--rotation`
asks for it.** That is deliberate and it is about honesty of the record, not convenience.
`--rotation` alone still reads the committed *synthetic* fixture under `data/sample/`, so a
step that ran by default would write fixture-derived claims into a real week's artifact, and
that artifact is the one the member-facing card reads. Real hosts are registered now
(`docs/club_news_sources.md`) and `--rotation-capture <id>` reads a real capture from them,
but that does not change the default: naming the capture is a second deliberate act, and the
flag is still the consent for the first. Reusing a live
capture with `--rotation` requires that capture's export **already on disk**, refused before
anything is spent: the pair records when it was generated, the claim chain has to be frozen
before the decision capture, and re-exporting now for a capture already taken stamps it
afterwards however promptly it is done.

The elite-picks capture travels with the cohort capture into the scoreboard, and it is
what lets the Top-100 column be **net**: the Overall standings publish `event_total`
gross of the week's transfer cost, so a mean over the standings alone is not on the
members' basis. The picks documents carry each member's own `entry_history`, so when the
capture covers all hundred of that week the mean is `points - event_transfers_cost` per
member. Without one — `--skip-top100`, or a picks capture that missed a member — the mean
is published **gross**, labelled gross, and the card says it does not compare with the
net columns beside it.

## Timing

### The order the week's instants must keep

Every step below records an instant, and the readers refuse a step whose instant is
out of order. The list is the whole order for one deadline, with the check that holds
each line; the commands are in the table above and in the documents named.

1. **Club news is fetched, then coded from one observation instant taken after the last
   page was read** (`scripts.capture_club_news`; `docs/club_news_configuration.md`). The
   coding refuses a document fetched after its observation instant.
2. **The decision capture is taken** (`fpl_capture.capture`). The rotation export refuses a
   news document fetched at or after the decision capture, and the bundle refuses a news
   capture that completed after it.
3. **The football forecast is built with its components from that capture**
   (`scripts.build_football_forecast --with-components`), and **the projection handoff from
   the capture and the evidence** (`scripts.build_projection_handoff`). The bundle binds
   the forecast's and the handoff's fingerprints to the capture and refuses any other.
4. **The weekly run**: rotation export, league tree, advice record, site, scoreboard,
   publish pull request (`platform.weekly_operations`). The journal refuses a stage whose
   predecessor did not complete; the league tree carries one `generated_at_utc`, which the
   bundle requires to be after the capture.
5. **The bundle is sealed against the published tree** (`scripts.prepare_football_bundle`;
   `docs/operations/official_injury_discovery.md`; with several leagues, `--league <id>` names
   the tree it seals, as `scripts.add_device_plan_inputs --league <id>` names the tree it
   augments). Its marker is written last, after every
   copy has been read back through the production validators; a name or an input the reader
   would refuse is refused before anything is copied.
   A new seal with retained scoreboard, history or series-horizon files requires
   `publication-identity.json`. The next normal league publication establishes it.
   See `docs/contracts/league_publication_identity_v1.md` for replay and identity rules.
6. **The site pull request merges through develop's merge queue, the release is cut and
   tagged, the backend is restarted** (`docs/deployment_runbook.md`). The restart reads the
   one capture every published human entry names, on the public site and locally, and
   refuses when the two differ.

A step run out of this order is not late; its artifact is refused by the next reader.

- **Take the capture two to three hours before the deadline, not the night before.**
  The capture must be open for the requested gameweek — the command reads the deadline
  back from it and refuses a mismatch — but "open" is a floor, not the policy. The week
  is decided from that one capture and availability is applied once from it, so a note
  the platform adds afterwards is not late, it is absent, and no later step recovers it.
  Running a day or more ahead leaves that whole span unseen.
- The size of what is unseen is measured, not argued.
  `python -m scripts.measure_capture_lead_time` reads the stored captures and writes
  `docs/capture_lead_time.json`: per gameweek, each capture's lead time and how many of
  the source's own notes were stamped inside the window between the earliest and the
  latest capture. Take a second capture inside the window and the week's own numbers
  appear there. A gameweek captured once reports **not measured**, never zero.
- Two to three hours, rather than as late as possible, for one reason: everything the
  week needs has to fit **before** the deadline, in order — capture, handoff, decide,
  and the league tree, which is over half an hour for fifteen members (below). A capture
  at thirty minutes leaves no room for the league tree at all, let alone for a step that
  fails and has to be run again.
- Do not read the feed's own `news` as cover for capturing early. The rotation-lane
  brief (2026-09-08) measured its items on the 2026-09-07 capture at a median of 22.9
  days behind it, with 3 of 71 added since the previous deadline; no artifact in this
  repository carries that measurement yet, so it is cited here rather than claimed.
- **`--rotation` runs after the capture, and the club documents must have been fetched
  before it.** The export reads the capture's own roster and its own deadline, which is why
  it cannot run earlier; and it refuses a week whose club documents carry a fetch instant at
  or after the capture, because words fetched after a capture could have been chosen by
  looking at it first. So the club-news fetch belongs in the same window as everything else,
  ahead of the capture rather than after it. The fetch and the model call are one step and it
  now exists: `python -m scripts.capture_club_news --roster-snapshot <capture>` reads the
  registry, fetches the registered pages and up to ten article pages per host that they link
  to on the same host, codes them one club per call and prints the capture id that
  `--rotation` then reads. It runs **before** the capture, for the reason above, and
  its roster comes from a capture already on disk so its only network reach is the club hosts
  the registry names. A host whose terms reading is more than 90 days old is refused before
  any request and printed as refused with the reading's date; renew the reading as
  `docs/club_news_sources.md` describes rather than editing the date alone.
- **The club-news capture runs on the machine that publishes, not beside it.** `--rotation-capture`
  is resolved against the run's own `data/snapshots`, so a capture written into a different
  checkout is a capture the run cannot see. That machine is the one holding `data/entries`,
  `data/ledger`, `data/handoffs` and `data/advice_records`, which the league and publish stages
  read and which are gitignored and local; a clone without them can capture club news and export
  rotation evidence, and can do nothing else in this list.
- **Which model codes the club news is three environment variables. Before anything is
  fetched the command checks, for every adapter, that the provider is one it knows, that a
  key is set, and that a generic key is not left to a provider nobody named; it checks the
  model name only for the `gemini` adapter.** For the free adapter,
  in the shell that runs `capture_club_news`:

  ```powershell
  $env:SQUADOPT_LLM_PROVIDER = "gemini"
  $env:SQUADOPT_LLM_API_KEY = "<the key>"      # or GEMINI_API_KEY; never committed or echoed
  $env:SQUADOPT_LLM_MODEL = "gemini-3.6-flash" # optional: this is the default
  ```

  With `SQUADOPT_LLM_PROVIDER` unset and `SQUADOPT_LLM_API_KEY` set, the command now refuses
  before it fetches anything, and the refusal names both variables. The reason is that the
  generic key names no vendor: with no provider line the provider would be `anthropic`, that
  adapter reads `SQUADOPT_LLM_API_KEY` first and `ANTHROPIC_API_KEY` only when the first is
  unset, its model name is not checked against any list, and the key would leave with the
  first club's call. A key that reached the wrong vendor has left this machine, and no later
  refusal can call it back, which is why this one happens at configuration rather than at the
  first request. Set the provider line in the same shell as the key. Exporting
  `ANTHROPIC_API_KEY` alone still needs no provider line, because that name says whose key it
  is. A mistyped provider name is different again: it is refused before anything is fetched,
  and the refusal lists the registered ones.

  With `SQUADOPT_LLM_MODEL` unset the `gemini` adapter asks `gemini-3.6-flash`, the model the
  first real run (#621, 22 September) was answered by. The earlier default,
  `gemini-2.5-flash`, answers a new key with a 404: the provider now limits the 2.5 models to
  keys that used them before. A name outside the `gemini` adapter's list
  (`DOCUMENTED_MODELS` in `src/squadopt/platform/club_news_gemini.py`, read from the provider's
  models page on 25 September 2026) stops the command with `Refused:` before a single page is
  read, and the refusal lists the names it accepts. `gemini-3.8-flash` and
  `gemini-3.5-flash-lite` are on that list and are the two the provider points new projects to,
  but neither has answered this adapter yet, so a switch to one of them is something to try on
  a quiet evening rather than on the deadline day. The capture records the model and the prompt
  digest, so a week coded by one model stays distinguishable from a week coded by another.
- The Top-100 captures refuse at or after the deadline, and read the cohort's picks for
  the gameweek that just closed — so they need those picks to be public (after the
  previous deadline) and the coming deadline still open.
- The league tree takes **about thirty-six minutes** for fifteen members with `--workers 8`
  (one control plus twenty-eight rival solves per member); one process takes about
  seven times longer. The bytes do not depend on the worker count. Measured on the GW4
  capture, 2026-09-14, run `rehearsal-20260914-gw04`: the league stage ran 35 min 45 s of
  a 36 min 21 s run, with preflight, capture, settled outcomes, site and scoreboard
  together under four seconds and the handoff 28 s. Two earlier runs put the same stage at
  32 min and 49.5 min, so treat half an hour as the floor and not the estimate. This
  figure is the run **without** `--publish`. The publish stage took 13.7 s when it was
  timed on 16 September (#872, section 4); `src/squadopt/platform/weekly_publish.py`
  has changed since, and no later timing is recorded.
- With the full menu (Top 100 on; windows 1, 3 and 5 for `saf-puan`, `ortak-koru` and
  `fark-yarat`) the league stage is the run. From the rehearsal of 2026-09-26 that #872
  (section 4) reports, on the fix3 code with `--workers 12` and nothing published (#872 names
  no capture or run id): preflight to scoreboard **74.5 min**,
  the league stage 74.0 min of it, the handoff 0.4 min and everything else seconds; 1421
  advice files, `check_league_tree` passing all three checks. Every one-week (572) and
  three-week (300) window solve proved; of the 300 five-week solves 241 proved and 59
  returned FEASIBLE. GW5's full-menu league stage took 1 h 35 min with fifteen workers,
  before #655.
- **Capture to live is about 1 h 45 min** with the full menu: league stage 74 min, publish
  13.7 s (measured 16 Sep), release PR CI about 13 min, main CI about 15 min, deploy about
  1 min. A capture three hours before the deadline leaves about an hour of slack; two hours
  leaves about fifteen minutes. For GW6 (deadline 2026-10-10T10:00Z) that is 07:00Z.
- `--decide` needs the ledger to hold the previous gameweek. A week nothing was decided
  for is recorded first as a roll (`squadopt gameweek roll`, below); the pre-flight says
  so before anything is captured. `held_squad_from_ledger` (`src/squadopt/live/ledger.py`)
  refuses when the ledger holds nothing for the previous week, and the error names the
  way out. Note that `--dry-run` prints `decide run` regardless: it prints the plan and
  does not reach this check, so the refusal appears only in a real run.

## Our own squad: catching the ledger up, then deciding, then settling

Our squad is a paper ledger, not an FPL entry: it is decided into `data/ledger/` and
scored from a later capture. `held_squad_from_ledger` wants exactly the previous
gameweek's decision, so a gameweek the loop did not run for has to be recorded from a
capture taken before its deadline — `squadopt gameweek decide` with an explicit
`--snapshot-id` stamps such an entry `replay`, and the season ledger's Mode column shows
it.

**GW2 and GW3 cannot be caught up, and this is settled, not pending.** The method above
needs a capture taken before the gameweek's own deadline, and for GW1, GW2 and GW3 no
such capture exists any more: they were destroyed on 2026-09-10 along with the GW4
pre-deadline capture of the time, and they cannot be re-fetched, because a capture records
each player's status, news and chance of playing *as they stood at that moment* and the
API only ever serves the present. Earlier revisions of this section listed three capture
ids and two handoff files for these commands; none of the five is on disk, so every
command in that block would have refused. They are removed rather than corrected.

### Rolling a week that was not decided

A roll records what the game did with a week no decision was made for: the squad, the
picks and the purchase prices carried over unchanged, the bank where it was, one free
transfer accrued up to the season's cap. It names no capture, no projection and no
solver, so it claims nothing about points. The season ledger shows it as `roll` with
dashes where a decision has numbers; the scoreboard, the site and the calibration never
see it (`load_ledger` hides rolls unless asked); an outcome can never be attached to it.
It is recorded only from the entry of the week before, so the ledger stays a chain, and
like every entry it is written once.

```bash
squadopt gameweek roll --season 2026-27 --gameweek 2 --snapshot-id fpl-live-20260912T100000Z-24613792ef57 --reason "no run happened; the pre-deadline capture was destroyed on 2026-09-10"
squadopt gameweek roll --season 2026-27 --gameweek 3 --snapshot-id fpl-live-20260912T100000Z-24613792ef57 --reason "no run happened; the pre-deadline capture was destroyed on 2026-09-10"
```

The capture named supplies the season's rules (the free-transfer cap, the budget) and the
deadline being rolled through, and is refused if it was taken before that deadline: a
roll can only describe a week that is over. Rolling GW2 and GW3 from the 12 September
capture, deciding GW4 from that same capture with its handoff (recorded `replay`), then
settling GW4 from a capture in which it is finished and checked, gives the ledger
`[1, 2, 3, 4]` with GW4 its first settled row. Each command regenerates
`docs/season_ledger_2026-27.md`, which is tracked, so commit it before the next weekly
run or the pre-flight refuses the modified tree.

The check that tells you where the season actually stands, before spending anything:

```bash
python -m scripts.export_settled_outcomes --season 2026-27 --dry-run
```

As of 2026-09-14 it reports gw01, gw02 and gw03 each skipped with "no capture was taken
before its deadline", and then "No settled gameweek has both captures on disk; nothing to
accumulate." So the ledger holds GW1's decision and the settled-outcome record holds
nothing at all. **GW4 is the first gameweek that can complete the loop**, because its
pre-deadline capture `fpl-live-20260912T100000Z-24613792ef57` survives; settle it from a
capture taken once GW4 is finished and checked, and the record has its first row.

Each decide verifies the handoff against the capture and the model version against the
promoted in-season controls before anything is written; a refusal leaves the ledger as it
was. Then the weekly command with `--decide` records GW4 from the capture it takes, and
stamps it `live` only if it took that capture itself and the deadline has not passed —
a catch-up run after the deadline, from the same pre-deadline capture, is recorded
`replay`, because it was not decided before the deadline whatever it was decided from. After the gameweek, settle it from a capture in which it is finished and checked
(the Monday capture, or a fresh one):

```bash
squadopt gameweek settle --season 2026-27 --gameweek 4 --snapshot-id <fpl-live id>
python -m scripts.run_week ... --snapshot-id <that id> --skip-top100     # or --publish
```

Settling regenerates `docs/season_ledger_2026-27.md` and the scoreboard's row of ours
fills in on the next site build. Settle stays a separate command on purpose: it needs a
capture the decision run cannot have taken.

## What is on the site afterwards

For every member: their squad, the pure-points plan, and — against every other member —
the two rival strategies the catalogue computes (`ortak-koru`, `fark-yarat`), each with
captain, vice-captain, eleven, bench order, chip, the expected-points price of the
constraint net of hits, the overlap and the expected gap. The page reads the index to
know what exists; a pair no plan could satisfy is listed with its reason, not hidden.

The `/league` page carries the weekly scoreboard: per finished gameweek, our paper
ledger's figure (labelled with its mode), the league members' mean net, the Top-100 mean
with the basis it is on, the game's average and its highest score, with a cumulative row
that names the weeks each figure covers. A member's net is their gross week minus the
transfer cost, read from their own history, and the Top-100 mean is netted the same way
when the week's picks capture covers the cohort.

The league table at `/league/members` reads the same document. Beside the members it
draws, per finished gameweek, our paper squad's net, the members' mean net and the game's
average as bars on one scale ("Sistemin karnesi"), says "kayıt yok" where our row is
missing rather than drawing a zero, and keeps the whole scoreboard, with its bases, modes
and provisional weeks, behind a closed "Tüm skor tablosu" under the table.

Our own figure is not FPL's net and the card says so in both languages: it is the eleven
the decision named, scored as named. The game's automatic substitutions are not applied,
and the frozen decision names no vice-captain, so a captain who did not play is not
recovered. Neither correction is computable from what the ledger holds — the decision
records its bench as a set, not in the order autosubs walk it — and both would only add
points, so the row reads low against a real entry. In GW1 the named starters Watkins and
Mukiele both played nought minutes while the bench held two defenders who played ninety
and scored 4 and 1, so the published 26 is roughly five short of what that squad would
have scored as an FPL entry.

A gameweek that has finished but has not been data-checked in the capture is marked
provisional: bonus points land fixture by fixture, so its scores can still move.

The member page offers the one-, three- and five-week windows named by the published
index or the on-demand capabilities. An unavailable selection has a reason; a window
plan is not a fresh prediction for every later week.

## From a recorded preview to a release

Run these only inside the intended deadline window, after choosing the actual season,
gameweek, run ID and an unused publication suffix. This example is a no-write preview:

```sh
python -m squadopt.platform.weekly_operations --season 2026-27 --gameweek 6 --league 352490 --workers 6 --run-id 2026-27-gw06-decision --rotation --projection component-only --record-advice --publish --publish-suffix 1 --dry-run
```

Remove `--dry-run` only when operating the week. This records the complete published
menu and opens `feature/gw06-decision-site-1`; it does not merge or publish to production.
Once CI passes, the site pull request uploads one Pages preview, which counts toward
the ten per UTC day. A prior preview without `--publish` cannot acquire it on resume:
use a new run ID, with the
explicit capture/evidence reuse options above if appropriate. An actual resume repeats
the original options unchanged. A used suffix refuses before the expensive stages, and so
does a reused capture whose advice records name a different commit from this run's. The
captures dated 12, 15, 17 or 18 September 2026, and any whose record's `told.source` is not
`page_default`, were recorded by older code, so rebuilding one of them needs
`--no-advice-record` beside `--publish` (and no `--record-advice`) on the weekly run, or
`python -m scripts.build_league_site --no-advice-record` by hand. Either publishes without
recording and keeps the existing records. Without the switch, a record from another commit
is refused in preflight, and any other difference from the record is still refused only at
the end of the league stage.

Check the candidate with `python -m scripts.check_league_tree <preview>/data`. The site
pull request's CI also holds the shipped tree to the page's own validators
(`shippedTree.test.ts`, `planModel.chips.shipped.test.ts`, `LeagueMemberPage.shipped.test.tsx`,
`e2e/captain-line.spec.ts`). They find the trees the way the page does
(`web/src/testSupport/shippedTrees.ts`: every tree `data/leagues.json` lists, or `data/league/`
on a site without the directory) and fail, never skip, on a site that publishes neither; the
member-page guard draws one tree and fails on a site that lists more, until it draws each; to
run the first by hand, use `npx vitest run src/features/league/shippedTree.test.ts` from the
publication worktree's `web` directory.

**The first publish under the directory** (GW6 of 2026-27, the first since #959 and #960)
needs nothing typed differently: the run moves `data/league/` to `data/leagues/<league id>/`
before it reads or writes the tree, so the members' histories carry over, and writes
`data/leagues.json` last. Four things differ from the weeks before it:

- the accepted stamp `ship.sh` and `verify_live.py` take is `data/leagues.json`'s
  `generated_at_utc` (with one league, the same as that league's `members.json`), not the
  scoreboard's later stamp;
- `scripts.add_device_plan_inputs` is not run on a weekly-run tree: the builder already
  writes `device-plan.json` and each entry's inputs, with the Top 100 weights, and the script
  refuses an entry that publishes purchase prices (it exists for a tree published before the
  inputs, as fix13 was);
- the tag is the next unused one: `site-2026-27-gw06-decision` already exists, so the
  publisher's printed `-decision` tag would be refused only after `ship.sh` has waited for
  the site pull request (`git ls-remote --tags origin 'site-2026-27-gw06-*'`);
- the backend is restarted only after `verify_live.py` prints `ALL GOOD`: before the
  release, the public site still serves the legacy tree's capture and the restart refuses.

Then use the [release recipe](deployment_runbook.md#release-in-one-command)
from Git Bash:
`sh scripts/release/ship.sh --dry-run <site-PR> <unused-tag> <fresh-release-branch> <accepted-generated-at-ISO> <summary>`.
Its real invocation performs the site release and runs `verify_live.py`; the restart
helper runs that verifier again before stopping anything. To run it again by hand,
use `python scripts/release/verify_live.py <accepted-generated-at-ISO>`. The separate backend
restart command and browser check follow the order in that runbook. These remain
owner-operated actions, not part of this preview.

After publication the backend selects the one agreed capture ID carried by all human
entry documents, not simply the newest capture on disk. The chosen capture still needs
its matching handoff. Missing or unusable published capture metadata falls back to the
newest live capture and logs why. A newly captured but unpublished week must not be
mistaken for a backend release; see [backend hosting](backend_free_hosting.md).
The readiness field `league_tree_matches_capture` checks season and gameweek only;
the release restart command separately checks the public/local capture IDs.

## What stays a person's act

The outward half of publishing — merging the PR, releasing develop to main, the
`site-<season>-gw<NN>-decision` tag, the Pages dispatch — is printed, not performed.
Settling our squad (`squadopt gameweek settle`) and the replayed catch-up decisions above
are separate commands run by a person; the weekly command decides only when `--decide`
asks it to, and never settles.

**Do not re-publish a capture whose advice has already been accepted.** The advice record is
immutable within one capture and the settled publisher checks each accepted document's
canonical payload digest (`advice_sha256`) against it. It must not compare this digest to
the full envelope bytes (`published_sha256`); a changed publication clock or JSON formatting
does not change advice. A changed payload, including any added field, still refuses.
That refusal is the guard working and the answer is to stop, not to force it: the
accepted documents are the ones members read before the deadline and the record is what proves
it. Restarting the backend does not re-publish anything (`scripts/release/restart_backend.ps1`
verifies the published site, fast-forwards the checkout and restarts the launcher), so the
standing rule to restart only with a publish means restart *after* an accepted publication,
not invoke the publisher as part of restarting.
