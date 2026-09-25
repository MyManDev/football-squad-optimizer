export const CHIP_FORECAST_COPY = {
  en: {
    calendarTrue: "A blank or double appears in the examined weeks",
    calendarFalse: "No blank or double appears in the examined weeks",
    calendarNull: "This calendar reading was refused.",
    calendarEmpty: "No later gameweek remains in a held chip window.",
    /** The examined gameweeks, first to last, after the calendar sentence. */
    range: (first: number, last: number) => `${first} to ${last}`,
    title: "Chip outlook",
    published: "Published reading",
    computed: "Newly computed reading",
    separate:
      "These readings stand separately. The new calculation only measures the chip you chose; the other current gains remain unknown.",
    play: "The rule points to playing now",
    hold: "The rule points to holding",
    unknown: "This week's gain was not computed",
    reserved: "The rule holds this chip for a gameweek with blanks or doubles.",
    gain: "This week's expected gain",
    threshold: "Rule threshold",
    later: "Calendar reading for gameweek",
    laterGain: "Scaled estimate",
    noLater: "No later gameweek in this window crosses the rule's threshold.",
    noEstimate:
      "No later estimate can be made: all players this chip reads have no fixture this week.",
    whole:
      "No later gain is estimated for this chip. That would require a new squad calculation for each week.",
    structure: "Later gameweeks with blanks or doubles",
    noStructure: "No later blank or double appears in this chip's calendar window yet.",
    doubling: "clubs with doubles",
    blank: "clubs with blanks",
    noChips: "No chip is available in the current window.",
    calendar:
      "A named week carries this week's expectation over the fixture calendar; it is not a new projection for that week. Cup rescheduling can move it.",
    squad:
      "The present fifteen and bench are held unchanged. Future transfers, injuries and rotation are not included. Players without a fixture this week are left out of later estimates.",
    evidence:
      "Development-season evidence: playing each chip when this rule's threshold was met, against never playing it, was worth +2.74 points a gameweek [+1.18, +4.26]. That is not the figure for the rule whose threshold loosens over the season, and it is not a measured gain for your team.",
    limits:
      "The system's own squad used this season's two chip windows over older seasons. Those managers had one set, so ownership and prices still describe that world.",
    action:
      "This reading is recomputed at publication. It never plays a chip for you; you decide in FPL.",
    unavailable: "The chip outlook cannot be shown. This does not change your plan.",
    reasons: {
      fixtures_unscheduled:
        "Some fixtures have no assigned gameweek, so future counts are incomplete.",
      calendar_missing: "This capture has no fixture calendar.",
      calendar_unreadable: "The fixture calendar could not be read.",
      calendar_incomplete: "The calendar is incomplete or repeats a fixture or gameweek.",
      club_roster_missing: "The complete club list is missing.",
      club_roster_incomplete:
        "The clubs in the squad and calendar do not match the complete club list.",
      capture_mismatch: "This reading does not match the squad and capture on screen.",
      chip_history_unknown:
        "Your chip history was not captured, so held chips cannot be established.",
      chip_window_unreadable: "The current chip window could not be established.",
      squad_projection_missing: "Some of your held players have no current projection.",
      forecast_inputs_unreadable: "The inputs do not form a usable chip reading.",
      forecast_unreadable: "The published chip reading is incomplete or inconsistent.",
    },
  },
  tr: {
    calendarTrue: "İncelenen haftalarda boş veya çift maç var",
    calendarFalse: "İncelenen haftalarda boş veya çift maç yok",
    calendarNull: "Bu takvim okuması yapılamadı.",
    calendarEmpty: "Eldeki çip pencerelerinde sonraki bir hafta kalmadı.",
    range: (first: number, last: number) => `${first}. ile ${last}. hafta arası`,
    title: "Çip görünümü",
    published: "Yayımlanmış okuma",
    computed: "Yeni hesaplanan okuma",
    separate:
      "Bu okumalar ayrıdır. Yeni hesap yalnızca seçtiğin çipi ölçer; diğer çiplerin bu haftaki katkısı bilinmiyor olarak kalır.",
    play: "Kural bu hafta kullanmayı gösteriyor",
    hold: "Kural bekletmeyi gösteriyor",
    unknown: "Bu haftanın katkısı hesaplanmadı",
    reserved: "Kural bu çipi boş veya çift maçlı bir hafta için bekletiyor.",
    gain: "Bu haftanın beklenen katkısı",
    threshold: "Kural eşiği",
    later: "Takvim okumasının gösterdiği hafta",
    laterGain: "Ölçeklenmiş değer",
    noLater: "Bu pencerenin sonraki haftalarında kural eşiğini geçen bir hafta yok.",
    noEstimate:
      "Sonraki haftalar için değer üretilemiyor: bu çipin okuduğu oyuncuların hiçbirinin bu hafta maçı yok.",
    whole:
      "Bu çip için sonraki haftaların katkısı hesaplanmıyor. Her hafta için yeni bir kadro hesabı gerekir.",
    structure: "Sonraki boş veya çift maçlı haftalar",
    noStructure:
      "Bu çipin takvim penceresinde henüz sonraki bir boş veya çift maçlı hafta görünmüyor.",
    doubling: "çift maçlı kulüp",
    blank: "maçı olmayan kulüp",
    noChips: "Mevcut pencerede kullanılabilir çip yok.",
    calendar:
      "Adı verilen hafta, bu haftanın beklentisini maç takvimine taşır; o hafta için yeni bir oyuncu hesabı değildir. Kupa ertelemeleri bu haftayı değiştirebilir.",
    squad:
      "Mevcut on beşli ve yedekler değişmeden tutulur. Gelecek transferler, sakatlıklar ve rotasyon hesaba katılmaz. Bu hafta maçı olmayan oyuncular sonraki hafta hesaplarına alınmaz.",
    evidence:
      "Geliştirme sezonlarındaki ölçüm: çipi bu kuralın eşiği geçildiğinde oynamak, hiç oynamamaya göre hafta başına +2,74 puan getirdi [+1,18, +4,26]. Bu, eşiği sezon içinde gevşeyen kuralın sonucu değildir; senin takımın için ölçülmüş bir katkı da değildir.",
    limits:
      "Sistemin kendi kadrosu eski sezonlarda bu sezonun iki çip penceresiyle oynatıldı. O sezonların menajerlerinde tek set vardı; sahiplik ve fiyatlar o düzeni yansıtıyor.",
    action:
      "Bu okuma her yayında yeniden hesaplanır. Senin yerine çip kullanmaz; FPL'de kararı sen verirsin.",
    unavailable: "Çip görünümü gösterilemiyor. Bu durum planını değiştirmez.",
    reasons: {
      fixtures_unscheduled:
        "Bazı maçların haftası belli değil; sonraki haftaların maç sayıları eksik.",
      calendar_missing: "Bu yakalamada maç takvimi yok.",
      calendar_unreadable: "Maç takvimi okunamadı.",
      calendar_incomplete: "Takvim eksik veya bir maç ya da hafta yineleniyor.",
      club_roster_missing: "Tam kulüp listesi eksik.",
      club_roster_incomplete: "Kadro ve takvimdeki kulüpler tam kulüp listesiyle eşleşmiyor.",
      capture_mismatch: "Bu okuma ekrandaki kadro ve yakalamayla eşleşmiyor.",
      chip_history_unknown: "Çip geçmişin yakalanmadığı için elindeki çipler belirlenemiyor.",
      chip_window_unreadable: "Mevcut çip penceresi belirlenemedi.",
      squad_projection_missing: "Elindeki bazı oyuncuların bu hafta için hesabı yok.",
      forecast_inputs_unreadable: "Girdiler kullanılabilir bir çip okuması oluşturmuyor.",
      forecast_unreadable: "Yayımlanmış çip okuması eksik veya tutarsız.",
    },
  },
} as const;
