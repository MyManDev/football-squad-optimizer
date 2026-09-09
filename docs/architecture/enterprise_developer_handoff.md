# Enterprise geçişi: geliştirici devir notu

Hazırlanma tarihi: **10 Eylül 2026**. Bu belge, ertesi gün çalışmaya başlayacak
geliştiricinin mevcut sistemi koruyarak devam etmesi içindir. Yeni bir mimari veya
araştırma programı önermiyor. Kodun uygulanmış olması, bir testin belirli ortamda
geçmesi ve canlı sistemin kabul edilmesi ayrı durumlardır.

Çalışmanın dalı `codex/enterprise-software-transition`; entegrasyon kaydı
[geçiş belgesinde](enterprise_transition.md), testlerin kapsamı ve bilinen başarısızlıklar
[kabul kaydında](enterprise_acceptance.md) bulunur. Başlangıç revizyonları ve arşiv
karşılaştırmaları tarihsel bağlamdır; onları yarınki çalışma HEAD'i gibi kullanma.
Önce yerel durumu, PR'ın güncel revizyonunu ve İbo'nun devam eden işini kontrol et.

## Son CI ve E2E sonucu: devir kapanışında doldurulacak

**Bu bölüm hazırlanırken güncel uzak CI devam ediyordu. Aşağıdaki boş alanlar başarı
anlamına gelmez.** Sonuçlar yalnız ilgili commit, çalıştırma ve kanıtla doldurulmalı;
önceki yerel veya uzak koşunun başarılı kısımları buraya taşınmamalı.

| Kapanış alanı | Güncel kayıt |
| --- | --- |
| İncelenen son commit / branch | **BEKLİYOR — tam SHA ve dal** |
| PR ve tam CI çalıştırma bağlantısı | **BEKLİYOR — mevcut PR'ın son HEAD'iyle eşleşmeli** |
| CI işleri ve nihai sonuçları | **BEKLİYOR — Python sürümleri, web ve container ayrı yazılmalı** |
| Son E2E ortamı ve kullanılan veriler | **BEKLİYOR — yerel/container/canlı; sentetik/gerçek ayrımı** |
| Son E2E kullanıcı adımları ve sonuçları | **BEKLİYOR — TR/EN, üye/rakip seçimi, öneri, iptal/hata/cache akışı** |
| E2E kanıtı ve kaynak/image kimliği | **BEKLİYOR — rapor, log, gerekli ekran/istek kaydı, commit/digest** |
| Canlı yayın yapıldı mı; hangi adres ve sürüm doğrulandı? | **BEKLİYOR — yerel E2E'den canlı yayın sonucu çıkarılmamalı** |
| Kalan başarısızlıklar ve kabul edilmeyen ortamlar | **BEKLİYOR — boş bırakılarak gizlenmemeli** |
| Kontrol kapanış zamanı (UTC) | **BEKLİYOR** |

[Kabul kaydındaki](enterprise_acceptance.md) tarihsel tam Python koşusu 4.755 geçti,
19 hata, 13 atlama sonucuyla bitmiştir; “tam paket yeşil” değildir. On dört hata için
uyumluluk/beklenti/bağımlılık düzeltmeleri ve odaklı kontroller kaydedilmiştir. İki uzun
yol hatası değişmeyen kaynakla kısa kökte doğrulanmış, üç Windows izin hatası ise
workaround veya yeniden denemeyle örtülmeden açıkça bırakılmıştır. Uzak CI'da görülen
scratch üst dizini eksikliği de ayrı kayıttır: workflow, açık pytest basetemp'inden önce
`.pt` üst dizinini artık oluşturur. Son CI bunlardan sonra gelen kendi
revizyonunu doğrulamalıdır.

### Son yerel Chromium kabulü

`tests/integration/test_advice_browser.py` ile onun çalıştırdığı
`web/e2e/advice-backend.spec.ts`, gerçek Chromium → HTTP API → bağımsız worker → disk
cache zincirini kullanır. Girdiler sentetiktir; public üye/index dosyalarını gerçek Python
yayıncısı üretir. İstekler tarayıcıda mock/intercept edilmez. Bu koşu üretim sitesinin
veya gerçek üye verilerinin kabulü değildir.

Son senaryo şu adımları kapsar: `/` girişinde `123` ligini **fetch yapmadan reddetme** →
`352490` ile üyeleri açma → “Bu benim” seçimi ve `squadopt.viewer` localStorage kaydı →
seçili üyenin eldeki kadrosu → eksik statik öneriden “Hesapla” → POST **202** ve job ID →
worker `completed` → doğru capture/üye/hafta kimliğiyle UI sonucu → sayfa yenileme →
aynı cevabın cache'den POST **200** ile gelmesi. Worker ilk işten sonra kapanır; son
adım cache cevabının yeni hesap gerektirmediğini doğrular. Sonuç görünümüne erişilebilirlik
kontrolü de uygulanır. Bu koşunun dil kapsamı TR'dir; EN ve rakip değiştirme kapsamı
kapanış matrisinde ayrıca belirtilmelidir.

İlk genişletilmiş koşu, seçili üyenin “Üyeyi değiştir” bağlantısında **4,33:1** kontrast
oranını yakaladı. `LeagueMemberPage.module.css` içindeki `.notice a` rengi mevcut
`--color-text` token'ına alındı. Bu değişiklikten sonraki yerel koşu **1 passed in 22.54s**
sonucuyla bitti. Kayıtlar `.pt/enterprise/e2e-final-02.log` (başarısız kontrast kontrolü)
ve `.pt/enterprise/e2e-final-03.log` (son başarılı koşu) altındadır. Kod revizyonu ve son
uzak CI sonucu üstteki kapanış tablosuna ayrıca bağlanmalıdır. Bu düzeltme R07 veya
model davranışını değiştirmez.

## Sistemi nereden okumalı?

İlk okuma sırası: [sistem haritası](system_map.md), [bağımlılık kuralları](dependency_rules.md),
[geçiş kaydı](enterprise_transition.md), [kabul kaydı](enterprise_acceptance.md),
[işletme envanteri](operations_inventory.md), [arşiv uzlaştırması](archive_integration.md).
`docs/product/roadmap.md` ürün/araştırma yönünü taşır; bu belgedeki işletme kabulüyle
bilimsel terfi koşullarını birbirine karıştırma.

Sistem **modüler monolittir**: bir kurulu Python paketi, ayrı API ve worker süreçleri,
bir React web uygulaması. Kuyruk/cache aynı kalıcı depoyu paylaşır; bu, API ve worker'ın
aynı süreçte olması gerektiği anlamına gelmez.

| Sınır | Sorumluluk ve korunacak kural |
| --- | --- |
| `contracts` | Pozisyonlar, gerekli oyuncu kolonları ve kararlı sıralama gibi ortak sözlük. Motor katmanlarını import etmez. Hesap veya taşıma davranışı ekleme. |
| `data → features → prediction` | Yakalanmış veriler, özellikler, projeksiyonlar. Kaynak zamanını ve veri kimliğini korur. |
| `optimization`, `planning` | Karar ve plan hesabı. Ortak karar kısıtları/seçim/doğrulama `optimization.decisions` modülündedir. |
| `evaluation` ve araştırma katmanları | Ortak değerlendirme, terfi politikası ve istatistikler; diğer araştırma paketleri ilan edilmiş katman sırasına uyar. |
| `live` | Kalıcı domain kayıtları, sezon kararları ve gerçekleşmiş sonuçların domain hesabı. |
| `application` | Tipli iş akışları, öneri yetenekleri, yayın ve kanıt üretimi. `platform` veya `scripts` import etmez. |
| `platform` | Dosya sistemi, ağ yakalama, kuyruk, süreç havuzu, metrikler, yedekleme, CLI/Git adaptörleri. Domain karar kurallarını burada çoğaltma. |
| `api` | HTTP çevirisi; motora doğrudan ulaşmaz, application/platform sınırını kullanır. |
| `web` | Yayımlanmış verinin doğrulanmış okunması, seçim ve istek yaşam döngüsü, gösterim. Eksik değerden sonuç uydurmaz. |

Eski beş import istisnası kaldırıldı. `lint-imports` artık sıfır istisna ile katmanları
ve API'nin doğrudan motor import yasağını denetler. Yeni istisna eklemek veya kaynak
modülünü `scripts` üzerinden geri bağlamak çözüm değildir.

## Taşınan kodun sahibi ve uyumluluk haritası

Yeni davranışı sağdaki sahibinde değiştir; soldaki girişleri aynı PR'da gelişigüzel
kaldırma. Eski script'ler yalnız test kolaylığı değildir: bazıları gerçek araştırma
çağrıları tarafından import edilir.

| Önceki giriş / sorumluluk | Güncel sahip | Uyumlulukta dikkat |
| --- | --- | --- |
| `optimization.config`, `validation`, `coefficients` içindeki ortak oyuncu sözlüğü | `contracts.players` | Eski importlar aynı nesneleri dışa aktarır; kanonik oyuncu sırası/fingerprint değişmemeli. |
| Deneylerin ortak terfi politikası ve bootstrap hesabı | `evaluation.promotion`, `evaluation.statistics` | `ExperimentError` ve `ExperimentConfigurationError` isimleri/kalıtımı eski çağrıları korur. Deney yürütme davranışı taşınmış sayılmaz. |
| Tekrarlanan solver karar desteği | `optimization.decisions` | Kısıtlar, seçim ve doğrulama paylaşılır; objective, bağ kırma sırası, solver ayarı ve sonuç fingerprint'i refaktör gerekçesiyle değiştirilmez. |
| `scripts.build_projection_handoff` | `application.projection_handoff` + `platform.projection_retention` | CLI bayrakları ve `build` girişi korunur. Eski script API'si yazarken retention kullanır. Dört sabit ile `_component_table` gerçek Phase E çağrısına açıktır. |
| `scripts.export_player_evidence`, `export_rotation_evidence`, `export_settled_outcomes` | `application.player_evidence`, `rotation_export`, `settled_outcomes` | Domain üreticisi kurulu pakettedir; script argüman/komut uyumluluğunu sürdürür. Kanıt şeması veya eski kayıt baytları kendiliğinden değişmez. |
| `scripts.capture_top100_cohort`, `capture_elite_picks` | `platform.cohort_capture`, `platform.elite_capture` | Ağ işi platformda, eski komut girişleri korunur. |
| `scripts.run_week`, `publish_gameweek_site` | `application.weekly_plan`; `platform.weekly_operations`, `weekly_journal`, `weekly_publish` | Haftalık planın domain kontrolleri application'da; yürütme/kayıt/Git platformdadır. Varsayılan önizleme artık özel run klasörüdür. |
| `scripts.build_league_site`, `build_scoreboard`, `build_site` | `application.league_publication`, `scoreboard`, `site_publication` | Tipli request/result ve `output_paths`; eski CLI bayrakları devam eder. Yayın geç hata verirse kısmi dosya yazılmış olabilir. |
| Capture picks sağlayıcısı | `application.capture_entries` | `platform.capture_context` aynı nesneleri dışa aktarır. Havuz oluşturma `platform.publication_workers` içindedir. |
| Kuyruğun tek büyük modülü | `platform.queue_contracts`, `file_advice_queue`, `advice_queue` | Arayüz, depolama ve hesap çağırma ayrıdır; eski `advice_queue` importları uyumludur. |
| Büyük üye sayfası | `LeagueMemberPage`, `useLeagueMemberData`, `LeagueMemberView`, `useMemberAdviceView`, `MemberAdviceCard` | Route/sorgu/seçim/gösterim ayrıdır; eski view/type importları korunur. Doğrulama `publicationShape`, ortak hata sınıfları `dataErrors` içindedir. |

Son tam koşunun bulduğu somut ders: `scripts/_phase_e_live.py`, handoff script'inden
`COMPONENT_MODEL_VERSION`, `COMPONENT_FEATURE_CONTRACT_VERSION`,
`COMPONENT_HISTORY_WINDOW` ve `_component_table` kullanır; test fixture'ı ayrıca
`CONTROL_MODEL_NAME` kullanır. Eksik sabit re-export'ları düzeltildi ve gerçek çağrı
testleri geçti. Gelecek taşımada yalnız yeni sahibi test etmek yerine eski girişin
çağrılarını da ara. Ayrıntılar: [yayın servisleri](publication_services.md),
[üye sayfası sınırları](member_page_boundaries.md).

## API ve kuyruk: bozulmaması gereken koşullar

Üye seçimi → yayımlanmış index → izin verilen öneri adresi/hesap isteği → API →
doğrulanmış cache veya kuyruk → bağımsız worker → application hesabı → cache şeklinde
ilerler. Bir adresin biçimsel olarak üretilebilmesi, o seçimin yayımlanmış/izinli
olduğunu kanıtlamaz. Üretici ve API `application.advice_capabilities` kuralını paylaşır:
saf puan 1/3/5 hafta; mevcut rakip stratejileri farklı bir lig üyesiyle 1 hafta.
Bu yetenek, her capture'da her takvimin çözülebileceği garantisi değildir.

- `job_id`, `request_fingerprint`, `cache_key` farklı kimliklerdir. İşin `attempt`
  değeri ayrıca yürütme sahipliğini belirler. Bunlardan biri diğerinin yerine geçmez.
- Kalıcı `.queue.lock` dosyası kısa metadata işlemlerini korur; çözüm kilit dışında
  çalışır. Kilit dosyasını silmek veya değiştirmek iki ayrı kilit kimliği yaratabilir.
- Claim ve recovery saati kilit alınıp ilgili iş seçildikten sonra okunur. Worker aynı
  enjekte edilmiş saati taşır; sabit `at_utc` tekrar/test uyumluluğu içindir. Terminal
  saat hesap bittikten sonra alınır. Geriye giden gerçek saat reddedilir; ileriye
  yuvarlayarak veya başlangıç anını tamamlanma anı yazarak saklanmaz.
- İşin yaşam döngüsü zamanı ile cevabın `generated_at_utc` alanı farklıdır. Tekrar
  hesaplanabilir cache cevabı capture zamanını taşır. Bu alanı worker'ın bitiş saatiyle
  değiştirmek deterministik cache baytlarını bozar.
- İlk cache miss'ten sonra başka worker işi tamamlamış olabilir. Son doğrulanmış cache
  okuması ve açık iş ayırma `submit_unless_cached` içinde, completion ile aynı kilit
  altındadır. Bu kontrolü API tarafındaki ilk okumaya indirgeme.
- Eski attempt heartbeat yenileyemez, yeni claim'i kaldıramaz, terminal sonuç veya cache
  yayımlayamaz. Sahiplik kontrolü cache yazısından önce de yapılır. Lease kaybı başka
  attempt'in başarısını hata durumuna çevirmek için kullanılmaz.
- Job polling okuması da metadata kilidi içindedir. Windows'ta açık okuma handle'ı ile
  `os.replace` yarışına retry/sleep eklenmedi; okuma ve yazı doğru sınırda sıralandı.
- Kesilen intent/claim/terminal-cleanup adımları kurtarılır. Bozuk kayıt `integrity/`
  altında bayt/hash kanıtıyla korunur; aynı anahtarın rezervasyonu bloke kalır, ilgisiz
  işler devam eder. Bozuk kaydı “iş yok” saymak duplicate üretir.
- Her iki cache okuma yolu şema/kimlik/iç içe veri doğrulaması yapar; non-finite değerler
  reddedilir. Readiness bir bütünlük kontrolüdür, yeni bir veri yaşı politikası değildir.

Web'de iptal, taşıma isteğini keser; sunucuda işi iptal ettiğini iddia etmez. Zaman aşımı,
eski seçimden dönen cevap ve bozuk/mismatched veri yeni görünümü ezemez. İptal edilen
istekten otomatik statik fallback başlatılmaz. Eksik değer, geçerli sıfır ve bağlantı
hatası ayrı kalır. [Taşıma sınırları](advice_boundaries.md) ve
[kuyruk kurtarma](queue_recovery.md) kaynak ayrıntılarını verir.

API istek/cache sayaçları API'de, solve/job sayaçları worker'ın ayrı metrik listener'ında
kalır. Yerel kapasite ölçümü bir üretim replika sayısı seçmez; gerçek process-tree
CPU/RSS ölçümü, sentetik roster ve burst sınırları [kapasite kaydında](advice_capacity.md)
belirtilmiştir. Yeni worker sayısını yalnız bu tablodan türetme.

## Haftalık iş, yayın ve kalıcı kayıtlar

[Haftalık işletme belgesi](weekly_operations.md) yürütmenin sahibidir. Ana sıra:
preflight → isteğe bağlı Top100 capture/evidence → seçilen capture → geçmiş settled
outcomes → isteğe bağlı rotation → handoff → isteğe bağlı kendi kararımız → lig/site/
scoreboard önizlemesi → yalnız istenirse yayın PR'ı.

`data/runtime/weekly/<run-id>/run.json` sabit istek, kurulu kod kimliği, aşama denemeleri,
girdi/çıktı hashleri ve sonuçları taşır. `exit 0` tek başına yeterli değildir. Resume aynı
istek/kod/girdileri ister; biten aşamanın çıktısını doğrular ve yeniden üretmez. Capture
üyeliği veya değişebilir handoff alias'ı kayarsa devam reddedilir. Özel run/workspace
sahiplik kilitlerinden ayrı kısa journal kilidi, status okumalarının Windows yazısını
engellemesini önler.

Varsayılan çıktı `data/runtime/weekly/<run-id>/preview` altındadır. `--out` korunur fakat
tracked `web/public` seçilirse oluşturulan değişiklikler temiz kaynak önkoşulunu bozabilir.
Kaynak filtresini gevşeterek bunu örtme; varsayılan özel çıktı bu sorunu önler.

Deadline hedefi mevcut runbook'taki **deadline'dan 2–3 saat önce** kuralıdır. Sabit bir
haftalık gün/saat benimsenmiş değildir. `--expected-at` verilmeden `missed` bilinmez;
gecikmiş/eksik başarıya ilişkin çıkış durumu scheduler'ın açık beklentisine bağlıdır.
Settled-outcome export yalnız seçilen capture anına kadar görülen, daha önceki bitmiş
ve checked haftaları kullanır. Eksik pre-deadline/settled eşleşmesinde sıfır sonuç yazmaz.
Bu adım güncel ledger haftasını settle etmez; o post-gameweek komutu ayrıdır.

`--handoff` açık bir hazır projeksiyon kullanımıdır: capture/season/GW/fingerprint
doğrulanır, `--skip-top100` gerekir; receipt yeni evidence uygulanmadığını söyler.
Rotation hâlen opt-in fixture kaynağı kullanır. Önizleme advice record yazmaz. Yayın
rebuild'i gerçekten ürettiği veriye ait özel kaydı yazar. Aynı capture'ın yalnız yayın
saati değişmiş tekrarı ilk immutable kaydı korur; payload veya maddi provenance farkı
çatışır. İlk kaydın `published_sha256` alanı ilk yayın baytlarını anlatır.

`--publish` başarısı açık PR/commit veya değişiklik olmadığı receipt'idir; canlı site
başarısı değildir. Merge, main CI, tag, deploy ve canonical doğrulama ayrıca gerekir.
Push/PR sırasında kesilirse sonuç `uncertain` kalır; kör resume ile dış yan etki
tekrarlanmaz. Yerel yayın dalı, uzak PR/commit ve advice record uzlaştırılmalıdır.

## Yedek ve gerçek ortamda hâlâ eksik olanlar

[Yedekleme aracı](backup_recovery.md) seçilmiş kökleri bütünüyle kopyalar, manifest/hash
doğrular ve yalnız boş/olmayan hedefe restore eder. Snapshot, ledger, registry, advice
record, handoff'un tamamı ve gerekli evidence/archive/runtime köklerini işletmeci açıkça
seçer. Runtime içindeki mutlak yollar restore'da kendiliğinden yeni konuma çevrilmez.

Handoff'un eski/yeni baytları `handoffs/by-capture/<capture>/<content-sha>.json` altında
korunur; `<season>-gwNN.json` uyumlu alias olarak kalır. Content hash ile projection
fingerprint aynı şey değildir. Aynı hafta önceki capture'a dönmek, onun handoff'unu da
eşleştirmeyi gerektirir; yalnız son snapshot'ı saklamak alias'ı düzeltmez.

`--writers-stopped` süreçleri durdurmaz, işletmecinin önkoşulunu kaydeder. Kaynaklar ve
hedefler ayrı olmalı; bağımsız korunan receipt'teki manifest hash'i kullanılmalıdır.
Araç prune yapmaz, kaynak ACL/ownership bilgisini taşımaz veya şifreleme sağlamaz.
Restore sonrasında domain okuyucuları ve capture/fingerprint ilişkileri de doğrulanır.
Git, immutable dosya, aynı diskte kopya ve yedi günlük CI artifact saklama süresi tek
başına özel veri yedeği değildir.

9 Eylül [envanterinde](operations_inventory.md) doğrulanan hosting statik Cloudflare
yayınıydı; canlı backend/shared mount, bağımsız dış yedek, çalışan haftalık scheduler ve
bildirim hedefi doğrulanmadı. “Bulunamadı” başka makinede kesinlikle yok demek değildir.
Compose API/worker ayrımını, read-only girdileri ve ortak yazılabilir store'u hazırlar;
gerçek host/UID 10001 yazma hakkı, mount kilidi/restart, ingress ve rollback kabulü gerekir.
Eski ve fenced kuyruk writer'larını aynı store'da birlikte çalıştırma.

Windows'ta kısa workspace/test/backup kökleri kullan. Bu hostta 260 karakter eşiğiyle
ilgili kanıt var; global long-path ayarı veya extended-path desteği açılmış değildir.
İzin hatası görünce veri klasörü silmek, ACL değiştirmek ya da yeşil olana kadar denemek
kabul yöntemi değildir. Hatanın kaynak mı ortam mı olduğu ayrı kanıtla yazılmalıdır.

## R07: İbo'nun teslimatı ve araştırma devamı

İbo'nun çalışması bağımsızdır. [Arşiv uzlaştırma belgesindeki](archive_integration.md)
`feat/club-news-model-call` ve `feat/per-club-model-provenance` uçları **9 Eylül kontrolünün**
kayıtlarıdır; entegrasyona başlamadan güncel teslimatı sahibiyle doğrula. Bu geçişe SDK,
kodlama adaptörü veya per-club model provenance kendiliğinden alınmış değildir.

En küçük bütün teslimat, mevcut sözleşmeyle şu zinciri birlikte göstermelidir:

1. Kulüp ile kaynak belgenin gerçek ilişkisi ve kalıcı ham belge baytları.
2. Dondurulmuş kodlama istemi/cevap şeması; istenen ve gerçekten hizmet veren model kimliği;
   kulüp ile ilgili model cevabının ilişkisi.
3. Ham cevabın durable capture'ı ve ağ/model çağrısı olmadan o capture'dan tekrar okuma.
4. Quote → benzersiz tam UTF-8 byte span dönüşümü; bulunamayan/çok anlamlı alıntının reddi.
5. Aynı teslimatın offline testleri ve `application.rotation_export` sınırına uyarlanması.

Bilinen locator hatası somuttur: `b'aaa'.count(b'aa') == 1` olmasına rağmen 0 ve 1'de
iki örtüşen başlangıç vardır. Benzersiz eşleşme iddiası bunu reddetmelidir. Mevcut offset
parser'ı başka bir sözleşmedir; sadece helper'ı kopyalayıp ikinci, kullanılmayan şema
yaratma. Mevcut in-memory fixture replay testi, kalıcı gerçek capture kanıtı değildir.
Yeni alan adlarını/şemayı burada icat etmek yerine teslimat sahibiyle frozen contract'ı
uzlaştır. Ağ/model aktivasyonu ve maliyeti ayrı açık karardır.

R08'in daha sıkı artifact beyanı ve eşleşen karşılaştırma popülasyonları, eski bilimsel
kanıtları yeniden yazmaz. R09 component ile component+Top100 karşılaştırması gelecekteki
deadline öncesi karar capture'ları ve sonrasında gerçekten settled sonuçları gerektirir.
R10/Phase D–E admission, kalibrasyon ve promotion kapıları korunur. Yeni veri/ölçüm kendi
kimliği ve değerlendirme koşullarıyla kaydedilir; başarılı CI veya entegre edilmiş kaynak
kodundan model üstünlüğü/kalibrasyon sonucu çıkarılmaz.

## Başlangıç komutları ve dar doğrulama

İlk komutlar okuma/kontrol içindir; aktif dalı veya private data'yı değiştirmez:

```powershell
git status --short
git branch --show-current
git log -5 --oneline
.venv/Scripts/python -m squadopt.platform.cli --help
.venv/Scripts/python -m squadopt.platform.weekly_operations --help
.venv/Scripts/python -m squadopt.platform.backup_recovery --help
```

Yeni ortam kurulacaksa [README](../../README.md) ve [Contributing](../../CONTRIBUTING.md)
kullanılmalı. Python 3.13'te `constraints.txt` ile `.[api,dev]`; kapasite ölçümü için ayrıca
`capacity` extra gerekir. Python 3.11 destek tabanıdır fakat 3.13 constraints dosyasıyla
kurulmaz. Web için Node 22 ve kilit dosyasına uygun `npm ci` kullanılır.

Değişen alana göre önce odaklı testi, sonra gereken entegrasyon kapısını seç. Normal Python
kapıları:

```powershell
.venv/Scripts/python -m ruff check .
.venv/Scripts/python -m ruff format --check .
.venv/Scripts/python -m mypy
.venv/Scripts/lint-imports
.venv/Scripts/python -m pytest -n auto --dist loadscope --basetemp .pt/dev1
```

`.pt` üst dizini mevcut olmalı; `dev1` daha önce kullanılmamış kısa bir test kökü örneğidir.
Windows sandbox başlangıç izni ile domain test hatasını ayrı sınıflandır. Sonuca bakmadan
full suite'i sürekli yeniden başlatma. Kullanılan komut, exit code, source revision ve
ortam kanıta yazılmalı.

Web dizininde: `npm run typecheck`, `npm run lint`, `npm run test -- --run`,
`npm run build`, `npm run check:deployment`, `npm run size`, `npm run format:check`,
`npm run e2e`. Build normal `dist`/analysis çıktısı üretir; private üretim verisini fixture
diye değiştirme. Son E2E'de hangi public/captured veri kullanıldığı ayrıca belirtilmelidir.

Yeni gerçek servis kabulünü yalnız unit testten türetme:

| Değişiklik | İlgili mevcut doğrulama |
| --- | --- |
| Kuyruk/clock/sahiplik | `test_queue_recovery.py`, `test_advice_worker_timestamps.py`; gerekirse offline capacity ve iki süreçli kabul |
| Python/web sözleşmesi | `tests/integration/test_publication_contract.py`, `SQUADOPT_PUBLICATION_CONTRACT=1` |
| Gerçek browser/API/worker/cache | `tests/integration/test_advice_browser.py`, `SQUADOPT_BROWSER_SMOKE=1`; web bağımlılıkları ve Playwright Chromium gerekir |
| Container/persistence | `tests/integration/test_backend_container.py`; mevcut opt-in image ayarları backend runbook'tadır |
| Weekly/restore | `test_weekly_journal.py`, `test_weekly_operations.py`, `test_backup_recovery.py`, `test_backup_domain_restore.py`; kurulu wheel kabulü ayrı |
| Eski handoff script çağrısı | `test_phase_e_live.py` + `test_build_projection_handoff.py` |

Servis başlatma, Compose, private kökler ve rollback için
[backend runbook](../backend_runbook.md) ve [envanter](operations_inventory.md) izlenmeli.
Buradaki yardım komutları canlı deploy talimatı veya model aktivasyonu değildir.

## En küçük öncelikli devam işleri

| Sıra | İş ve sahibi | Bitti sayılma koşulu |
| --- | --- | --- |
| 1 | Entegrasyon geliştiricisi: güncel CI + son E2E kapanışı | Yukarıdaki tablo exact HEAD/run/ortam/kanıtla dolu; kalan hatalar açık; merge/yayın durumu ayrı. |
| 2 | İşletme sahibi: mevcut hedefi ve persistent kökleri kesinleştir | Host, image digest, store/input yolları, erişim sahibi, metrik/uyarı hedefi yazılı; gerçek mount/restart kabulü kayıtlı. Yeni altyapı satın almak bu işin varsayılanı değil. |
| 3 | İşletme sahibi: bağımsız yedek ve boş hedef restore provası | Writers-stop kanıtı, güvenilir receipt, domain ilişkileri, ölçülen süre/kapsam mevcut. RPO/RTO/retention ancak bundan sonra açık kararla belirlenir. |
| 4 | Haftalık iş sahibi: bir gerçek koşu ve eksik/başarısız koşu kontrolü | Mevcut 2–3 saat hedefiyle capture/run-id; açık expected-time; başarı, kesinti ve missed durumunun belirlenen yere ulaştığı kanıt. Canlı scheduler kurulumu ayrıca kaydedilir. |
| 5 | İbo + entegrasyon geliştiricisi: R07'nin bütün teslimatını uyarlama | Raw capture → offline replay → kulüp/model/span provenance zinciri ve locator düzeltmesi aynı sözleşmeyle doğrulanmış; ölçülmemiş model aktif değil. |
| 6 | Araştırma sahibi: R09/R10 için yeni kanıt toplama | Önceden belirlenmiş karşılaştırma ve gerçek gelecek sonuçlar; mevcut admission/promotion koşulları sağlanmadan terfi iddiası yok. |

Yeni hata yoksa sırf düzenlemek için başka klasör taşıma, script silme, geniş barrel
daraltma veya ikinci bir framework üretme. Bir sonraki değişiklik gerçek çağrı, hata
veya teslimat üzerinden küçük tutulmalı. Mevcut süreç tasarımını yeni mesaj broker'ı,
mikroservisler veya API içine gömülü worker ile değiştirmek bu devrin devam işi değildir.
Ölçülmemiş model, yeni freshness/SLO/retention politikası, uydurma notification alıcısı,
historical artifact yeniden üretimi ve eski kayıtları düzeltme adı altında yeniden yazma
bu kapsamın dışındadır.
