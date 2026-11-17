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
        body: "LLMOPT's chat works with your own model key. What you write and the candidate players for your squad go from your browser straight to the provider you chose, under your key, and that provider's terms apply to them. Our server prepares the request and checks the answer: it receives your text for that, does not write it to its logs, and never receives the key. The key stays only in that tab, is deleted when you leave the page, and is never sent to SquadOpt. Your team number and name are not sent.",
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
        body: "LLMOPT sohbeti kendi model anahtarınla çalışır. Yazdığın metin ve kadron için aday oyuncular, tarayıcından doğrudan seçtiğin sağlayıcıya, senin anahtarınla gider; bu veriler için o sağlayıcının koşulları geçerlidir. Sunucumuz isteği hazırlar ve cevabı denetler: bunun için metnini alır, kayıtlarına yazmaz, anahtarı ise hiç almaz. Anahtar yalnızca o sekmede kalır, sayfadan çıkınca silinir ve SquadOpt'a hiç gönderilmez. Takım numaran ve adın gönderilmez.",
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
