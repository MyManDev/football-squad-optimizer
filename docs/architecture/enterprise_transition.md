# Enterprise software transition

## Adım adım ilerleme

- [x] Tek geçiş branch'ini oluştur; güncel develop ve aktif işleri doğrula.
- [x] Kuyruk kurtarma, iş sahipliği ve bozuk kayıt izolasyonu (R02); odaklı testler geçti.
- [x] API/web veri doğrulaması, istek iptali ve süre sınırları (R03); tarayıcı kabulü geçti.
- [x] Yedekleme ve geri yükleme araçları (R04); 59 test ve sentetik restore geçti.
- [x] Haftalık koşu kaydı ve güvenli devam (R05); 239 test ve kurulu wheel kabulü geçti.
- [x] Ortak sözleşmeler ve katman bağımlılıkları (R11); 5 istisna kaldırıldı, 163 test geçti.
- [x] Ortak solver desteği (R12); 209 test ve model/sonuç eşitliği geçti.
- [x] Üye sayfasını sorgu, seçim ve görünüm olarak ayır (R12); 392 ilgili web testi geçti.
- [x] Yayın servislerini kurulu pakete taşı (R12); 48 test, gerçek iki işçi ve temiz wheel kabulü geçti.
- [x] Arşiv düzeltmelerini uzlaştır (R01); 71 Python ve 19 web testi geçti.
- [ ] İbo'nun teslimatını bağla (R07); gerekli üretici teslimatı bekleniyor.
- [x] Bilimsel kontrol hatalarını düzelt (R08: 54 test); eski kanıt dosyaları korundu.
- [x] CI/tarayıcı kapsamı eklendi (R13); web derlemesi, boyut/dağıtım ve 70 tarayıcı senaryosu kontrol edildi.
- [x] Ayrı işçi metrikleri ve depolama kilidi kontrolü (45 test); süreçler ayrı tutuldu.
- [x] Yük testinde iki eşzamanlılık hatası doğrulandı ve düzeltildi; 70 odaklı test geçti.
- [x] Kilit öncesi saat okuma hatası düzeltildi (88 test); son 18 yük senaryosu ve gerçek CPU/bellek ölçümü geçti.
- [ ] **Şimdi:** Son Python testleri, Linux container/Compose ve güncel tarayıcı/backend kabulü.
- [ ] Hedef sunucu, bağımsız dış yedek ve canlı scheduler kabulü; mevcut altyapı henüz doğrulanmadı.
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
| R05 | Durable weekly stage/results, interrupted-run visibility and safe resume; installed application seams | Implemented; 239 tests, real process crash/read locking, Git-backed resume and isolated wheel run/resume/status passed; no live scheduler installed |
| R06 | Browser/API/worker/cache acceptance and independent process observability; real host/storage acceptance recorded separately | Browser acceptance passed; independent worker metrics and mount-lock probe implemented, 45 focused tests passed; Compose acceptance pending |
| R07 | Integrate delivered, replayable club evidence without duplicating Ibo's adapter or activating an unmeasured model | Pending contributor integration |
| R08 | Artifact-specific evidence declarations and matched strategy comparison populations, with unchanged historical evidence | Implemented; 54 focused tests passed; historical evidence unchanged |
| R09 | Prospective component versus component+Top100 decisions and settled comparison | Requires future captures/outcomes |
| R10 | Preserve Phase D/E admission gates; never infer calibration or promotion from source integration | Existing scientific gates retained |
| R11 | Extract shared vocabulary and evaluation policy/statistics; remove all five import exemptions; compatibility re-exports | Implemented; 163 tests passed, zero import exemptions; seeded outputs and fingerprints unchanged |
| R12 | Extract actually shared solver support and focused publication/member-page responsibilities | Solver: 209 tests and unchanged model/results; member page: 392 tests; publication: 48 tests and isolated wheel/two-worker acceptance passed |
| R13 | Browser/backend CI smoke, loaded member accessibility coverage, failure traces and current documentation entry points | Implemented; browser/backend passed; production build/assets/size/format passed; 68/70 browser cases initially passed, two stale wrong-path expectations corrected and all 13 affected cases passed |
| R14 | Reproducible cache/dedup/distinct-job load scenarios; measured latency/resource report; deployed replica decision separately | Implemented; 18 final scenarios passed (6 configurations, 143.67 s); exact per-case source inventories match; CPU/RSS cover owned process trees. Earlier failures and fixes retained in advice_capacity.md/JSON; production replica choice remains host-specific |
| R15 | Incremental prose/script organization with compatible paths; retain immutable artifacts and worktree evidence | README now covers runtime/setup; product roadmap moved to docs/product; current system map and operations indexes updated, local links checked |

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
