import type { Language } from "../../i18n/messages";

export interface PrivacySection {
  title: string;
  body: string;
}

export interface PrivacyCopy {
  title: string;
  sections: readonly PrivacySection[];
}

/**
 * What the site sends where, one short section per flow. Each sentence names a flow the code
 * has: the browser's own storage, the FPL forwarder (ADR 0012), the backend's calculations,
 * LLMOPT's model call, the deadline reminder (ADR 0013), the usage record (ADR 0014) and the
 * comments on the contribute page.
 */
export const PRIVACY_COPY: Record<Language, PrivacyCopy> = {
  en: {
    title: "Privacy",
    sections: [
      {
        title: "No account",
        body: "SquadOpt asks for no sign-up, password or email. Your language, theme and the league and team you pick stay in your browser.",
      },
      {
        title: "FPL data",
        body: "League tables and squads are FPL's public data. The site reads them from FPL through its own forwarder.",
      },
      {
        title: "Calculations",
        body: "A plan calculated on our server sends your team and league numbers with the request, and the result is kept so the same request is answered again. A plan calculated on your device stays on it.",
      },
      {
        title: "LLMOPT",
        body: "What you write in LLMOPT and the candidate players for your squad are sent to Google Gemini to read your request. Your team number and name are not sent, and your text is not written to our server's logs. Google may use this text and its answer to improve its products, and people at Google may read them, so do not write personal information in LLMOPT. With your own API key, your text goes directly from your browser to the provider you chose, and the key stays only in that tab and is never sent to SquadOpt.",
      },
      {
        title: "Deadline reminder",
        body: "Turning the reminder on stores your browser's notification subscription, the language and the page to open. Turning it off deletes them.",
      },
      {
        title: "Usage",
        body: "We count which pages and tools are opened, with the language and device type. No team number, name or address is recorded.",
      },
      {
        title: "Comments",
        body: "A name and comment you send on the contribute page are shown to everyone once approved. A one-way code of your address is kept for a day to limit repeated sending.",
      },
    ],
  },
  tr: {
    title: "Gizlilik",
    sections: [
      {
        title: "Hesap yok",
        body: "SquadOpt üyelik, şifre ya da e-posta istemez. Dilin, temanın ve seçtiğin lig ile takım yalnızca tarayıcında kalır.",
      },
      {
        title: "FPL verisi",
        body: "Lig tabloları ve kadrolar FPL'in herkese açık verisidir. Site bunları kendi aktarıcısı üzerinden FPL'den okur.",
      },
      {
        title: "Hesaplamalar",
        body: "Sunucumuzda hesaplanan bir plan için takım ve lig numaran istekle birlikte gönderilir; aynı istek tekrar cevaplansın diye sonuç saklanır. Cihazında hesaplanan plan cihazında kalır.",
      },
      {
        title: "LLMOPT",
        body: "LLMOPT'a yazdığın metin ve kadron için aday oyuncular, isteğini anlamak üzere Google Gemini'ye gönderilir. Takım numaran ve adın gönderilmez, metnin sunucu kayıtlarımıza yazılmaz. Google bu metni ve cevabını ürünlerini geliştirmek için kullanabilir ve Google çalışanları okuyabilir; LLMOPT'a kişisel bilgi yazma. Kendi API anahtarınla metnin tarayıcından doğrudan seçtiğin sağlayıcıya gider; anahtar yalnızca o sekmede kalır ve SquadOpt'a hiç gönderilmez.",
      },
      {
        title: "Deadline hatırlatıcısı",
        body: "Hatırlatıcıyı açarsan tarayıcının bildirim aboneliği, dil ve açılacak sayfa saklanır. Kapatınca silinir.",
      },
      {
        title: "Kullanım",
        body: "Hangi sayfa ve aracın açıldığını, dil ve cihaz türüyle birlikte sayarız. Takım numarası, ad ya da adres kaydedilmez.",
      },
      {
        title: "Yorumlar",
        body: "Katkı sayfasından gönderdiğin ad ve yorum, onaylanırsa herkese gösterilir. Tekrar tekrar gönderimi sınırlamak için adresinden üretilen geri çevrilemez bir kod bir gün tutulur.",
      },
    ],
  },
};
