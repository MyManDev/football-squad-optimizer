import { createContext, useContext } from "react";
import { useQuery, type UseQueryResult } from "@tanstack/react-query";

import type { DataClient, Loaded } from "./client";
import { StaticDataClient } from "./client";
import type { LedgerView, PoolView, RecommendationView, SiteIndex, StatusView } from "./schema";

export const DataClientContext = createContext<DataClient>(new StaticDataClient());

export function useDataClient(): DataClient {
  return useContext(DataClientContext);
}

const STALE = 60_000;

export function useIndex(): UseQueryResult<Loaded<SiteIndex>> {
  const client = useDataClient();
  return useQuery({ queryKey: ["index"], queryFn: () => client.getIndex(), staleTime: STALE });
}

export function useRecommendation(
  season: string | undefined,
  gameweek: number | undefined,
): UseQueryResult<Loaded<RecommendationView>> {
  const client = useDataClient();
  return useQuery({
    queryKey: ["recommendation", season, gameweek],
    queryFn: () => client.getRecommendation(season as string, gameweek as number),
    enabled: season !== undefined && gameweek !== undefined,
    staleTime: STALE,
  });
}

export function usePool(
  season: string | undefined,
  gameweek: number | undefined,
): UseQueryResult<Loaded<PoolView>> {
  const client = useDataClient();
  return useQuery({
    queryKey: ["pool", season, gameweek],
    queryFn: () => client.getPool(season as string, gameweek as number),
    enabled: season !== undefined && gameweek !== undefined,
    staleTime: STALE,
  });
}

export function useLedger(season: string | undefined): UseQueryResult<Loaded<LedgerView>> {
  const client = useDataClient();
  return useQuery({
    queryKey: ["ledger", season],
    queryFn: () => client.getLedger(season as string),
    enabled: season !== undefined,
    staleTime: STALE,
  });
}

export function useStatus(season: string | undefined): UseQueryResult<Loaded<StatusView>> {
  const client = useDataClient();
  return useQuery({
    queryKey: ["status", season],
    queryFn: () => client.getStatus(season as string),
    enabled: season !== undefined,
    staleTime: STALE,
  });
}
