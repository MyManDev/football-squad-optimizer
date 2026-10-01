export function expectedLineupLabel(value: string, language: "tr" | "en"): string {
  return language === "tr"
    ? `otomatik değişikliklerle beklenen puan: ${value}`
    : `expected points with automatic substitutions: ${value}`;
}
