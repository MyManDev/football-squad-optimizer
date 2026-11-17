import type { Language } from "../../i18n/messages";

/**
 * The usage record's admin page and heatmap mode (ADR 0016), in both languages.
 *
 * It lives beside the components that read it, so it loads with their own chunks and never
 * with a public page. The honesty sweep (`i18n/messagesNoProbability.test.ts`) walks it entry
 * by entry, functions called. Shares are formatted where they are drawn, so no entry here
 * carries a sign for one.
 *
 * The record's own words (page, tool and zone names) are shown as the record spells them;
 * the words a reader needs explained are named here.
 */
export interface UsageAdminCopy {
  title: string;
  intro: string;
  rangeLegend: string;
  today: string;
  days: (count: number) => string;
  from: string;
  to: string;
  rangeShown: (from: string, to: string) => string;
  rangeUnreadable: (days: number) => string;
  loading: string;
  signedOut: string;
  signedOutBody: string;
  refused: string;
  refusedBody: string;
  notConfigured: string;
  notConfiguredBody: string;
  failed: string;
  failedBody: string;
  retry: string;
  empty: string;
  emptyBody: string;
  truncated: string;
  nothing: string;

  totals: string;
  visits: string;
  events: string;
  claimShare: string;
  returningShare: string;
  phoneShare: string;
  frustrationShare: string;

  funnel: string;
  ofOpened: string;
  steps: Record<"open" | "picker_shown" | "picker_claimed" | "tool" | "device_solve", string>;
  tools: string;
  pages: string;
  name: string;
  noTool: string;
  sources: string;
  returns: string;
  sourceNames: Record<"direct" | "internal" | "other", string>;
  visitNames: Record<"new" | "same_week" | "last_week" | "weeks_2_4" | "older" | "unknown", string>;

  perPage: string;
  page: string;
  device: string;
  deviceNames: Record<"phone" | "tablet" | "desktop" | "unknown", string>;
  scroll: string;
  depth: string;
  atLeast: (depth: string) => string;
  views: string;
  share: string;
  dwell: string;
  dwellNames: Record<"s5" | "s15" | "s30" | "s60" | "s180" | "s600" | "long", string>;

  vitals: string;
  metric: string;
  readings: string;
  p75: string;
  rating: string;
  ratingNames: Record<"good" | "needs" | "poor", string>;
  milliseconds: (value: string) => string;

  errors: string;
  error: string;
  errorNames: Record<"script" | "promise" | "chunk", string>;

  clicks: string;
  zone: string;
  clickCount: string;
  rage: string;
  dead: string;

  heatmapOpen: string;
  heatmapTitle: string;
  mark: string;
  markNames: Record<"all" | "rage" | "dead", string>;
  heatRange: string;
  heatTotal: (count: string) => string;
  heatPage: (page: string) => string;
  heatLoading: string;
  heatFailed: string;
  heatEmpty: string;
  legendFew: string;
  legendMany: string;
  close: string;
}

const en: UsageAdminCopy = {
  title: "Usage record",
  intro: "What the site's visitors did, counted without names. Dates are UTC days.",
  rangeLegend: "Range",
  today: "Today",
  days: (count) => `${count} days`,
  from: "From",
  to: "To",
  rangeShown: (from, to) => `${from} to ${to}, both included`,
  rangeUnreadable: (days) =>
    `Choose a start before the end, an end no later than today, and at most ${days} days.`,
  loading: "Reading the record",
  signedOut: "You are not signed in",
  signedOutBody: "Reload the page and Cloudflare Access will ask you to sign in.",
  refused: "This account may not read the record",
  refusedBody: "Sign in with an address on the admin list, or ask the owner to add yours.",
  notConfigured: "The report is not set up yet",
  notConfiguredBody: "The usage Worker has no Access or analytics settings.",
  failed: "The record could not be read",
  failedBody: "The answer did not arrive or was not a report.",
  retry: "Try again",
  empty: "Nothing recorded in this range",
  emptyBody: "Choose a longer range or a later day.",
  truncated: "The range holds more rows than one report reads; these counts are partial.",
  nothing: "none",

  totals: "Totals",
  visits: "Visits",
  events: "Events",
  claimShare: "Picker: name taken",
  returningShare: "Returning visits",
  phoneShare: "Phone visits",
  frustrationShare: "Rage and dead clicks",

  funnel: "Funnel",
  ofOpened: "Of opened",
  steps: {
    open: "Opened a page",
    picker_shown: "Saw the picker",
    picker_claimed: "Took a name",
    tool: "Used a tool",
    device_solve: "Solved on the device",
  },
  tools: "Tools",
  pages: "Pages",
  name: "Name",
  noTool: "(no tool)",
  sources: "Sources",
  returns: "Returns",
  sourceNames: { direct: "Direct", internal: "From the site", other: "Other" },
  visitNames: {
    new: "First visit",
    same_week: "Same week",
    last_week: "Last week",
    weeks_2_4: "2 to 4 weeks ago",
    older: "Older",
    unknown: "Unknown",
  },

  perPage: "Page and device",
  page: "Page",
  device: "Device",
  deviceNames: { phone: "Phone", tablet: "Tablet", desktop: "Desktop", unknown: "Unknown" },
  scroll: "Scroll depth",
  depth: "Depth",
  atLeast: (depth) => `at least ${depth} seen`,
  views: "Page views",
  share: "Share",
  dwell: "Time on page",
  dwellNames: {
    s5: "Under 5 s",
    s15: "5 to 15 s",
    s30: "15 to 30 s",
    s60: "30 to 60 s",
    s180: "1 to 3 min",
    s600: "3 to 10 min",
    long: "Over 10 min",
  },

  vitals: "Speed (Web Vitals)",
  metric: "Metric",
  readings: "Readings",
  p75: "p75",
  rating: "Rating",
  ratingNames: { good: "Good", needs: "Needs work", poor: "Poor" },
  milliseconds: (value) => `${value} ms`,

  errors: "Errors",
  error: "Error",
  errorNames: { script: "Script error", promise: "Unhandled promise", chunk: "Failed to load" },

  clicks: "Clicks by zone",
  zone: "Zone",
  clickCount: "Clicks",
  rage: "Rage",
  dead: "Dead",

  heatmapOpen: "Heatmap",
  heatmapTitle: "Clicks on this page",
  mark: "Clicks",
  markNames: { all: "All", rage: "Rage", dead: "Dead" },
  heatRange: "Range",
  heatTotal: (count) => `${count} clicks drawn`,
  heatPage: (page) => `Page: ${page}`,
  heatLoading: "Reading the record",
  heatFailed: "The record could not be read.",
  heatEmpty: "No clicks for this choice.",
  legendFew: "Few",
  legendMany: "Many",
  close: "Close",
};

const tr: UsageAdminCopy = {
  title: "Kullanım kaydı",
  intro: "Ziyaretçilerin sitede yaptıkları, isimsiz sayılmış hâliyle. Tarihler UTC günüdür.",
  rangeLegend: "Aralık",
  today: "Bugün",
  days: (count) => `${count} gün`,
  from: "Başlangıç",
  to: "Bitiş",
  rangeShown: (from, to) => `${from} ile ${to} arası, iki gün de dahil`,
  rangeUnreadable: (days) =>
    `Başlangıç bitişten önce, bitiş en geç bugün ve aralık en çok ${days} gün olmalı.`,
  loading: "Kayıt okunuyor",
  signedOut: "Oturum açık değil",
  signedOutBody: "Sayfayı yenileyin; Cloudflare Access giriş yapmanızı isteyecek.",
  refused: "Bu hesap kaydı okuyamaz",
  refusedBody:
    "Yönetici listesindeki bir adresle girin ya da sahibinden adresinizi eklemesini isteyin.",
  notConfigured: "Rapor henüz kurulmadı",
  notConfiguredBody: "Kullanım Worker'ında Access ya da analiz ayarları yok.",
  failed: "Kayıt okunamadı",
  failedBody: "Yanıt gelmedi ya da bir rapor değildi.",
  retry: "Tekrar dene",
  empty: "Bu aralıkta kayıt yok",
  emptyBody: "Daha uzun bir aralık ya da daha yakın bir gün seçin.",
  truncated: "Aralıkta bir raporun okuduğundan fazla satır var; sayılar eksik.",
  nothing: "yok",

  totals: "Toplamlar",
  visits: "Ziyaret",
  events: "Olay",
  claimShare: "Seçici: isim alındı",
  returningShare: "Geri gelen ziyaretler",
  phoneShare: "Telefondan ziyaretler",
  frustrationShare: "Öfkeli ve boş tıklamalar",

  funnel: "Huni",
  ofOpened: "Açanlara oranı",
  steps: {
    open: "Sayfa açtı",
    picker_shown: "Seçiciyi gördü",
    picker_claimed: "İsim aldı",
    tool: "Araç kullandı",
    device_solve: "Cihazda çözdü",
  },
  tools: "Araçlar",
  pages: "Sayfalar",
  name: "Ad",
  noTool: "(araç yok)",
  sources: "Kaynaklar",
  returns: "Geri dönüşler",
  sourceNames: { direct: "Doğrudan", internal: "Site içinden", other: "Diğer" },
  visitNames: {
    new: "İlk ziyaret",
    same_week: "Aynı hafta",
    last_week: "Geçen hafta",
    weeks_2_4: "2 ile 4 hafta önce",
    older: "Daha eski",
    unknown: "Bilinmiyor",
  },

  perPage: "Sayfa ve cihaz",
  page: "Sayfa",
  device: "Cihaz",
  deviceNames: { phone: "Telefon", tablet: "Tablet", desktop: "Masaüstü", unknown: "Bilinmiyor" },
  scroll: "Kaydırma derinliği",
  depth: "Derinlik",
  atLeast: (depth) => `en az ${depth} görüldü`,
  views: "Görüntüleme",
  share: "Oran",
  dwell: "Sayfada kalma süresi",
  dwellNames: {
    s5: "5 sn altı",
    s15: "5 ile 15 sn",
    s30: "15 ile 30 sn",
    s60: "30 ile 60 sn",
    s180: "1 ile 3 dk",
    s600: "3 ile 10 dk",
    long: "10 dk üstü",
  },

  vitals: "Hız (Web Vitals)",
  metric: "Ölçü",
  readings: "Okuma",
  p75: "p75",
  rating: "Değerlendirme",
  ratingNames: { good: "İyi", needs: "Geliştirilmeli", poor: "Zayıf" },
  milliseconds: (value) => `${value} ms`,

  errors: "Hatalar",
  error: "Hata",
  errorNames: { script: "Betik hatası", promise: "Yakalanmayan promise", chunk: "Yüklenemedi" },

  clicks: "Bölgelere göre tıklamalar",
  zone: "Bölge",
  clickCount: "Tıklama",
  rage: "Öfkeli",
  dead: "Boş",

  heatmapOpen: "Isı haritası",
  heatmapTitle: "Bu sayfadaki tıklamalar",
  mark: "Tıklamalar",
  markNames: { all: "Tümü", rage: "Öfkeli", dead: "Boş" },
  heatRange: "Aralık",
  heatTotal: (count) => `${count} tıklama çizildi`,
  heatPage: (page) => `Sayfa: ${page}`,
  heatLoading: "Kayıt okunuyor",
  heatFailed: "Kayıt okunamadı.",
  heatEmpty: "Bu seçim için tıklama yok.",
  legendFew: "Az",
  legendMany: "Çok",
  close: "Kapat",
};

export const USAGE_ADMIN_COPY: Record<Language, UsageAdminCopy> = { en, tr };
