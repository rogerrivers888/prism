import { useQuery } from "@tanstack/react-query";
import { API_BASE_URL } from "./config";
import type { components } from "./schema";

export type CompanyOut = components["schemas"]["CompanyOut"];
export type LensDetail = components["schemas"]["LensDetail"];
export type PeerRow = components["schemas"]["PeerRow"];
export type MetricSeries = components["schemas"]["MetricSeries"];

async function get<T>(path: string): Promise<T> {
  const response = await fetch(`${API_BASE_URL}${path}`);
  if (!response.ok) throw new Error(`${path} failed: ${response.status}`);
  return response.json();
}

export function useCompany(ticker: string) {
  return useQuery({
    queryKey: ["company", ticker],
    queryFn: () => get<CompanyOut>(`/company/${ticker}`),
    staleTime: 5 * 60 * 1000,
  });
}

export function usePeers(ticker: string, lens: string | null) {
  return useQuery({
    queryKey: ["peers", ticker, lens],
    queryFn: () => get<PeerRow[]>(`/company/${ticker}/peers?lens=${lens}`),
    enabled: Boolean(lens),
    staleTime: 5 * 60 * 1000,
  });
}

export function useMetricHistory(
  ticker: string,
  metrics: string[],
  range: "12M" | "5Y" | "MAX",
) {
  return useQuery({
    queryKey: ["metric-history", ticker, metrics.join(","), range],
    queryFn: () =>
      get<MetricSeries[]>(
        `/company/${ticker}/metric-history?metrics=${metrics.join(",")}&range=${range}`,
      ),
    enabled: metrics.length > 0,
    staleTime: 5 * 60 * 1000,
  });
}
