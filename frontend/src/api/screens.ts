import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE_URL } from "./config";

async function req<T>(path: string, init?: RequestInit): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`, {
    headers: init?.body ? { "content-type": "application/json" } : undefined,
    ...init,
  });
  if (!response.ok) throw new Error(`${path} failed: ${response.status}`);
  return response.json();
}

export const useWatchlist = () =>
  useQuery({ queryKey: ["watchlist"], queryFn: () => req<{ ticker: string; note: string | null; added_at: string }[]>("/watchlist") });

export function useWatchToggle() {
  const client = useQueryClient();
  return useMutation({
    mutationFn: ({ ticker, watched }: { ticker: string; watched: boolean }) =>
      watched
        ? req(`/watchlist/${ticker}`, { method: "DELETE" })
        : req("/watchlist", { method: "POST", body: JSON.stringify({ ticker }) }),
    onSuccess: () => client.invalidateQueries({ queryKey: ["watchlist"] }),
  });
}

export type Point = {
  id: number; scope_type: string; scope_value: string; stance: string;
  body: string; source_title: string | null; source_url: string | null;
  pinned: boolean; stress_test: string | null; created_at: string;
};
export const usePoints = (scopeValue?: string) =>
  useQuery({
    queryKey: ["points", scopeValue],
    queryFn: () => req<Point[]>(`/research/points${scopeValue ? `?scope_value=${scopeValue}` : ""}`),
  });

export type Clip = {
  id: number; title: string; body: string; url: string | null;
  summary: string | null; tickers: string[]; created_at: string;
};
export const useClips = (q: string) =>
  useQuery({ queryKey: ["clips", q], queryFn: () => req<Clip[]>(`/research/clips${q ? `?q=${encodeURIComponent(q)}` : ""}`) });

export const useSectorAggregates = () =>
  useQuery({ queryKey: ["sector-aggregates"], queryFn: () => req<Record<string, unknown>[]>("/research/sectors") });

export type BookOut = {
  positions: Record<string, unknown>[];
  committed_capital: number | null;
  total_notional: number; total_risk: number;
  clusters: { driver: string; positions: string[]; notional: number; risk: number }[];
};
export const useBook = () => useQuery({ queryKey: ["book"], queryFn: () => req<BookOut>("/book") });

export type DecisionOut = {
  stream_id: string; ticker: string | null; kind: string; status: string;
  thesis: string; premortem: string; falsifier: string;
  decision_quality: string | null; outcome_quality: string | null;
  error_tag: string | null; close_note: string | null;
  raised_at: string; closed_at: string | null;
};
export const useDecisions = () =>
  useQuery({ queryKey: ["decisions"], queryFn: () => req<DecisionOut[]>("/decisions") });

export { req };
