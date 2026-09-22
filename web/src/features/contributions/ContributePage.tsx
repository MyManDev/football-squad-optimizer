import { useMutation, useQuery } from "@tanstack/react-query";
import { useState, type FormEvent } from "react";

import { withRequestDeadline } from "../../data/request";
import { useLanguage } from "../../i18n/context";
import styles from "./ContributePage.module.css";

interface Catalog {
  season: string;
  captured_at_utc: string;
  teams: { id: number; name: string }[];
  players: { id: number; name: string; team_id: number; team: string; position: string }[];
}
interface Comment {
  id: number;
  author: string;
  body: string;
  source: string;
  created: number;
}

async function read(path: string, init?: RequestInit) {
  const origin = ((import.meta.env.VITE_ADVICE_API_ORIGIN as string | undefined) ?? "").replace(
    /\/$/,
    "",
  );
  return withRequestDeadline(async (signal) => {
    const response = await fetch(`${origin}/api/v1/contributions${path}`, {
      ...init,
      signal,
      cache: "no-store",
    });
    if (!response.ok) throw new Error(response.status === 429 ? "limited" : "unavailable");
    return response.json() as Promise<unknown>;
  });
}

function catalog(value: unknown): Catalog {
  const data = value as Catalog;
  if (
    !data ||
    typeof data.season !== "string" ||
    !Number.isFinite(Date.parse(data.captured_at_utc)) ||
    !Array.isArray(data.teams) ||
    !data.teams.every((t) => t && Number.isInteger(t.id) && typeof t.name === "string") ||
    !Array.isArray(data.players) ||
    !data.players.every(
      (p) =>
        p &&
        Number.isInteger(p.id) &&
        typeof p.name === "string" &&
        typeof p.team === "string" &&
        data.teams.some((t) => t.id === p.team_id && t.name === p.team) &&
        ["GK", "DEF", "MID", "FWD"].includes(p.position),
    )
  )
    throw new Error("unavailable");
  return data;
}

function comments(value: unknown): Comment[] {
  const data = value as { comments: Comment[] };
  if (
    !data ||
    !Array.isArray(data.comments) ||
    !data.comments.every(
      (c) =>
        c &&
        Number.isInteger(c.id) &&
        typeof c.author === "string" &&
        typeof c.body === "string" &&
        typeof c.source === "string" &&
        Number.isFinite(c.created),
    )
  )
    throw new Error("unavailable");
  return data.comments;
}

function sourceLink(value: string): string | undefined {
  try {
    const url = new URL(value);
    return url.protocol === "https:" && !url.username && !url.password ? url.href : undefined;
  } catch {
    return undefined;
  }
}

export function ContributePage() {
  const { language, locale } = useLanguage();
  const tr = language === "tr";
  const [playerId, setPlayerId] = useState("");
  const [teamId, setTeamId] = useState("");
  const [position, setPosition] = useState("");
  const [author, setAuthor] = useState("");
  const [body, setBody] = useState("");
  const [source, setSource] = useState("");
  const [consent, setConsent] = useState(false);
  const players = useQuery({
    queryKey: ["contribution-players"],
    queryFn: async () => catalog(await read("/players")),
    retry: false,
  });
  const season = players.data?.season;
  const teamPlayers = players.data?.players.filter((p) => String(p.team_id) === teamId) ?? [];
  const filteredPlayers = teamPlayers.filter((p) => p.position === position);
  const positions = tr
    ? { GK: "Kaleci", DEF: "Defans", MID: "Orta saha", FWD: "Forvet" }
    : { GK: "Goalkeeper", DEF: "Defender", MID: "Midfielder", FWD: "Forward" };
  const feed = useQuery({
    queryKey: ["contributions", season, playerId],
    enabled: !!season && !!playerId,
    queryFn: async () =>
      comments(await read(`?season=${encodeURIComponent(season!)}&player_id=${playerId}`)),
    retry: false,
  });
  const submit = useMutation({
    mutationFn: async () => {
      const result = (await read("", {
        method: "POST",
        headers: { "Content-Type": "application/json" },
        body: JSON.stringify({
          season,
          player_id: Number(playerId),
          author: author.trim(),
          body: body.trim(),
          source: source.trim(),
          consent,
        }),
      })) as { id?: unknown; status?: unknown };
      if (result?.status !== "pending" || !Number.isInteger(result.id))
        throw new Error("unavailable");
      return result;
    },
    onSuccess: () => {
      setBody("");
      setSource("");
      setConsent(false);
    },
  });
  function send(event: FormEvent<HTMLFormElement>) {
    event.preventDefault();
    if (!submit.isPending) submit.mutate();
  }
  function resetPlayer(next = "") {
    setPlayerId(next);
    submit.reset();
    setBody("");
    setSource("");
    setConsent(false);
  }
  return (
    <section className={styles.page}>
      <header>
        <h1>{tr ? "Katkıda bulun" : "Contribute"}</h1>
        <p>
          {tr
            ? "Bir oyuncunun rolü, dakikaları veya takımındaki değişiklikler hakkında gözlemini paylaş. Varsa haberin kaynağını ekle."
            : "Share observations about a player's role, minutes or team changes. Include a news source when available."}
        </p>
        <p>
          {tr
            ? "Yorumlar yönetici onayından sonra herkese açılır. Kullanıcı görüşleridir; doğrulanmış haber sayılmaz ve tahmin modelini otomatik değiştirmez."
            : "Comments become public after moderation. These are user opinions, not verified news, and do not automatically change predictions."}
        </p>
      </header>
      {players.isPending ? (
        <p role="status">{tr ? "Oyuncular yükleniyor…" : "Loading players…"}</p>
      ) : players.isError ? (
        <div role="alert">
          <p>
            {tr
              ? "Katkı servisine şu an ulaşılamıyor. Yorum gönderilmedi."
              : "The contribution service is unavailable. No comment was submitted."}
          </p>
          <button onClick={() => void players.refetch()}>{tr ? "Yeniden dene" : "Retry"}</button>
        </div>
      ) : (
        <>
          <label>
            {tr ? "Takım" : "Team"}
            <select
              value={teamId}
              disabled={submit.isPending}
              onChange={(event) => {
                setTeamId(event.target.value);
                setPosition("");
                resetPlayer();
              }}
            >
              <option value="">{tr ? "Takım seç" : "Choose a team"}</option>
              {players.data?.teams.map((team) => (
                <option key={team.id} value={team.id}>
                  {team.name}
                </option>
              ))}
            </select>
          </label>
          <label>
            {tr ? "Pozisyon" : "Position"}
            <select
              value={position}
              disabled={!teamId || submit.isPending}
              onChange={(event) => {
                setPosition(event.target.value);
                resetPlayer();
              }}
            >
              <option value="">{tr ? "Pozisyon seç" : "Choose a position"}</option>
              {Object.entries(positions).map(([code, name]) => (
                <option
                  key={code}
                  value={code}
                  disabled={!teamPlayers.some((p) => p.position === code)}
                >
                  {name}
                </option>
              ))}
            </select>
          </label>
          <label>
            {tr ? "Oyuncu" : "Player"}
            <select
              value={playerId}
              disabled={!teamId || !position || submit.isPending}
              onChange={(event) => resetPlayer(event.target.value)}
            >
              <option value="">{tr ? "Oyuncu seç" : "Choose a player"}</option>
              {filteredPlayers.map((player) => (
                <option key={player.id} value={player.id}>
                  {player.name} · {player.team}
                </option>
              ))}
            </select>
          </label>
          <small>
            {tr ? "Tüm FPL oyuncuları" : "Complete FPL roster"} · {season} ·{" "}
            {players.data?.players.length} {tr ? "oyuncu" : "players"} ·{" "}
            {players.data && new Date(players.data.captured_at_utc).toLocaleString(locale)}
          </small>
          {playerId && (
            <>
              <form onSubmit={send} className={styles.form}>
                <fieldset disabled={submit.isPending}>
                  <legend>{tr ? "Gözlemini paylaş" : "Share your observation"}</legend>
                  <label>
                    {tr ? "Görünen ad (takma ad olabilir)" : "Display name (a nickname is fine)"}
                    <input
                      required
                      minLength={2}
                      maxLength={40}
                      value={author}
                      onChange={(e) => setAuthor(e.target.value)}
                      autoComplete="nickname"
                    />
                  </label>
                  <label>
                    {tr ? "Oyuncu hakkında yorum" : "Player comment"}
                    <textarea
                      required
                      minLength={10}
                      maxLength={1500}
                      rows={6}
                      value={body}
                      onChange={(e) => setBody(e.target.value)}
                    />
                  </label>
                  <small>
                    {body.length}/1500 ·{" "}
                    {tr
                      ? "Kişisel bilgi, hakaret veya özel sağlık bilgisi paylaşma."
                      : "Do not share personal information, abuse or private health information."}
                  </small>
                  <label>
                    {tr
                      ? "Kaynak bağlantısı (isteğe bağlı, https://)"
                      : "Source link (optional, https://)"}
                    <input
                      type="url"
                      pattern="https://.*"
                      maxLength={500}
                      value={source}
                      onChange={(e) => setSource(e.target.value)}
                    />
                  </label>
                  <label className={styles.consent}>
                    <input
                      type="checkbox"
                      required
                      checked={consent}
                      onChange={(e) => setConsent(e.target.checked)}
                    />
                    {tr
                      ? "Adımın ve yorumumun onay sonrası herkese açık yayımlanmasını kabul ediyorum."
                      : "I agree to my display name and comment being published after approval."}
                  </label>
                  <button
                    type="submit"
                    disabled={!consent || body.trim().length < 10 || author.trim().length < 2}
                  >
                    {submit.isPending
                      ? tr
                        ? "Gönderiliyor…"
                        : "Submitting…"
                      : tr
                        ? "Onaya gönder"
                        : "Submit for approval"}
                  </button>
                </fieldset>
              </form>
              {submit.isSuccess && (
                <p role="status">
                  {tr
                    ? "Yorumun kaydedildi; yönetici onayı bekliyor. Henüz herkese açık değil."
                    : "Your comment was saved and awaits moderation. It is not public yet."}{" "}
                  #{String(submit.data.id)}
                </p>
              )}
              {submit.isError && (
                <p role="alert">
                  {submit.error.message === "limited"
                    ? tr
                      ? "Gönderim sınırına ulaşıldı. Bir saat sonra tekrar dene."
                      : "Submission limit reached. Try again in one hour."
                    : tr
                      ? "Gönderim doğrulanamadı. Yazdıkların burada duruyor; tekrar deneyebilirsin."
                      : "Submission could not be confirmed. Your text is preserved; you can retry."}
                </p>
              )}
              <section aria-label={tr ? "Onaylı yorumlar" : "Approved comments"}>
                <h2>{tr ? "Onaylı yorumlar" : "Approved comments"}</h2>
                <button onClick={() => void feed.refetch()} disabled={feed.isFetching}>
                  {tr ? "Yorumları yenile" : "Refresh comments"}
                </button>
                {feed.isPending ? (
                  <p role="status">{tr ? "Yükleniyor…" : "Loading…"}</p>
                ) : feed.isError ? (
                  <p role="alert">
                    {tr ? "Yorumlar yüklenemedi." : "Comments could not be loaded."}
                  </p>
                ) : (
                  <>
                    {!feed.data?.length && (
                      <p>
                        {tr
                          ? "Bu oyuncu için henüz onaylı yorum yok."
                          : "No approved comments for this player yet."}
                      </p>
                    )}
                    {feed.data?.map((comment) => (
                      <article key={comment.id} className={styles.comment}>
                        <strong>{comment.author}</strong> ·{" "}
                        <time dateTime={new Date(comment.created * 1000).toISOString()}>
                          {new Date(comment.created * 1000).toLocaleDateString(locale)}
                        </time>
                        <p>{comment.body}</p>
                        {sourceLink(comment.source) && (
                          <a
                            href={sourceLink(comment.source)}
                            target="_blank"
                            rel="noopener noreferrer nofollow ugc"
                          >
                            {tr ? "Paylaşılan kaynak" : "Submitted source"}
                          </a>
                        )}
                      </article>
                    ))}
                    {feed.data?.length === 50 && (
                      <p>
                        {tr
                          ? "En son 50 onaylı yorum gösteriliyor."
                          : "Showing the latest 50 approved comments."}
                      </p>
                    )}
                  </>
                )}
              </section>
            </>
          )}
        </>
      )}
    </section>
  );
}
