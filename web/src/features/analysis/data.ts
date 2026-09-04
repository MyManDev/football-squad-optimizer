export type MeasurementType = "passed" | "negative" | "descriptive" | "prereg";

export interface MeasurementEntry {
  slug: string;
  title: string;
  date: string | null;
  type: MeasurementType;
  phase: string;
  finding: string;
  markdown_path: string;
  json_path: string | null;
}

export interface AnalysisIndex {
  contract_version: "web_analysis_index_v1";
  entries: MeasurementEntry[];
}

export function analysisAsset(path: string): string {
  return `${import.meta.env.BASE_URL}analysis/${path}`;
}

export async function fetchAnalysisIndex(): Promise<AnalysisIndex> {
  const response = await fetch(analysisAsset("index.json"));
  if (!response.ok) throw new Error(`Analysis index request failed: ${response.status}`);
  return (await response.json()) as AnalysisIndex;
}

export async function fetchMarkdown(path: string): Promise<string> {
  const response = await fetch(analysisAsset(path));
  if (!response.ok) throw new Error(`Measurement document request failed: ${response.status}`);
  return response.text();
}
