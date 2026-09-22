/**
 * A-Stock Lens 领域与 API 响应数据契约。
 * 对应 FastAPI 后端暴露的只读端点。
 */

export type MarketRegime = 'BULL' | 'BEAR' | 'SHOCK';

export type MarketValidation = 'CONFIRMED' | 'CONTRADICTED' | 'NEUTRAL';

export type Signal =
  | 'BREAKOUT'
  | 'BREAKDOWN'
  | 'MOMENTUM_ACCELERATION'
  | 'OVERSOLD_BOUNCE'
  | 'VALUE_CONTRARIAN'
  | 'DIVIDEND_DEFENSIVE'
  | 'TREND_FOLLOWING'
  | 'NEUTRAL';

export type NextAction = 'TRACK_SIGNAL' | 'DEEP_RESEARCH' | 'WATCH' | 'DISCOVERED';

export interface SnapshotDatesResponse {
  kind: string;
  dates: string[];
  latest: string | null;
}

export interface Candidate {
  symbol: string;
  primary_strategy_id: string;
  primary_score: number | null;
  rank_percentile: number | null;
  qualified_strategies: string[];
  market_validation: MarketValidation;
  signal: Signal;
  next_action: NextAction;
  confidence?: number | null;
  reasons: string[];
  risks: string[];
  rank?: number;
}

export interface CandidatesResponse {
  as_of: string;
  records: Candidate[];
}

export interface TodayOverview {
  as_of: string;
  market_regime: MarketRegime | null;
  candidate_count: number;
  confirmed_count: number;
  neutral_count: number;
  strategy_distribution: Record<string, number>;
  validation_distribution: Record<string, number>;
  signal_distribution: Record<string, number>;
  top_candidates: Candidate[];
}

export interface StockProfileUniverse {
  included: boolean;
  rules_passed: string[];
  exclusion_rules: string[];
}

export interface StockProfileFactor {
  factor: string;
  status: string;
  raw_value: number | null;
  unit?: string | null;
  as_of: string;
}

export interface StockProfileStrategy {
  strategy_id: string;
  score: number | null;
  eligible: boolean;
  rank_percentile: number | null;
  reasons: string[];
  risks: string[];
}

export type CandidateStatus = 'published_selected' | 'not_selected' | 'not_published';

export interface StockProfileResponse {
  symbol: string;
  as_of: string;
  universe: StockProfileUniverse;
  factors: StockProfileFactor[];
  strategies: StockProfileStrategy[];
  candidate_status: CandidateStatus;
  candidate: Candidate | null;
  watchlist_status: string | null;
}

export interface StrategyScreenResult {
  query: {
    strategy_id: string;
    as_of: string;
    limit: number;
  };
  coverage: {
    covered_count: number;
    total_count: number;
    coverage_ratio: number;
  };
  results: Array<{
    symbol: string;
    score: number | null;
    rank_percentile: number | null;
    confidence?: number | null;
    reasons: string[];
    risks: string[];
  }>;
}

export interface QualifiedScreenItem {
  symbol: string;
  qualified: boolean;
  percentile_pass: boolean;
  absolute_pass: boolean;
  rank_percentile: number | null;
  failure_reasons: string[];
}

export interface QualifiedScreenResult {
  strategy_id: string;
  as_of: string;
  qualified_count: number;
  coverage_count: number;
  items: QualifiedScreenItem[];
}
