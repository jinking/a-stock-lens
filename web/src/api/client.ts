import type {
  Candidate,
  CandidateStatus,
  CandidatesResponse,
  QualifiedScreenResult,
  SnapshotDatesResponse,
  StockProfileResponse,
  StrategyScreenResult,
  TodayOverview,
} from './types';

/**
 * 结构化 API 错误类，包含 HTTP 状态码与中文/原始错误信息。
 */
export class ApiError extends Error {
  status: number;

  constructor(status: number, message: string) {
    super(message);
    this.name = 'ApiError';
    this.status = status;
    Object.setPrototypeOf(this, ApiError.prototype);
  }
}

const DEFAULT_API_BASE_URL = 'http://127.0.0.1:8000';

/**
 * 读取当前环境配置的后端 API 根地址。
 */
export function getApiBaseUrl(): string {
  const metaEnv =
    typeof import.meta !== 'undefined'
      ? (import.meta as unknown as { env?: Record<string, string | undefined> }).env
      : undefined;
  return metaEnv?.VITE_API_BASE_URL || DEFAULT_API_BASE_URL;
}

/**
 * 全局共享的 HTTP 请求封装函数。
 * 禁止页面组件直接调用裸 fetch()。
 */
export async function request<T>(
  endpoint: string,
  params?: Record<string, string | number | boolean | null | undefined>
): Promise<T> {
  const baseUrl = getApiBaseUrl().replace(/\/+$/, '');
  const cleanEndpoint = endpoint.startsWith('/') ? endpoint : `/${endpoint}`;
  const url = new URL(`${baseUrl}${cleanEndpoint}`);

  if (params) {
    for (const [key, value] of Object.entries(params)) {
      if (value !== undefined && value !== null) {
        url.searchParams.set(key, String(value));
      }
    }
  }

  let response: Response;
  try {
    response = await fetch(url.toString());
  } catch (error) {
    if (error instanceof ApiError) {
      throw error;
    }
    throw new ApiError(0, '网络请求失败，请检查后端服务是否启动');
  }

  if (!response.ok) {
    let errorMessage = response.statusText || `HTTP ${response.status}`;
    try {
      const body = await response.json();
      if (body && typeof body === 'object') {
        if (typeof body.detail === 'string') {
          errorMessage = body.detail;
        } else if (Array.isArray(body.detail)) {
          errorMessage = body.detail
            .map((d: unknown) =>
              typeof d === 'object' && d !== null && 'msg' in d
                ? String((d as { msg: unknown }).msg)
                : JSON.stringify(d)
            )
            .join('; ');
        } else if (typeof body.message === 'string') {
          errorMessage = body.message;
        }
      }
    } catch {
      // 非 JSON 格式错误主体直接回退至 statusText
    }
    throw new ApiError(response.status, errorMessage);
  }

  return (await response.json()) as T;
}

/**
 * 标准化候选人记录结构，确保无论后端原始格式还是客户端契约均能平滑兼容。
 */
function normalizeCandidate(raw: any): Candidate {
  return {
    symbol: raw.symbol,
    primary_strategy_id: raw.primary_strategy_id ?? '',
    primary_score:
      raw.primary_score !== undefined
        ? raw.primary_score
        : (raw.strategy_results?.[0]?.score ?? null),
    rank_percentile:
      raw.rank_percentile !== undefined
        ? raw.rank_percentile
        : raw.best_rank_percentile !== undefined
          ? raw.best_rank_percentile
          : (raw.strategy_results?.[0]?.rank_percentile ?? null),
    qualified_strategies:
      raw.qualified_strategies ??
      raw.qualified_strategy_ids ??
      (raw.strategy_qualifications?.map((q: any) => q.strategy_id) ?? []),
    market_validation: raw.market_validation ?? 'NEUTRAL',
    signal: raw.signal ?? 'NEUTRAL',
    next_action: raw.next_action ?? 'DISCOVERED',
    confidence: raw.confidence !== undefined ? raw.confidence : null,
    reasons: raw.reasons ?? [],
    risks: raw.risks ?? [],
    rank: raw.rank,
  };
}

/**
 * 获取 Candidate 快照已有的全部历史日期列表及最新日期。
 */
export async function getCandidateDates(): Promise<SnapshotDatesResponse> {
  return request<SnapshotDatesResponse>('/snapshot-dates', { kind: 'CANDIDATE' });
}

/**
 * 获取指定日期的盘后候选研究概览（Today）。
 */
export async function getToday(asOf: string, top?: number): Promise<TodayOverview> {
  const raw = await request<Record<string, any>>('/today', { as_of: asOf, top });
  const validationDist =
    raw.validation_distribution ?? raw.counts_by_market_validation ?? {};
  const strategyDist =
    raw.strategy_distribution ?? raw.counts_by_primary_strategy ?? {};
  const signalDist =
    raw.signal_distribution ?? raw.counts_by_signal ?? {};

  return {
    as_of: raw.as_of,
    market_regime: raw.market_regime ?? null,
    candidate_count: raw.candidate_count ?? 0,
    confirmed_count: raw.confirmed_count ?? validationDist['CONFIRMED'] ?? 0,
    neutral_count: raw.neutral_count ?? validationDist['NEUTRAL'] ?? 0,
    strategy_distribution: strategyDist,
    validation_distribution: validationDist,
    signal_distribution: signalDist,
    top_candidates: (raw.top_candidates ?? []).map(normalizeCandidate),
  };
}

/**
 * 获取指定日期的正式候选股票池完整列表。
 */
export async function getCandidates(asOf: string): Promise<CandidatesResponse> {
  const raw = await request<{ as_of: string; records: any[] }>('/candidates', {
    as_of: asOf,
  });
  return {
    as_of: raw.as_of,
    records: (raw.records ?? []).map(normalizeCandidate),
  };
}

/**
 * 获取单只标的在指定日期的完整研究画像。
 */
export async function getStock(symbol: string, asOf: string): Promise<StockProfileResponse> {
  const raw = await request<Record<string, any>>(`/stocks/${encodeURIComponent(symbol)}`, {
    as_of: asOf,
  });
  let candidateStatus: CandidateStatus = raw.candidate_status;
  if ((raw.candidate_status as string) === 'published') {
    candidateStatus = 'published_selected';
  }
  return {
    symbol: raw.symbol,
    as_of: raw.as_of,
    universe: {
      included: Boolean(raw.universe?.included),
      rules_passed: raw.universe?.rules_passed ?? [],
      exclusion_rules: raw.universe?.exclusion_rules ?? [],
    },
    factors: raw.factors ?? [],
    strategies: raw.strategies ?? [],
    candidate_status: candidateStatus,
    candidate: raw.candidate ? normalizeCandidate(raw.candidate) : null,
    watchlist_status: raw.watchlist_status ?? (raw.watchlist?.state ?? null),
  };
}

/**
 * 获取指定策略在指定日期的初筛股票列表与覆盖度。
 */
export async function getStrategyResults(
  strategyId: string,
  asOf: string,
  limit?: number
): Promise<StrategyScreenResult> {
  const raw = await request<Record<string, any>>(
    `/strategies/${encodeURIComponent(strategyId)}/results`,
    {
      as_of: asOf,
      limit,
    }
  );
  if (raw.results && raw.query && raw.coverage?.covered_count !== undefined) {
    return raw as StrategyScreenResult;
  }
  const totalCount = raw.coverage?.total_count ?? 0;
  const coveredCount =
    raw.coverage?.covered_count ??
    raw.coverage?.eligible_count ??
    (raw.items?.length ?? 0);
  const coverageRatio =
    raw.coverage?.coverage_ratio ?? (totalCount > 0 ? coveredCount / totalCount : 0);
  const results =
    raw.results ??
    (raw.items ?? []).map((item: any) => ({
      symbol: item.symbol,
      score: item.score ?? null,
      rank_percentile: item.rank_percentile ?? null,
      confidence: item.confidence ?? null,
      reasons: item.reasons ?? [],
      risks: item.risks ?? [],
    }));
  return {
    query: raw.query ?? { strategy_id: strategyId, as_of: asOf, limit: limit ?? 20 },
    coverage: {
      covered_count: coveredCount,
      total_count: totalCount,
      coverage_ratio: coverageRatio,
    },
    results,
  };
}

/**
 * 获取指定策略在指定日期的双门槛合格股票列表与覆盖度。
 */
export async function getQualifiedResults(
  strategyId: string,
  asOf: string,
  limit?: number
): Promise<QualifiedScreenResult> {
  const raw = await request<Record<string, any>>(
    `/qualifications/${encodeURIComponent(strategyId)}/results`,
    {
      as_of: asOf,
      limit,
    }
  );
  if (
    raw.qualified_count !== undefined &&
    raw.coverage_count !== undefined &&
    raw.as_of
  ) {
    return raw as QualifiedScreenResult;
  }
  const qualifiedCount =
    raw.qualified_count ?? raw.coverage?.qualified_count ?? (raw.items?.length ?? 0);
  const coverageCount =
    raw.coverage_count ??
    raw.coverage?.strategy_eligible_count ??
    raw.coverage?.ranked_count ??
    0;
  const items = (raw.items ?? []).map((item: any) => ({
    symbol: item.symbol,
    qualified: item.qualified ?? true,
    percentile_pass: item.percentile_pass ?? true,
    absolute_pass: item.absolute_pass ?? true,
    rank_percentile: item.rank_percentile ?? null,
    failure_reasons: item.failure_reasons ?? [],
  }));
  return {
    strategy_id: raw.strategy_id ?? strategyId,
    as_of: raw.as_of ?? asOf,
    qualified_count: qualifiedCount,
    coverage_count: coverageCount,
    items,
  };
}
