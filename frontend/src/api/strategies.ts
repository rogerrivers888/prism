import { useMutation, useQuery, useQueryClient } from "@tanstack/react-query";
import { API_BASE_URL } from "./config";

export type LeaderboardRow = {
  strategy_id: string;
  name: string;
  authority: string;
  citation: string | null;
  horizon: string;
  status: string;
  stage: string;
  registered_at: string;
  started: string | null;
  trades: number;
  total_return_pct: number | null;
  expectancy_r: number | null;
  mean_trade_return_pct: number | null;
  max_drawdown_pct: number | null;
  cost_drag_pct: number | null;
  track_record_verdict: string;
  backtest_mean_trade_pct: number | null;
  backtest_excess_over_drift_pct: number | null;
  deflated_survives: boolean | null;
  family_size: number | null;
  duplicate_of: string | null;
  decay_note: string;
};

export type Leaderboard = {
  boards: Record<string, LeaderboardRow[]>;
  ranked_on: string;
};

export type StrategyHolding = {
  ticker: string;
  name: string;
  quantity: number;
  avg_cost: number;
  opened_at: string;
  last_price: number | null;
  unrealised_pct: number | null;
  rule_fired: string;
  metric_values: Record<string, number>;
};

export type StrategyTrade = {
  ticker: string;
  side: string;
  quantity: number;
  price: number;
  spread_cost: number;
  commission: number;
  signal_date: string;
  fill_date: string;
  rule_fired: string;
  metric_values: Record<string, number>;
};

export type StrategyDetail = {
  strategy_id: string;
  name: string;
  hypothesis: string;
  authority: string;
  citation: string | null;
  horizon: string;
  status: string;
  stage: string;
  registered_at: string;
  expected_trade_frequency: string;
  expected_holding_period: string;
  predicted_performance: string;
  encoding_deviations: string | null;
  decay_note: string;
  parent_strategy_id: string | null;
  duplicate_of: string | null;
  duplicate_correlation: number | null;
  duplicate_override_note: string | null;
  rules_json: unknown;
  rules_plain: string[];
  holdings: StrategyHolding[];
  trades: StrategyTrade[];
  equity_curve: [string, number][];
  paper: Record<string, unknown>;
  backtest: Record<string, any> | null;
  decay_warning: string | null;
};

export type TradesToday = {
  date: string | null;
  note?: string;
  trades: {
    strategy_id: string;
    strategy: string;
    ticker: string;
    side: string;
    quantity: number;
    price: number;
    costs: number;
    signal_date: string;
    rule_fired: string;
    metric_values: Record<string, number>;
  }[];
};

export const HORIZON_LABEL: Record<string, string> = {
  short: "Short horizon — weeks",
  medium: "Medium horizon — months",
  long: "Long horizon — quarters and beyond",
};

export function useLeaderboard() {
  return useQuery<Leaderboard>({
    queryKey: ["strategies"],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/strategies`);
      if (!response.ok) throw new Error("could not load strategies");
      return response.json();
    },
  });
}

export function useStrategy(id: string | undefined) {
  return useQuery<StrategyDetail>({
    queryKey: ["strategy", id],
    enabled: Boolean(id),
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/strategies/${id}`);
      if (!response.ok) throw new Error("could not load this strategy");
      return response.json();
    },
  });
}

export function useTradesToday() {
  return useQuery<TradesToday>({
    queryKey: ["trades-today"],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/strategies/trades-today`);
      if (!response.ok) throw new Error("could not load today's trades");
      return response.json();
    },
  });
}

export function usePromote() {
  const queryClient = useQueryClient();
  return useMutation<unknown, Error, { id: string; stage: string; note?: string }>({
    mutationFn: async ({ id, stage, note }) => {
      const response = await fetch(`${API_BASE_URL}/strategies/${id}/promote`, {
        method: "POST",
        headers: { "content-type": "application/json" },
        body: JSON.stringify({ stage, note }),
      });
      const body = await response.json();
      if (!response.ok) throw new Error(body.detail ?? "promotion refused");
      return body;
    },
    onSuccess: (_data, variables) => {
      queryClient.invalidateQueries({ queryKey: ["strategies"] });
      queryClient.invalidateQueries({ queryKey: ["strategy", variables.id] });
    },
  });
}
