# Top100 ağırlık karşılaştırması ve kişisel seçim

15 Eylül 2026. Bu çalışma karar hassasiyetini ölçer. Gerçekleşen puan kazancı veya
tahmin doğruluğu için bir kazanan belirlemez. Kullanıcının istediği seçenekler:
**%0, %5, %10, %20, %30, %40, %50**.

## Hesaplama

```text
destek = önceki haftada oyuncuyu ilk 11'e alan Top100 takım sayısı / 100
yeni_puan = temel_puan × (1 + seçilen_yüzde / 100 × destek)
```

Örneğin 40 takımın seçtiği oyuncuda %50 ayarı, temel puanı %20 artırır. Bu katsayı
gerçek maçta ilk 11 başlama veya puan kazanma olasılığı değildir. Top100'ün önceki
FPL ilk 11 tercihidir. %0 sinyali kapatır; sıfır destekli oyuncunun puanı değişmez.

Kaynak projeksiyonda zaten %5 varsa kişisel hesaplama onu değiştirir:
`mevcut_puan × (1 + yeni_ağırlık × destek) / (1 + 0.05 × destek)`.
Artışlar üst üste uygulanmaz. Sakatlık/uygunluk düzeltmesi tekrar uygulanmaz;
sıfırlanmış bir oyuncunun puanı sıfır kalır. Aynı oran 1, 3 ve 5 haftalık
pencerelerin her haftasında kullanılır. Bu bağımsız dalda saf puan 1/3/5 hafta, rakip stratejileri yalnız 1 hafta desteklenir.
Hepsi aynı kişisel projeksiyonu kullanır; bütçe ve transfer kuralları korunur.
Çok haftalık rakip stratejileri ayrı #559 çalışmasıdır.

## Veri ve kapsam

- Kaynak: `fpl-live-20260912T100000Z-24613792ef57`, 2026–27 GW4.
- Kontrol: `data/handoffs/2026-27-gw04.json`, `phase_c_control_components_v1`.
  Bu dosyada Top100 uygulanmamış; fiilî başlangıç ağırlığı **%0**.
- Kanıt: `player_evidence_v1_2026-27_gw04_top100_a0f72a506e05.csv` ve eş manifesti.
  Üretim zamanı `2026-09-12T09:59:43Z`, karar kaydından ve son tarihten önce.
  Mevcut doğrulama 100 gözlenen takım ve toplam 1.100 ilk 11 seçimi gerektirir.
- Bir hafta: kayıtlı **15 kullanıcı × 7 oran = 105 hesaplama**, hepsi `OPTIMAL`.
- Üç/beş hafta: giriş kimliğine göre sıralı kayıt listesindeki ilk kullanıcı,
  her pencerede aynı 7 oran. Bu dar örnek, tüm ligin uzun vadeli karşılaştırması değildir.
- Aynı kadrolar, aynı eldeki transfer hakları, aynı bütçe, fiyat ve fikstür verisi,
  aynı `saf-puan` stratejisi ve mevcut çözücü sınırları kullanıldı.

Kontrol handoff SHA-256:
`0727b28ff30e589aac49650d6f80bed2d36a1293bffe3ecd1a3042ccd223248d`.
Kanıt CSV SHA-256:
`68fc7a8e74796e2586a6bd1611ff205da9fba1917a56f5e2faa35b0eeac4d170`.

Yerel kayıtlarda tamamlanmış GW1–3 var. Bu haftalar için eşleşen, son tarih
öncesi karar ve Top100 veri dizisi yok. Kontrol sırasında resmî FPL API, GW4'ü
`finished=false`, `data_checked=false` olarak döndürdü. Sonradan yakalanan bilgiyi
eski haftaya taşıyarak geriye dönük başarı hesabı yapılmadı. Gerçekleşen sonuç
alanları bu nedenle `null`; rapor durumu `decision_sensitivity_only`.

## Bir haftalık sonuçlar

Her satır %0 ile aynı kullanıcı üzerinde karşılaştırılır. Karar değişikliği:
transfer, ilk 11 kümesi veya kaptanın değişmesi. Sadece sayısal puan artışı
karar değişikliği sayılmaz. Temel puan farkı, seçilen ilk 11 ve kaptanın **aynı
ağırlıksız modeldeki** puanları eksi transfer cezasıdır; gerçekleşen puan değildir.

| Top100 ayarı | Kararı değişen | Transferi değişen | Kaptanı değişen | Ortalama tercih bedeli (temel puan) | İlk 11 ortalama Top100 desteği |
| --- | ---: | ---: | ---: | ---: | ---: |
| %0 | 0/15 | 0/15 | 0/15 | 0,000 | %20,15 |
| %5 | 3/15 | 3/15 | 0/15 | 0,015 | %21,29 |
| %10 | 7/15 | 7/15 | 2/15 | 0,140 | %22,86 |
| %20 | 13/15 | 13/15 | 3/15 | 0,471 | %25,90 |
| %30 | 14/15 | 13/15 | 3/15 | 0,556 | %26,93 |
| %40 | 14/15 | 13/15 | 3/15 | 0,556 | %26,93 |
| %50 | 14/15 | 14/15 | 4/15 | 0,711 | %26,01 |

%30 ve %40 bu örnekte aynı ilk 11, transfer ve kaptan seçimlerini üretti.
%50'nin daha büyük katsayısı, ilk 11'in ortalama destek payını zorunlu olarak
artırmaz: hedef fonksiyonu kaptanı ve yedek kulübesini de değerlendirir; bütçe
seçimlerin birbirini etkilemesine neden olur.

Bu sonuçlar %20–%50'nin temel modelin tercihlerine belirgin müdahale ettiğini
gösterir. Bir doğruluk veya başarı sıralaması değildir. Varsayılanı ölçümden
bir kazanan seçerek değiştirmek için yeterli kanıt yoktur.

Bu sütun ağırlıksız modeldeki **tercih bedelidir**: sıfır ağırlıklı plan eksi seçilen
plan. Ham ölçüm dosyası ters yöndeki farkı saklamaya devam eder. Aynı uygun kadrolar
arasında yalnız hedef katsayıları değiştiğinden bu tablo Top100 sinyalinin gelecek
puanlara etkisini ölçmez. OPTIMAL, yedek ve transfer temkin payı da içeren çözücü
hedefinin ispatıdır; gösterilen ilk 11 net puanının ayrı bir optimum ispatı değildir.

## Üç ve beş haftalık örnek

**14/14 hesaplama geçerli plan buldu; hepsi `FEASIBLE`, hiçbiri `OPTIMAL` değil.**
Mevcut süre sınırındaki arama farkları da sonucu etkileyebilir. Her hücre aynı tek
kullanıcının kendi %0 planına göre ilk hafta temel net puan farkını gösterir.
Bu tablo toplam pencere başarısı veya ağırlık sıralaması olarak okunmamalıdır.

| Top100 ayarı | 3 hafta: ilk hafta temel puan farkı | 5 hafta: ilk hafta temel puan farkı |
| --- | ---: | ---: |
| %0 | 0,000 | 0,000 |
| %5 | 0,000 | +0,350 |
| %10 | 0,000 | +0,350 |
| %20 | 0,000 | +0,528 |
| %30 | −0,040 | −0,234 |
| %40 | −0,040 | +0,311 |
| %50 | −0,040 | +0,311 |

Üç haftada ilk hafta kararı %30'dan itibaren, beş haftada %5'ten itibaren
değişti. Bu, yalnız ilk hafta kararına ilişkin karşılaştırmadır; sonraki
haftaların transferleri ham raporda ayrıca saklanır. Toplam **119 hesaplamanın**
kullanıcı kimliği içermeyen sayısal özeti ve her uzun vadeli planın çözücü farkı
[ölçüm dosyasında](../top100_weights_20260915.json) bulunur.

Uzun pencerelerde kontrol ve adayların çözüm açıkları üç haftada 17,3–32,1,
beş haftada 38,9–59,2 puandır. Küçük pozitif hücreler bir kazanç bulgusu değildir.

## Tercihin canlı fiyatı

Kişisel yanıtta `top100_price`, aynı strateji, rakip ve pencerenin sıfır ağırlıklı
planıyla karşılaştırmayı taşır. Seçilen **gerçek ilk 11 ve kaptan**, her haftada
Top100 çarpanı geri alınarak temel modelde puanlanır; transfer cezaları bir kez düşer.
Plan yeniden kadro seçilerek puanlanmaz. Bedel `max(0, kontrol_net - seçilen_net)`tir.

`expected_points_cost_ceiling` her kişisel fiyatla birlikte zorunludur. Üst sınır,
her haftanın en yüksek temel puanlı on bir oyuncusunu ve en yüksek kaptan puanını
kullanarak bütçe, pozisyon, takım ve transfer kısıtlarını gevşetir. Bu yüzden geniş
olabilir; FEASIBLE sonuçlarda veya yedek değerinin hedefe girdiği durumda da geçerlidir.
Arayüz bulunan planların bedelini ve bu muhafazakâr üst sınırı ayrı gösterir.

Sıfır ayarı ek çözüm gerektirmez ve tercih bedeli sıfırdır. Diğer kişisel ayarlar
aynı koşullarda bir sıfır-ağırlık referans hesabı daha yapar; bu ek süre yalnız
istek üzerine hesaplamaya aittir, haftalık lig yayınına ek çözüm getirmez. Referans
hesaplanamazsa fiyatı eksik bir kişisel sonuç yayımlanmaz. Yedi seçenek korunur;
ayrı yedi davranış veya monoton ortaklık artışı vaat edilmez.

## Sisteme bağlantı

Arayüzde hesaplama servisi bağlıysa **Top100 etkisi** seçimi görünür. Varsayılan
**Yayınlanan ayarı kullan**; kaynağın gerçekten kullandığı ağırlık sonuçta yazılır.
URL'de `top100=50` gibi saklanır. Seçim değişince önceki hesaplama durumu sıfırlanır.
Kullanıcı **Hesapla** ile seçili oranı uygular. Statik site kişisel sonuç üretemez.

GET sorgusu ve POST gövdesindeki `top100_weight_percent`, isteğin kimliğine,
kuyruk işine ve önbellek anahtarına dahildir. Eksik/null değer yayınlanan ayardır;
açıkça gönderilen %0 veya %5 ayrı kişisel seçimdir. Sonuç
`top100_weight_percent` ve `top100_weight_source` (`published`/`personal`) taşır.
Tarayıcı yanlış orandaki cevabı reddeder. Servis erişilemezse statik bir öneri
kişisel oranla hesaplanmış gibi gösterilmez.

Yeni kanıtlı handoff üretimi, doğrulanmış `elite_start_counts` alanını dosyaya ve
parmak izine ekler. Normal haftalık `component` akışı zaten Top100 kanıt çiftini
`build_handoff` çağrısına geçirir. API için yeni bir haricî veri servisi gerekmez.
Eski handoff dosyaları okunmaya devam eder; sayımlar yoksa sıfır dışındaki kişisel ayarın fiyatlandırılması
`TOP100_INPUTS_UNAVAILABLE` ile açıkça reddedilir.

**Yayına alma önkoşulu:** backend ve web sürümünün birlikte dağıtılması ve geçerli
Top100 kanıtıyla yeni handoff üretilmesi gerekir. Mevcut GW4 kontrol dosyasında
sayımlar yoktur; o dosya ile yayınlanan ayar/%0 çalışır, %5–%50 değişikliği çalışmaz.
Bu çalışma mevcut dosyayı değiştirmedi veya canlı siteye dağıtım yapmadı.
İşletimde normal haftalık üretim kullanılmalı; geçmiş karar dosyası yeni bilgiyle
üzerine yazılmamalıdır. Yayınlanan operasyonel %5 politikasının kimliği değişmedi.

## Tekrar çalıştırma

Depo kökünden, mevcut sanal ortam ve kayıtlı veriyle:

```powershell
.venv/Scripts/python.exe -m scripts.measure_top100_weights --snapshot fpl-live-20260912T100000Z-24613792ef57 --handoff data/handoffs/2026-27-gw04.json --evidence artifacts/phase_b/player_evidence_v1_2026-27_gw04_top100_a0f72a506e05.csv --windows 1 --workers 3 --out .codex-tmp/top100-weight-measurement/one-week
.venv/Scripts/python.exe -m scripts.measure_top100_weights --snapshot fpl-live-20260912T100000Z-24613792ef57 --handoff data/handoffs/2026-27-gw04.json --evidence artifacts/phase_b/player_evidence_v1_2026-27_gw04_top100_a0f72a506e05.csv --windows 3 5 --limit 1 --workers 2 --out .codex-tmp/top100-weight-measurement/multiweek
```

Ham kullanıcı kayıtları git dışında kalır. Çıktı her oran için çözüm/hata durumunu,
karar kimliklerini, temel puan maliyetini ve çözücü durumunu saklar. Süre sınırlı
`FEASIBLE` planlar, `OPTIMAL` sonuçlarla eşdeğer bir optimum karşılaştırması sayılmaz.

Gerçek başarı ölçümü için sonraki adım, aynı kararları değiştirmeden tamamlanmış
GW4 sonuçlarıyla değerlendirmek; ardından birden fazla son tarih öncesi kayıt
üzerinde bütün oranları aynı haftalarda karşılaştırmaktır. Seçilen katsayıyla
şişen tahmin toplamı bir başarı ölçütü olarak kullanılmamalıdır.

## Doğrulama

#565 düzeltmesi `develop` tabanındaki bağımsız `codex/top100-565-fixes` dalındadır;
#559 kodu bu dalın önkoşulu değildir. Yeni metinlerin tamamı iki dilde ana `MESSAGES`
sözlüğündedir. `AS_A_CHANCE` değiştirilmedi; kontrol değerleri `50 / 100` gibi gösterilir.

Üç gerçek Chromium → API → worker → cache senaryosu 235,00 saniyede geçti.
Bunlar yayınlanan tek haftayı, kişisel 50 tek haftayı ve kişisel 20 beş haftayı kapsar.
Linux/amd64 Docker imajında dört kabul testi 43,52 saniyede geçti. Konteyner kontrolü
bu backend değişikliği için yerel doğrulamaya dahil edildi; mevcut GitHub korumasında
ayrı zorunlu merge kapısı değildir. Bu sonuç bulut NFS veya canlı dağıtım kanıtı değildir.

Son tam Python/web kapılarının sonuçları son doğrulama tamamlandığında kaydedilecektir.
