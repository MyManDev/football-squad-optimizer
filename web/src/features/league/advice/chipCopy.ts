import type { Language } from "../../../i18n/messages";
import type { MemberChip } from "./chipChoice";

/**
 * The chip choice copy, in both languages.
 *
 * It lives beside the components that read it, like the manager's-word and Top 100 copy,
 * so it loads with the member page and not with every first visit. The honesty sweep
 * (`i18n/messagesNoProbability.test.ts`) walks it entry by entry, functions called.
 *
 * What it may say: the chip is there because the member chose it, what the chip week is
 * expected to score above the member's own plan without it, and that this is one
 * gameweek's difference. It never says this is the week to play the chip, because what the
 * chip would be worth in a later gameweek is not measured anywhere.
 */
export interface ChipCopy {
  legend: string;
  none: string;
  help: string;
  plain: string;
  onlyBaseline: string;
  blockedBySwitches: string;
  switchesOff: string;
  notOffered: string;
  unavailableReasons: Record<string, string> & { unknown: string };
  chipReasons: Record<string, string> & { unknown: string };
  chipReasonLine: (name: string, reason: string) => string;
  title: string;
  chosen: (name: string) => string;
  gain: (points: string) => string;
  honesty: string;
  unproven: string;
  freeHit: string;
  basis: Record<MemberChip, string>;
  expectedOwnPoints: (points: string, basis: string) => string;
  projectedGain: (points: string, basis: string) => string;
  moveRowsBasis: (basis: string) => string;
  planGainVsHold: (points: string, basis: string) => string;
  planGainVsHoldBeforeCost: (points: string, cost: string, basis: string) => string;
  limits: Record<string, string>;
}

/** The producer's two chip sentences, as `application/advice_chips.py` states them. */
const CHIP_CHOICE_LIMIT =
  "The chip is in this plan because the member chose it; the planner did not weigh it. The gain stated is this gameweek's only: what the chip would be worth in a later gameweek is not measured, so this is not advice to play it now.";
const FREE_HIT_LIMIT =
  "A Free Hit squad is held for this gameweek only; the squad held before it returns at the next deadline.";

const en: ChipCopy = {
  legend: "Chip",
  none: "None",
  help: "Choosing a chip shows your one-week plan with that chip played this gameweek, and what that week is expected to score above your own plan without it. The planner never chooses a chip itself: what a chip would be worth in a later gameweek is not measured, so nothing here says this is the gameweek to play it.",
  plain: "No chip is selected; the published plan plays none.",
  onlyBaseline: "One-week pure-points plan only.",
  blockedBySwitches:
    "A chip plan is solved on the plain one-week plan only. Switch the manager's word off and set the Top 100 influence to 0 to choose a chip.",
  switchesOff:
    "A chip is selected, and a chip plan is solved without the manager's word and without a Top 100 setting. Choose None under Chip to use them.",
  notOffered:
    "The chip in the link cannot be shown for this member in this publish; the plan without a chip is shown.",
  unavailableReasons: {
    chip_history_unknown: "This member's chip history was not captured, so no chip is offered.",
    no_chip_left: "This member has no chip that can be played this gameweek.",
    not_solved_for_member: "No chip plan was solved for this member in this publish.",
    unknown: "No chip plan can be shown for this member from this publish.",
  },
  chipReasons: {
    already_played: "already played",
    window_not_open: "its window is not open this gameweek",
    free_hit_played_last_gameweek:
      "a Free Hit was played last gameweek, and the game does not allow two in a row",
    not_solved_for_member: "no plan was solved in this publish",
    unknown: "not offered in this publish",
  },
  chipReasonLine: (name, reason) => `${name}: ${reason}.`,
  title: "Chip choice",
  chosen: (name) => `${name} is played this gameweek because you chose it.`,
  gain: (points) =>
    `~${points} expected points this gameweek against your own plan without the chip, hits included.`,
  honesty:
    "This is one gameweek's difference. What the chip would be worth in a later gameweek is not measured, so this is not advice to play it now.",
  unproven:
    "The solver found at least one of the two plans without finishing its proof, so the difference is between the plans it found.",
  freeHit:
    "A Free Hit squad is for this gameweek only; the squad you hold now returns at the next deadline.",
  basis: {
    wildcard: "the eleven with the captain doubled",
    freehit: "the eleven with the captain doubled",
    "3xc": "the eleven with the captain tripled",
    bboost: "all fifteen players with the captain doubled",
  },
  expectedOwnPoints: (points, basis) => `${points} expected points for ${basis}`,
  projectedGain: (points, basis) => `${points} for ${basis}`,
  moveRowsBasis: (basis) =>
    `Each row is what the total for ${basis} moves by once that swap is added to the rows above it, so the rows add up to the whole plan's gain below. Keeping your squad is counted with the same chip played.`,
  planGainVsHold: (points, basis) =>
    `${points} expected points against keeping the squad you hold and playing the same chip, for ${basis}.`,
  planGainVsHoldBeforeCost: (points, cost, basis) =>
    `${points} expected points against keeping the squad you hold and playing the same chip, for ${basis}, before this week's transfer cost of ${cost}.`,
  limits: {
    [CHIP_CHOICE_LIMIT]:
      "The chip is in this plan because you chose it; the planner did not weigh it. The gain stated is this gameweek's only: what the chip would be worth in a later gameweek is not measured, so this is not advice to play it now.",
    [FREE_HIT_LIMIT]:
      "A Free Hit squad is held for this gameweek only; the squad held before it returns at the next deadline.",
  },
};

const tr: ChipCopy = {
  legend: "Çip",
  none: "Yok",
  help: "Bir çip seçersen bir haftalık planın, o çip bu hafta oynanmış haliyle gösterilir; yanında da o haftanın çipsiz kendi planına göre beklenen puan farkı yazar. Planlayıcı çipi hiçbir zaman kendisi seçmez: bir çipin sonraki bir haftada kaç puan getireceği ölçülmedi, bu yüzden buradaki hiçbir şey çipi oynama haftasının bu hafta olduğunu söylemez.",
  plain: "Çip seçili değil; yayınlanan plan çip oynamaz.",
  onlyBaseline: "Yalnız bir haftalık saf puan planında.",
  blockedBySwitches:
    "Çipli plan yalnız sade bir haftalık plan üzerinde çözülür. Çip seçmek için hocanın sözünü kapat ve Top 100 etkisini 0 yap.",
  switchesOff:
    "Bir çip seçili; çipli plan hocanın sözü ve Top 100 ayarı olmadan çözülür. Bunları kullanmak için Çip bölümünde Yok'u seç.",
  notOffered: "Bağlantıdaki çip bu yayında bu üye için gösterilemiyor; çipsiz plan gösteriliyor.",
  unavailableReasons: {
    chip_history_unknown: "Bu üyenin çip geçmişi okunamadı; bu yüzden çip sunulmuyor.",
    no_chip_left: "Bu üyenin bu hafta oynayabileceği çip yok.",
    not_solved_for_member: "Bu yayında bu üye için çipli plan çözülmedi.",
    unknown: "Bu yayından bu üye için çipli plan gösterilemiyor.",
  },
  chipReasons: {
    already_played: "daha önce oynandı",
    window_not_open: "bu hafta oynanabileceği dönem açık değil",
    free_hit_played_last_gameweek:
      "geçen hafta Free Hit oynandı, oyun üst üste iki hafta oynatmıyor",
    not_solved_for_member: "bu yayında planı çözülmedi",
    unknown: "bu yayında sunulmuyor",
  },
  chipReasonLine: (name, reason) => `${name}: ${reason}.`,
  title: "Çip seçimi",
  chosen: (name) => `${name} bu hafta oynanıyor, çünkü sen seçtin.`,
  gain: (points) => `Çipsiz kendi planına göre bu hafta ~${points} beklenen puan, cezalar dahil.`,
  honesty:
    "Bu yalnız bu haftanın farkıdır. Çipin sonraki bir haftada kaç puan getireceği ölçülmedi; bu yüzden bu, çipi şimdi oyna tavsiyesi değildir.",
  unproven:
    "Çözücü iki plandan en az birini ispatını bitirmeden buldu; fark, bulduğu planlar arasındaki farktır.",
  freeHit:
    "Free Hit kadrosu yalnız bu hafta içindir; bir sonraki haftada şimdiki kadron geri gelir.",
  basis: {
    wildcard: "ilk on bir, kaptan iki kat",
    freehit: "ilk on bir, kaptan iki kat",
    "3xc": "ilk on bir, kaptan üç kat",
    bboost: "on beş oyuncunun tamamı, kaptan iki kat",
  },
  expectedOwnPoints: (points, basis) => `${points} beklenen puan (${basis})`,
  projectedGain: (points, basis) => `${points} (${basis})`,
  moveRowsBasis: (basis) =>
    `Her satır, o takas kendisinden önceki satırlara eklendiğinde toplamın (${basis}) ne kadar değiştiğini gösterir; bu yüzden satırlar aşağıdaki toplam kazancı verir. Mevcut kadroyu korumak da aynı çip oynanmış sayılarak hesaplanır.`,
  planGainVsHold: (points, basis) =>
    `Mevcut kadronu koruyup aynı çipi oynamaya göre ${points} beklenen puan (${basis}).`,
  planGainVsHoldBeforeCost: (points, cost, basis) =>
    `Mevcut kadronu koruyup aynı çipi oynamaya göre ${points} beklenen puan (${basis}); bu haftanın ${cost} transfer maliyeti düşülmeden önce.`,
  limits: {
    [CHIP_CHOICE_LIMIT]:
      "Çip bu planda, çünkü sen seçtin; planlayıcı çipi tartmadı. Yazan kazanç yalnız bu haftanındır: çipin sonraki bir haftada kaç puan getireceği ölçülmedi, bu yüzden bu, çipi şimdi oyna tavsiyesi değildir.",
    [FREE_HIT_LIMIT]:
      "Free Hit kadrosu yalnız bu hafta tutulur; ondan önceki kadro bir sonraki haftada geri gelir.",
  },
};

export const CHIP_COPY: Record<Language, ChipCopy> = { tr, en };

/** The sentence for an index reason; a reason this page does not know claims nothing. */
export function chipsUnavailable(copy: ChipCopy, reason: string | null): string {
  return (
    (reason !== null && Object.hasOwn(copy.unavailableReasons, reason)
      ? copy.unavailableReasons[reason]
      : undefined) ?? copy.unavailableReasons.unknown
  );
}

/** Why one chip has no plan, in the member's language; an unknown code claims nothing. */
export function chipReason(copy: ChipCopy, reason: string | undefined): string {
  return (
    (reason !== undefined && Object.hasOwn(copy.chipReasons, reason)
      ? copy.chipReasons[reason]
      : undefined) ?? copy.chipReasons.unknown
  );
}

/** A producer sentence the chip documents added, in the member's language; null for any other. */
export function chipLimit(copy: ChipCopy, sentence: string): string | null {
  return Object.hasOwn(copy.limits, sentence) ? copy.limits[sentence]! : null;
}

/** Whether a chip week scores on another basis than the eleven with the captain doubled. */
export function chipRescores(chip: MemberChip): boolean {
  return chip === "3xc" || chip === "bboost";
}
