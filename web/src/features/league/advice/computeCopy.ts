import type { Language } from "../../../i18n/messages";
import type { WindowSize } from "../../moves/modePrices";

/**
 * The compute service's copy, in both languages.
 *
 * It lives beside the panel and the controls that read it, like the manager's-word and
 * Top 100 copy, so it loads with the member page and not with every first visit. The
 * honesty sweep (`i18n/messagesNoProbability.test.ts`) walks it entry by entry, functions
 * called.
 *
 * What it may say: that a selection was not computed ahead of time and can be computed
 * now, about how long a computation took when it was measured, that the page can be left
 * open, and, when something fails, what happened in a sentence the member can act on. A
 * duration is "about" and never a promise. A failure is said from the service's stable
 * code; the code itself and the service's own text are never shown.
 */
export interface ComputeCopy {
  notPrecomputed: string;
  notComputable: string;
  chipUnavailable: string;
  chipDurationUnknown: string;
  duration: Record<WindowSize, string>;
  durationNote: string;
  leaveOpen: string;
  serviceUnreachable: string;
  otherCapture: string;
  controlsNote: string;
  wordComputable: string;
  top100Computable: string;
  rivalComputable: string;
  rateLimitedFor: (seconds: number) => string;
  failures: Record<string, string> & { unknown: string };
}

const en: ComputeCopy = {
  notPrecomputed:
    "This selection was not computed ahead of time for this publish. You can compute it now.",
  notComputable:
    "The service does not compute this selection right now. Change the selection to use Compute.",
  chipUnavailable:
    "The service cannot confirm this chip is available for this selection. The published plan, if any, still stands.",
  chipDurationUnknown: "The time to compute a chosen chip has not been measured.",
  duration: {
    1: "A one-week plan takes between a few seconds and half a minute to compute; a rival strategy and the settings you switch on make it longer.",
    3: "A 3-week plan takes about a minute and a half to compute, and up to two and a half minutes for a rival strategy.",
    5: "A 5-week pure points plan takes about three and a half minutes to compute; a rival strategy was not measured.",
  },
  durationNote:
    "These times were measured once and are not a promise; other computations ahead of yours make the wait longer.",
  leaveOpen:
    "You can leave this page open; the plan appears here when the computation finishes. If you reload, the wait picks up where it was.",
  serviceUnreachable:
    "The compute service cannot be reached right now. The published plans are below, as always.",
  otherCapture:
    "The compute service is working from a different data capture than this page, so only the published plans are shown.",
  controlsNote:
    "A selection that was not published can still be chosen; Compute below works it out now.",
  wordComputable: "Not solved in this publish. Switch it on and Compute works it out now.",
  top100Computable: "A setting with no published plan is worked out now with Compute.",
  rivalComputable: "Any member can be chosen; a pair that was not published is computed now.",
  rateLimitedFor: (seconds) =>
    `Too many requests arrived in a short time. Try again in about ${seconds} seconds.`,
  failures: {
    UNSUPPORTED_ADVICE_REQUEST: "The service does not compute this selection.",
    VALIDATION_FAILED: "The service does not compute this selection.",
    TOP100_INPUTS_UNAVAILABLE:
      "The service has no Top 100 selections for this gameweek. Set the influence to 0 and try again.",
    MANAGERS_WORD_UNAVAILABLE:
      "The service has no club news for this gameweek. Switch the manager's word off and try again.",
    CHIP_NOT_HELD:
      "This member cannot play the chosen chip this gameweek. Choose another chip or no chip.",
    CHIP_HISTORY_UNKNOWN: "The service could not confirm which chips this member holds.",
    UNKNOWN_ENTRY: "The service could not find this member or this rival in the league.",
    LEAGUE_NOT_CONNECTED: "This league is not connected to the compute service.",
    UNKNOWN_STRATEGY: "The service does not compute this strategy.",
    NOT_COMPUTED:
      "The computation finished but its result was not found. You can press Compute again.",
    NOT_FOUND: "The service no longer knows this computation. You can press Compute again.",
    IDEMPOTENCY_CONFLICT: "The request collided with another one. You can press Compute again.",
    REQUEST_CONFLICT: "The request collided with another one. You can press Compute again.",
    RATE_LIMITED: "Too many requests arrived in a short time. Wait a little and try again.",
    NOT_READY: "The compute service is not ready yet. Try again in a little while.",
    QUEUE_UNAVAILABLE:
      "The queue could not take the request just now. Try again in a little while.",
    QUEUE_INTEGRITY_ERROR:
      "The compute service cannot answer right now. The published plan, if any, still stands.",
    ADVICE_BACKEND_DISABLED:
      "The compute service cannot answer right now. The published plan, if any, still stands.",
    INTERNAL_ERROR:
      "The compute service cannot answer right now. The published plan, if any, still stands.",
    SERVICE_UNREACHABLE:
      "The compute service could not be reached. The published plan, if any, still stands.",
    ADVICE_FAILED:
      "The service could not solve this plan. The published plan, if any, still stands.",
    CONTEXT_UNAVAILABLE:
      "The service's data capture changed while this was computing. Reload the page and try again.",
    ENTRY_NOT_IN_CAPTURE: "The service's data capture has no squad for this member or this rival.",
    TOO_MANY_ATTEMPTS: "The service tried this computation several times and could not finish it.",
    PLAN_NOT_FOUND:
      "The service found no plan for this selection. The published plan, if any, still stands.",
    SWITCH_INPUTS_CHANGED:
      "The Top 100 selections or the club news were refreshed while this was computing. Press Compute again.",
    REQUEST_UNREADABLE: "The service could not read the request. You can press Compute again.",
    DETERMINISM_DEFECT: "The service could not confirm this result, so it is not shown.",
    PATIENCE_EXHAUSTED:
      "The computation took longer than this page waits. If the service has finished since, pressing Compute again brings the result at once.",
    ANSWER_UNREADABLE: "The computation finished but its answer could not be read.",
    ANSWER_MISMATCH: "The returned answer does not match this selection, so it is not shown.",
    ANSWER_OTHER_CAPTURE:
      "The service computed this from a different data capture than this page shows, so it is not shown. Reload the page and try again.",
    unknown: "The computation did not complete. The published plan, if any, still stands.",
  },
};

const tr: ComputeCopy = {
  notPrecomputed: "Bu seçim bu yayın için önceden hesaplanmadı. Şimdi hesaplatabilirsin.",
  notComputable: "Servis bu seçimi şu an hesaplamıyor. Hesapla için seçimi değiştir.",
  chipUnavailable:
    "Servis bu seçim için çipin kullanılabilir olduğunu doğrulayamıyor. Yayınlanmış plan varsa olduğu gibi duruyor.",
  chipDurationUnknown: "Seçilen çipin hesaplama süresi ölçülmedi.",
  duration: {
    1: "Bir haftalık planın hesabı birkaç saniye ile yarım dakika arasında sürer; rakip stratejisi ve açtığın ayarlar süreyi uzatır.",
    3: "3 haftalık planın hesabı yaklaşık bir buçuk dakika, rakip stratejisinde iki buçuk dakikaya kadar sürer.",
    5: "5 haftalık saf puan planının hesabı yaklaşık üç buçuk dakika sürer; rakip stratejisinde ölçülmedi.",
  },
  durationNote:
    "Bu süreler bir kez ölçüldü, söz değildir; sırada senden önce başka hesap varsa bekleme uzar.",
  leaveOpen:
    "Sayfayı açık bırakabilirsin; hesap bitince plan burada görünür. Sayfayı yenilersen bekleme kaldığı yerden sürer.",
  serviceUnreachable:
    "Hesaplama servisine şu an ulaşılamıyor. Yayınlanmış planlar her zamanki gibi aşağıda.",
  otherCapture:
    "Hesaplama servisi şu an bu sayfadakinden farklı bir veri kaydıyla çalışıyor; bu yüzden yalnız yayınlanmış planlar gösteriliyor.",
  controlsNote: "Yayınlanmamış bir seçimi de seçebilirsin; aşağıdaki Hesapla onu şimdi hesaplar.",
  wordComputable: "Bu yayında çözülmedi. Açarsan Hesapla onu şimdi hesaplar.",
  top100Computable: "Yayınlanmış planı olmayan bir ayarı Hesapla şimdi hesaplar.",
  rivalComputable: "Her üye seçilebilir; yayınlanmamış bir eşleşme şimdi hesaplanır.",
  rateLimitedFor: (seconds) =>
    `Kısa sürede çok fazla istek geldi. Yaklaşık ${seconds} saniye sonra yeniden dene.`,
  failures: {
    UNSUPPORTED_ADVICE_REQUEST: "Servis bu seçimi hesaplamıyor.",
    VALIDATION_FAILED: "Servis bu seçimi hesaplamıyor.",
    TOP100_INPUTS_UNAVAILABLE:
      "Serviste bu hafta için Top 100 seçimleri yok. Etkiyi 0 yapıp yeniden dene.",
    MANAGERS_WORD_UNAVAILABLE:
      "Serviste bu hafta için kulüp haberi yok. Hocanın sözünü kapatıp yeniden dene.",
    CHIP_NOT_HELD: "Bu üye seçilen çipi bu hafta oynayamıyor. Başka bir çip seç ya da çipi kapat.",
    CHIP_HISTORY_UNKNOWN: "Servis bu üyenin hangi çiplere sahip olduğunu doğrulayamadı.",
    UNKNOWN_ENTRY: "Servis bu üyeyi ya da bu rakibi ligde bulamadı.",
    LEAGUE_NOT_CONNECTED: "Bu lig hesaplama servisine bağlı değil.",
    UNKNOWN_STRATEGY: "Servis bu stratejiyi hesaplamıyor.",
    NOT_COMPUTED: "Hesap bitti ama sonucu bulunamadı. Yeniden Hesapla'ya basabilirsin.",
    NOT_FOUND: "Servis bu hesabı artık tanımıyor. Yeniden Hesapla'ya basabilirsin.",
    IDEMPOTENCY_CONFLICT: "İstek başka bir istekle çakıştı. Yeniden Hesapla'ya basabilirsin.",
    REQUEST_CONFLICT: "İstek başka bir istekle çakıştı. Yeniden Hesapla'ya basabilirsin.",
    RATE_LIMITED: "Kısa sürede çok fazla istek geldi. Biraz bekleyip yeniden dene.",
    NOT_READY: "Hesaplama servisi henüz hazır değil. Biraz sonra yeniden dene.",
    QUEUE_UNAVAILABLE: "Hesap sırası isteği şu an alamadı. Biraz sonra yeniden dene.",
    QUEUE_INTEGRITY_ERROR:
      "Hesaplama servisi şu an cevap veremiyor. Yayınlanmış plan, varsa, geçerli olmaya devam ediyor.",
    ADVICE_BACKEND_DISABLED:
      "Hesaplama servisi şu an cevap veremiyor. Yayınlanmış plan, varsa, geçerli olmaya devam ediyor.",
    INTERNAL_ERROR:
      "Hesaplama servisi şu an cevap veremiyor. Yayınlanmış plan, varsa, geçerli olmaya devam ediyor.",
    SERVICE_UNREACHABLE:
      "Hesaplama servisine ulaşılamadı. Yayınlanmış plan, varsa, geçerli olmaya devam ediyor.",
    ADVICE_FAILED:
      "Servis bu planı çözemedi. Yayınlanmış plan, varsa, geçerli olmaya devam ediyor.",
    CONTEXT_UNAVAILABLE:
      "Hesap sürerken servisin veri kaydı değişti. Sayfayı yenileyip yeniden dene.",
    ENTRY_NOT_IN_CAPTURE: "Servisin veri kaydında bu üyenin ya da bu rakibin kadrosu yok.",
    TOO_MANY_ATTEMPTS: "Servis bu hesabı birkaç kez denedi ve bitiremedi.",
    PLAN_NOT_FOUND:
      "Servis bu seçim için plan bulamadı. Yayınlanmış plan varsa olduğu gibi duruyor.",
    SWITCH_INPUTS_CHANGED:
      "Hesap sürerken Top 100 seçimleri ya da kulüp haberleri yenilendi. Yeniden Hesapla'ya bas.",
    REQUEST_UNREADABLE: "Servis isteği okuyamadı. Yeniden Hesapla'ya basabilirsin.",
    DETERMINISM_DEFECT: "Servis bu sonucu doğrulayamadı; bu yüzden gösterilmiyor.",
    PATIENCE_EXHAUSTED:
      "Hesap bu sayfanın beklediğinden uzun sürdü. Servis o arada bitirdiyse, yeniden Hesapla'ya basınca sonuç hemen gelir.",
    ANSWER_UNREADABLE: "Hesap bitti ama cevabı okunamadı.",
    ANSWER_MISMATCH: "Dönen cevap bu seçimle eşleşmiyor; bu yüzden gösterilmiyor.",
    ANSWER_OTHER_CAPTURE:
      "Servis bunu bu sayfadakinden farklı bir veri kaydıyla hesapladı; bu yüzden gösterilmiyor. Sayfayı yenileyip yeniden dene.",
    unknown: "Hesap tamamlanamadı. Yayınlanmış plan, varsa, geçerli olmaya devam ediyor.",
  },
};

export const COMPUTE_COPY: Record<Language, ComputeCopy> = { tr, en };

/**
 * The sentence for a failure. A code this page does not know says only that the
 * computation did not complete; nothing the service sent is ever printed.
 */
export function failureSentence(
  copy: ComputeCopy,
  reason: string | null | undefined,
  retryAfterSeconds?: number | null,
): string {
  if (reason === "RATE_LIMITED" && retryAfterSeconds != null && retryAfterSeconds > 0) {
    return copy.rateLimitedFor(retryAfterSeconds);
  }
  return (
    (reason != null && Object.hasOwn(copy.failures, reason) ? copy.failures[reason] : undefined) ??
    copy.failures.unknown
  );
}
