import { useQuery } from "@tanstack/react-query";
import { API_BASE_URL } from "./config";

export type IGAccount = {
  account_id: string;
  type: string;
  regime: string;
  label: string | null;
  currency: string | null;
  balance: number | null;
  margin_used: number | null;
  available: number | null;
  profit_loss: number | null;
};

export type IGPositionRow = {
  deal_id: string;
  epic: string;
  ticker: string | null;
  name: string | null;
  kind: string;
  direction: string;
  size: number;
  open_level: number | null;
  current_level: number | null;
  currency: string | null;
  stop_level: number | null;
  notional: number | null;
  opened_at: string | null;
  needs_mapping: boolean;
  funding_paid_to_date: number | null;
  funding_per_month: number | null;
  funding_projected: number | null;
  funding_is_estimate: boolean;
};

export type IGOption = {
  deal_id: string;
  underlying: string | null;
  right: string;
  strike: number;
  expiry: string;
  days_left: number;
  contracts: number;
  multiplier: number;
  direction: string;
  currency: string;
  mark: number | null;
  spot: number | null;
  position_value: number | null;
  premium_paid: number | null;
  breakeven_line: string;
  decay_line: string;
  leverage_line: string;
  max_loss_line: string;
  probability_line: string;
  earnings_warning: string | null;
  breakeven_price: number | null;
  move_required_pct: number | null;
  theta_per_day: number | null;
  exposure: number | null;
  delta: number | null;
  implied_volatility: number | null;
  iv_estimated: boolean;
  probability: number | null;
  warnings: string[];
};

export type AccountBook = {
  account: IGAccount;
  positions: IGPositionRow[];
  options: IGOption[];
  total_notional: number;
  margin_used: number | null;
  exposure_to_margin: number | null;
  funding_paid_this_year: number | null;
  cost_of_ownership_note: string;
};

export type IGBook = {
  accounts: AccountBook[];
  blended_total_note: string;
  unmapped_epics: number;
  pending_reconciliation: number;
  last_sync: string | null;
};

export function useIGBook(horizonDays = 105) {
  return useQuery<IGBook>({
    queryKey: ["ig-book", horizonDays],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/ig/book?horizon_days=${horizonDays}`);
      if (!response.ok) throw new Error("could not load your IG accounts");
      return response.json();
    },
  });
}

export type Reconciliation = {
  pending: {
    id: number;
    account_id: string;
    kind: string;
    deal_id: string | null;
    epic: string | null;
    ticker: string | null;
    detail: Record<string, unknown>;
    confidence: number | null;
  }[];
  counts: Record<string, number>;
  note: string;
};

export function useReconciliation() {
  return useQuery<Reconciliation>({
    queryKey: ["ig-reconciliation"],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/ig/reconciliation`);
      if (!response.ok) throw new Error("could not load the reconciliation");
      return response.json();
    },
  });
}

export type PositionRow = {
  deal_id: string;
  account_id: string;
  account_label: string | null;
  regime: string;
  kind: string;
  ticker: string | null;
  name: string;
  sector: string | null;
  direction: string;
  size: number;
  currency: string | null;
  opened_at: string | null;
  closed_at: string | null;
  days_held: number | null;
  open_level: number | null;
  current_level: number | null;
  notional: number | null;
  market_value: number | null;
  delta_exposure: number | null;
  at_risk: number | null;
  at_risk_basis: string;
  unrealised_pl: number | null;
  realised_pl: number | null;
  funding_paid: number | null;
  right: string | null;
  strike: number | null;
  expiry: string | null;
  days_to_expiry: number | null;
  breakeven_price: number | null;
  move_required_pct: number | null;
  theta_per_day: number | null;
  probability: number | null;
  has_earnings_warning: boolean;
  next_earnings: string | null;
  days_to_earnings: number | null;
};

export type PositionTotals = {
  positions: number;
  notional: number;
  market_value: number;
  delta_exposure: number;
  at_risk: number;
  at_risk_known: number;
  at_risk_unknown: number;
  unrealised_pl: number;
  realised_pl: number;
  funding_paid: number;
  currency: string;
};

export type PositionsOut = {
  open: PositionRow[];
  closed: PositionRow[];
  totals_open: PositionTotals;
  totals_closed: PositionTotals;
  by_account: Record<string, PositionTotals>;
  totals_by_currency: Record<string, PositionTotals>;
  sectors: string[];
  kinds: string[];
};

export function usePositions() {
  return useQuery<PositionsOut>({
    queryKey: ["ig-positions"],
    queryFn: async () => {
      const response = await fetch(`${API_BASE_URL}/ig/positions`);
      if (!response.ok) throw new Error("could not load your positions");
      return response.json();
    },
  });
}
