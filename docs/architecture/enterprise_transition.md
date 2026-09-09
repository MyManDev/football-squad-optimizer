# Enterprise software transition

## Adım adım ilerleme

- [x] Tek geçiş branch'ini oluştur; güncel develop ve aktif işleri doğrula.
- [x] Kuyruk kurtarma, iş sahipliği ve bozuk kayıt izolasyonu (R02); odaklı testler geçti.
- [x] API/web veri doğrulaması, istek iptali ve süre sınırları (R03); tarayıcı kabulü geçti.
- [ ] **Şimdi:** Yedekleme ve geri yükleme hazır (R04); haftalık koşu takibi sürüyor (R05).
- [x] Ortak sözleşmeler ve katman bağımlılıkları (R11); 5 istisna kaldırıldı, 163 test geçti.
- [ ] Solver, yayın üretimi ve üye sayfası sorumlulukları (R12).
- [ ] Arşiv düzeltmeleri ve İbo'nun teslimatını uzlaştırma (R01/R07).
- [ ] Bilimsel kontrol hataları tamam (R08: 54 test); CI ve tarayıcı kabulü sürüyor (R13).
- [ ] Backend kabulü, gözlemlenebilirlik ve yük ölçümü (R06/R14).
- [ ] Son klasör düzeni, tam doğrulama ve commit'ler (R15).

Tamamlanan kod ile gerçek ortamda kabul ayrı kaydedilir. R09 gerçek gelecek hafta
verisi gerektirir; R10'un bilimsel kapıları kod değişikliğiyle geçmiş sayılmaz.

## Implementation record

Implementation branch: `codex/enterprise-software-transition`.
Baseline: `0d9bd4622d086def677d038060f2d555acf4b36d` (published-main runtime plus documentation).

The 9 September repository review is the input, not a record of completed implementation.
Retain the modular monolith, deterministic domain calculations, versioned public contracts,
independent API/worker processes and immutable scientific evidence. Improvements are recorded
as topical commits on this one branch. Source implementation, deployment acceptance and
prospective scientific evidence have separate completion criteria.

| Work | Scope and acceptance | State |
| --- | --- | --- |
| R01 | Reconcile archived #440/#442 and prerequisite fixes against this baseline; preserve Ibo's active LLM work | Implemented; 71 Python and 19 strategy-control tests passed; active Ibo dependencies documented |
| R02 | Recover interrupted queue writes; fence stale attempts; isolate corrupt records; exercise process crashes and concurrent recovery | Implemented; 66 focused tests passed on Windows; full/CI acceptance pending |
| R03 | Shared API cache validation and request capabilities; strict nested web payloads; request cancellation and deadlines | Implemented; 59 Python and 143 web focused tests passed; offline Python-to-TypeScript publication and browser/API/worker/cache acceptance passed |
| R04 | Capture-addressed projection retention; verifiable backup and empty-target restore; inventory existing external backup | Implemented; 59 focused tests passed including synthetic domain restore; real independent destination remains unverified |
| R05 | Durable weekly stage/results, interrupted-run visibility and safe resume; installed application seams | In progress |
| R06 | Browser/API/worker/cache acceptance and independent process observability; real host/storage acceptance recorded separately | Pending |
| R07 | Integrate delivered, replayable club evidence without duplicating Ibo's adapter or activating an unmeasured model | Pending contributor integration |
| R08 | Artifact-specific evidence declarations and matched strategy comparison populations, with unchanged historical evidence | Implemented; 54 focused tests passed; historical evidence unchanged |
| R09 | Prospective component versus component+Top100 decisions and settled comparison | Requires future captures/outcomes |
| R10 | Preserve Phase D/E admission gates; never infer calibration or promotion from source integration | Existing scientific gates retained |
| R11 | Extract shared vocabulary and evaluation policy/statistics; remove all five import exemptions; compatibility re-exports | Implemented; 163 tests passed, zero import exemptions; seeded outputs and fingerprints unchanged |
| R12 | Extract actually shared solver support and focused publication/member-page responsibilities | Pending |
| R13 | Browser/backend CI smoke, loaded member accessibility coverage, failure traces and current documentation entry points | Pending |
| R14 | Reproducible cache/dedup/distinct-job load scenarios; measured latency/resource report; deployed replica decision separately | Pending R02/R06 |
| R15 | Incremental prose/script organization with compatible paths; retain immutable artifacts and worktree evidence | Documentation indexes present; further organization pending |

## Evidence and operational decisions

The earlier review used develop `a85c7bdd`; its additional source is now retained on
`archive/pre-main-alignment-20260909`, not silently part of this baseline. #440/#442 were
closed during owner-authorized branch consolidation, with all local and remote tips archived.
Inspect exact archived patches before restoring behavior. Ibo's contributor branches remain
independent; integration must account for unpublished dependencies.

Existing backup, scheduler, hosting and notification configuration will be inventoried before
selecting new infrastructure. Unknown retention, recovery objectives, costs and release timing
are not assumed to be established policy. Operational tools must allow explicit configuration
and produce durable acceptance evidence. No historical measurement is regenerated as part of
a structural refactor, and no private operational data is added to Git.
