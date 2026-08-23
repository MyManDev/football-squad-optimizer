import { useSearchParams } from "react-router";

import { WINDOWS, isPlayMode, type PlayMode, type WindowSize } from "./modePrices";

function isWindowSize(value: string | null): value is `${WindowSize}` {
  return WINDOWS.some((window) => String(window) === value);
}

export interface DecisionSelection {
  mode: PlayMode;
  windowSize: WindowSize;
  update: (key: "mode" | "window", value: string) => void;
}

export function useDecisionSelection(): DecisionSelection {
  const [searchParams, setSearchParams] = useSearchParams();
  const rawMode = searchParams.get("mode");
  const rawWindow = searchParams.get("window");
  const mode: PlayMode = isPlayMode(rawMode) ? rawMode : "saf-puan";
  const windowSize: WindowSize = isWindowSize(rawWindow) ? (Number(rawWindow) as WindowSize) : 1;

  function update(key: "mode" | "window", value: string): void {
    const next = new URLSearchParams(searchParams);
    next.set(key, value);
    setSearchParams(next);
  }

  return { mode, windowSize, update };
}
