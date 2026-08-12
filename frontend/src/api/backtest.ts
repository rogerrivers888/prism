import { useMutation, useQuery } from "@tanstack/react-query";
import { API_BASE_URL } from "./config";

export type Caveat = { severity: "high" | "medium" | "low"; title: string; body: string };

export type Overall = {
  trades: number;
  mean_return_pct: number;
  median_return_pct: number;
  mean_gross_return_pct: number;
  cost_drag_pct: number;
  win_rate: number;
  expectancy_r: number;
  max_drawdown_pct: number;
  stdev_pct: number;
  distribution: Record<string, number>;
  caught_by_early_report: number;
  mean_holding_days: number;
};

export type Significance = {
  mean_excess_pct: number;
  p5: number;
  p95: number;
  share_non_positive: number;
  inside_noise: boolean;
};

export type BacktestResult = {
  strategy: string;
  params: Record<string, unknown>;
  overall: Overall;
  breakdowns: Record<string, Record<string, { trades: number; mean_return_pct: number; win_rate: number }>>;
  bootstrap: { mean: number; p5: number; p95: number; share_non_positive: number; inside_noise: boolean } | null;
  control_unconditional_drift: { samples: number; mean_return_pct: number; win_rate: number } | null;
  excess_significance: Significance | null;
  excess_over_drift_pct: number | null;
  variants_tested: number;
  expectation_error_days: { mean: number | null; median: number | null; within_2_days: number | null };
  skipped: Record<string, number>;
  caveats: Caveat[];
};

export type Params = {
  enter_days_before: number;
  exit_days_before: number;
  start: string;
  end: string;
  spread_bps: number;
  commission_bps: number;
};

export function useRunBacktest() {
  return useMutation<BacktestResult, Error, Params>({
    mutationFn: async (params) => {
      const response = await fetch(`${API_BASE_URL}/backtest/pre-earnings`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(params),
      });
      if (!response.ok) throw new Error((await response.json()).detail ?? "backtest failed");
      return response.json();
    },
  });
}

export type SweepVariant = {
  enter_days_before: number;
  exit_days_before: number;
  trades: number;
  mean_return_pct: number | null;
  win_rate: number | null;
  drift_pct: number | null;
  excess_over_drift_pct: number | null;
  excess_significance: Significance | null;
};

export type SweepResult = {
  variants_tested: number;
  variants: SweepVariant[];
  best: SweepVariant | null;
  verdict: {
    negative_variants: number;
    total_variants: number;
    mean_excess_pct: number | null;
    best_inside_noise: boolean | null;
    coherent: boolean;
  };
};

export function useRunSweep() {
  return useMutation<SweepResult, Error, { enter_days: number[]; exit_days: number[]; start: string; end: string }>({
    mutationFn: async (body) => {
      const response = await fetch(`${API_BASE_URL}/backtest/pre-earnings/sweep`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify(body),
      });
      if (!response.ok) throw new Error((await response.json()).detail ?? "sweep failed");
      return response.json();
    },
  });
}

export type EarningsOut = {
  ticker: string;
  as_of: string;
  next_report_date: string | null;
  next_is_estimated: boolean | null;
  days_to_earnings: number | null;
  history: {
    period_end: string;
    report_date: string | null;
    is_estimated: boolean;
    before_after_market: string | null;
    eps_estimate: number | null;
    eps_actual: number | null;
    surprise_percent: number | null;
    observed_on: string;
  }[];
};

export function useEarnings(ticker: string | undefined) {
  return useQuery<EarningsOut>({
    queryKey: ["earnings", ticker],
    enabled: Boolean(ticker),
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/earnings/${ticker}`);
      if (!response.ok) throw new Error("no earnings on file");
      return response.json();
    },
  });
}
