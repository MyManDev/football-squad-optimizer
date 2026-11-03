import type { Language } from "../../../i18n/messages";
import type { WindowSize } from "../../../lib/decisionVocabulary";
import type { WaitingPhase } from "./useAdviceJob";

/**
 * The compute service's copy, in both languages.
 *
 * It lives beside the panel that reads it, like the manager's-word and Top 100 copy, so it
 * loads with the member page and not with every first visit. The honesty sweep
 * (`i18n/messagesNoProbability.test.ts`) walks it entry by entry, functions called.
 *
 * What it may say: that a selection can be computed now, about how long a computation took
 * when it was measured, that the page can be left open, where a waiting job stands, and, when
 * something fails, what happened in a sentence the member can act on. A duration is "about",
 * and a job's stages are a count ("1/3"), never a percentage. A failure is said
 * from the service's stable code, or in the general sentence where a code gives the member
 * nothing to do; the code itself and the service's own text are never shown.
 */
export interface ComputeCopy {
  notPrecomputed: string;
  notComputable: string;
  duration: Record<WindowSize, string>;
  leaveOpen: string;
  /** A queued job's place in line, said after the word for queued. */
  queueNext: string;
  queueAhead: (count: number) => string;
  /** The workers at work out of those alive. */
  workersBusy: (busy: number, total: number) => string;
  /** The service is down and nothing is published here, but the member's device solves it. */
  serviceUnreachableDevice: string;
  /** The gameweek this page advises on has closed. */
  deadlinePassedTitle: string;
  rateLimitedFor: (seconds: number) => string;
  failures: Record<string, string> & { unknown: string };
}

const en: ComputeCopy = {
  notPrecomputed: "You can compute it now.",
  notComputable: "Change the selection to use Compute.",
  duration: {
    1: "A one-week plan takes between a few seconds and half a minute to compute; a rival strategy and the settings you switch on make it longer.",
    3: "A 3-week plan takes about a minute and a half to compute, and up to two and a half minutes for a rival strategy.",
    5: "A 5-week pure points plan takes about three and a half minutes to compute.",
  },
  leaveOpen: "You can leave this page open; the plan appears here when the computation finishes.",
  queueNext: "yours is next",
  queueAhead: (count) =>
    count === 1 ? "1 computation ahead of yours" : `${count} computations ahead of yours`,
  workersBusy: (busy, total) => `Workers busy: ${busy}/${total}`,
  serviceUnreachableDevice: "This selection can be computed on this device.",
  deadlinePassedTitle: "This gameweek's deadline has passed",
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
    UNKNOWN_ENTRY: "The service could not find this member or this rival in the league.",
    UNKNOWN_STRATEGY: "The service does not compute this strategy.",
    NOT_COMPUTED:
      "The computation finished but its result was not found. You can press Compute again.",
    NOT_FOUND: "The service no longer knows this computation. You can press Compute again.",
    IDEMPOTENCY_CONFLICT: "The request collided with another one. You can press Compute again.",
    REQUEST_CONFLICT: "The request collided with another one. You can press Compute again.",
    RATE_LIMITED: "Too many requests arrived in a short time. Wait a little and try again.",
    OPEN_JOB_LIMITED:
      "This connection already has several computations open. Wait for one to finish, then try again.",
    DEADLINE_PASSED:
      "This gameweek's deadline has passed. Previously computed plans remain available.",
    NOT_READY: "The compute service is not ready yet. Try again in a little while.",
    QUEUE_UNAVAILABLE:
      "The queue could not take the request just now. Try again in a little while.",
    SERVICE_UNREACHABLE: "The compute service could not be reached.",
    CONTEXT_UNAVAILABLE: "Reload the page and try again.",
    ENTRY_NOT_IN_CAPTURE: "No squad for this member or this rival.",
    PLAN_NOT_FOUND: "The service found no plan for this selection.",
    SWITCH_INPUTS_CHANGED:
      "The Top 100 selections or the club news were refreshed while this was computing. Press Compute again.",
    REQUEST_UNREADABLE: "The service could not read the request. You can press Compute again.",
    PATIENCE_EXHAUSTED:
      "The computation took longer than this page waits. If the service has finished since, pressing Compute again brings the result at once.",
    ANSWER_OTHER_CAPTURE: "Reload the page and try again.",
    unknown: "The computation did not complete.",
  },
};

const tr: ComputeCopy = {
  notPrecomputed: "Şimdi hesaplatabilirsin.",
  notComputable: "Hesapla için seçimi değiştir.",
  duration: {
    1: "Bir haftalık planın hesabı birkaç saniye ile yarım dakika arasında sürer; rakip stratejisi ve açtığın ayarlar süreyi uzatır.",
    3: "3 haftalık planın hesabı yaklaşık bir buçuk dakika, rakip stratejisinde iki buçuk dakikaya kadar sürer.",
    5: "5 haftalık saf puan planının hesabı yaklaşık üç buçuk dakika sürer.",
  },
  leaveOpen: "Sayfayı açık bırakabilirsin; hesap bitince plan burada görünür.",
  queueNext: "sıradaki hesap senin",
  queueAhead: (count) => `önünde ${count} hesap var`,
  workersBusy: (busy, total) => `Çalışan işçi: ${busy}/${total}`,
  serviceUnreachableDevice: "Bu seçim bu cihazda hesaplanabilir.",
  deadlinePassedTitle: "Bu oyun haftasının son tarihi geçti",
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
    UNKNOWN_ENTRY: "Servis bu üyeyi ya da bu rakibi ligde bulamadı.",
    UNKNOWN_STRATEGY: "Servis bu stratejiyi hesaplamıyor.",
    NOT_COMPUTED: "Hesap bitti ama sonucu bulunamadı. Yeniden Hesapla'ya basabilirsin.",
    NOT_FOUND: "Servis bu hesabı artık tanımıyor. Yeniden Hesapla'ya basabilirsin.",
    IDEMPOTENCY_CONFLICT: "İstek başka bir istekle çakıştı. Yeniden Hesapla'ya basabilirsin.",
    REQUEST_CONFLICT: "İstek başka bir istekle çakıştı. Yeniden Hesapla'ya basabilirsin.",
    RATE_LIMITED: "Kısa sürede çok fazla istek geldi. Biraz bekleyip yeniden dene.",
    OPEN_JOB_LIMITED:
      "Bu bağlantıda zaten birkaç hesaplama açık. Birinin bitmesini bekleyip yeniden dene.",
    DEADLINE_PASSED:
      "Bu oyun haftasının son tarihi geçti. Önceden hesaplanan planlara erişebilirsin.",
    NOT_READY: "Hesaplama servisi henüz hazır değil. Biraz sonra yeniden dene.",
    QUEUE_UNAVAILABLE: "Hesap sırası isteği şu an alamadı. Biraz sonra yeniden dene.",
    SERVICE_UNREACHABLE: "Hesaplama servisine ulaşılamadı.",
    CONTEXT_UNAVAILABLE: "Sayfayı yenileyip yeniden dene.",
    ENTRY_NOT_IN_CAPTURE: "Bu üyenin ya da bu rakibin kadrosu yok.",
    PLAN_NOT_FOUND: "Servis bu seçim için plan bulamadı.",
    SWITCH_INPUTS_CHANGED:
      "Hesap sürerken Top 100 seçimleri ya da kulüp haberleri yenilendi. Yeniden Hesapla'ya bas.",
    REQUEST_UNREADABLE: "Servis isteği okuyamadı. Yeniden Hesapla'ya basabilirsin.",
    PATIENCE_EXHAUSTED:
      "Hesap bu sayfanın beklediğinden uzun sürdü. Servis o arada bitirdiyse, yeniden Hesapla'ya basınca sonuç hemen gelir.",
    ANSWER_OTHER_CAPTURE: "Sayfayı yenileyip yeniden dene.",
    unknown: "Hesap tamamlanamadı.",
  },
};

export const COMPUTE_COPY: Record<Language, ComputeCopy> = { tr, en };

/**
 * What goes beside a waiting job's word: its place in line, or how many of its stages are
 * done. Null where the service has not said. A job of one stage has nothing to count: "0/1"
 * would only stand still until it ends.
 */
export function jobStanding(
  copy: ComputeCopy,
  { status, queuePosition, progress }: Pick<WaitingPhase, "status" | "queuePosition" | "progress">,
): string | null {
  if (status === "queued") {
    if (queuePosition === undefined) return null;
    return queuePosition === 0 ? copy.queueNext : copy.queueAhead(queuePosition);
  }
  return progress !== undefined && progress.total > 1 ? `${progress.done}/${progress.total}` : null;
}

/** The line about the workers; null where the service has not said or counts none alive. */
export function jobWorkersLine(
  copy: ComputeCopy,
  { status, workers }: Pick<WaitingPhase, "status" | "workers">,
): string | null {
  if (workers === undefined || workers.total === 0) return null;
  // A running job's own worker holds it, though the count can be a few seconds behind.
  const busy = status === "running" ? Math.max(workers.busy, 1) : workers.busy;
  return copy.workersBusy(busy, workers.total);
}

/**
 * The sentence for a failure. A code with no sentence of its own, one this page does not
 * know among them, says only that the computation did not complete; nothing the service
 * sent is ever printed.
 */
export function failureSentence(
  copy: ComputeCopy,
  reason: string | null | undefined,
  retryAfterSeconds?: number | null,
): string {
  if (reason === "RATE_LIMITED" && retryAfterSeconds != null && retryAfterSeconds > 0) {
    return copy.rateLimitedFor(retryAfterSeconds);
  }
  const known = reason != null && Object.hasOwn(copy.failures, reason) ? reason : "unknown";
  return copy.failures[known] ?? copy.failures.unknown;
}
