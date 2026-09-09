# Enterprise software transition

## Adım adım ilerleme

- [x] Tek geçiş branch'ini oluştur; güncel develop ve aktif işleri doğrula.
- [ ] **Şimdi:** kuyruk kurtarma, iş sahipliği ve bozuk kayıt izolasyonu (R02).
- [ ] API/web veri doğrulaması, istek iptali ve süre sınırları (R03).
- [ ] Yedekleme, geri yükleme ve haftalık koşu takibi (R04/R05).
- [ ] Ortak sözleşmeler ve katman bağımlılıkları (R11).
- [ ] Solver, yayın üretimi ve üye sayfası sorumlulukları (R12).
- [ ] Arşiv düzeltmeleri ve İbo'nun teslimatını uzlaştırma (R01/R07).
- [ ] Bilimsel kontrol hataları, CI ve tarayıcı testleri (R08/R13).
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
| R01 | Reconcile archived #440/#442 and prerequisite fixes against this baseline; preserve Ibo's active LLM work | Pending |
| R02 | Recover interrupted queue writes; fence stale attempts; isolate corrupt records; exercise process crashes and concurrent recovery | In progress |
| R03 | Shared API cache validation and request capabilities; strict nested web payloads; request cancellation and deadlines | Pending |
| R04 | Capture-addressed projection retention; verifiable backup and empty-target restore; inventory existing external backup | Pending |
| R05 | Durable weekly stage/results, interrupted-run visibility and safe resume; installed application seams | Pending |
| R06 | Browser/API/worker/cache acceptance and independent process observability; real host/storage acceptance recorded separately | Pending |
| R07 | Integrate delivered, replayable club evidence without duplicating Ibo's adapter or activating an unmeasured model | Pending contributor integration |
| R08 | Artifact-specific evidence declarations and matched strategy comparison populations, with unchanged historical evidence | Pending |
| R09 | Prospective component versus component+Top100 decisions and settled comparison | Requires future captures/outcomes |
| R10 | Preserve Phase D/E admission gates; never infer calibration or promotion from source integration | Existing scientific gates retained |
| R11 | Extract shared vocabulary and evaluation policy/statistics; remove all five import exemptions; compatibility re-exports | Pending |
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
