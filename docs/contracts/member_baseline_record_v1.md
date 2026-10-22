# Member baseline record

`member_baseline_record_v1` records the server's unweighted one-week `saf-puan` answer for an FPL entry. Its key is season, gameweek, entry and capture. Neither the record nor its advice digest contains a league, so the same entry can use one record in several tracked leagues.

The record contains the capture identity and time, source `server_one_week_baseline`, the member's held squad and transfer state, projection and planner provenance, the player join map, and one scoring-complete advice document. The advice freezes the starters, ordered bench, captain, vice-captain, transfers, hit charge and expected own points. Its digest describes the computed payload with the page's league identifier removed.

This record makes no claim about a published page address or exact page bytes. It carries no `told`, `published_path` or `published_sha256`. A history writer must still prove that the relevant member page used this capture before the deadline, using the existing published-capture map. A record alone does not prove publication or adoption.

Storage retains the existing create-once and replay rules. A later capture has its own directory; a second write to the same key must reproduce the recorded decision. The manifest identifies this contract. Legacy `member_advice_record_v2` publication records remain readable with their original league identity and are never rewritten as baselines.

The weekly run computes one CP-SAT baseline per distinct tracked entry before rendering any league. Full menus reuse that control; device menus need no member solver during rendering. The writer lands a record in `data/member_baselines/<season>/gw<NN>/entry-<id>/<capture>/` after that member's page is emitted. A second league reuses the immutable record. An entry whose picks are missing, or whose solve or record fails, is named in the run receipt with the reason and gets no record; its full-menu page solves it again and refuses it there when that fails too, and the other entries are unaffected.

The batch enables CP-SAT's complete linear relaxation for these baselines, and a full-menu page that solves a member the batch has no control for uses the same level (`TRACKED_MEMBER_LINEARIZATION_LEVEL`), so the plan does not depend on whether the run records. The model and existing deterministic and wall ceilings are unchanged. This lets the second-league five-free-transfer case prove the same optimum as the device within the existing budget. A record still retains the actual solver status and gap; it never labels an unfinished search as optimal.

History reads both this store and the retained `data/advice_records` archive. For the same entry and capture, the original league keeps its legacy publication record and digest. Another league reads the independent baseline. Neither store may silently hide a corrupt record; all previously published weeks must remain present when a history is replaced.
