import { describe, it, expect, beforeEach, afterEach, vi } from 'vitest';
import {
  ApiError,
  getApiBaseUrl,
  request,
  getCandidateDates,
  getToday,
  getCandidates,
  getStock,
  getStrategyResults,
  getQualifiedResults,
} from './client';
import type {
  Candidate,
  CandidatesResponse,
  QualifiedScreenResult,
  SnapshotDatesResponse,
  StockProfileResponse,
  StrategyScreenResult,
  TodayOverview,
} from './types';

describe('API Client', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  afterEach(() => {
    vi.restoreAllMocks();
  });

  describe('ApiError', () => {
    it('instantiates with status and message', () => {
      const error = new ApiError(404, 'Not Found');
      expect(error).toBeInstanceOf(Error);
      expect(error).toBeInstanceOf(ApiError);
      expect(error.status).toBe(404);
      expect(error.message).toBe('Not Found');
      expect(error.name).toBe('ApiError');
    });
  });

  describe('getApiBaseUrl', () => {
    it('defaults to http://127.0.0.1:8000 when VITE_API_BASE_URL is not set', () => {
      expect(getApiBaseUrl()).toBe('http://127.0.0.1:8000');
    });
  });

  describe('request helper', () => {
    it('returns parsed JSON for successful 200 response', async () => {
      const mockData = { status: 'ok' };
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockData,
      } as Response);

      const result = await request<typeof mockData>('/health');
      expect(result).toEqual(mockData);
      expect(globalThis.fetch).toHaveBeenCalledWith('http://127.0.0.1:8000/health');
    });

    it('filters out undefined and null query params', async () => {
      const mockData = { ok: true };
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockData,
      } as Response);

      await request('/test', {
        active: true,
        count: 5,
        ignoredNull: null,
        ignoredUndefined: undefined,
      });

      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:8000/test?active=true&count=5'
      );
    });

    it('throws ApiError with detail message on 404 response', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 404,
        statusText: 'Not Found',
        json: async () => ({ detail: 'snapshot not found for date 2026-09-04' }),
      } as Response);

      await expect(request('/candidates', { as_of: '2026-09-04' })).rejects.toThrow(ApiError);

      try {
        await request('/candidates', { as_of: '2026-09-04' });
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        const apiErr = err as ApiError;
        expect(apiErr.status).toBe(404);
        expect(apiErr.message).toBe('snapshot not found for date 2026-09-04');
      }
    });

    it('formats array detail from FastAPI 422 validation errors', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 422,
        statusText: 'Unprocessable Entity',
        json: async () => ({
          detail: [
            {
              loc: ['query', 'as_of'],
              msg: 'Input should be a valid date',
              type: 'date_from_datetime_parsing',
            },
          ],
        }),
      } as unknown as Response);

      try {
        await request('/today', { as_of: 'invalid-date' });
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        const apiErr = err as ApiError;
        expect(apiErr.status).toBe(422);
        expect(apiErr.message).toContain('Input should be a valid date');
      }
    });

    it('throws ApiError with statusText when response has no detail json on 500 response', async () => {
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: false,
        status: 500,
        statusText: 'Internal Server Error',
        json: async () => {
          throw new Error('Not JSON');
        },
      } as unknown as Response);

      try {
        await request('/health');
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        const apiErr = err as ApiError;
        expect(apiErr.status).toBe(500);
        expect(apiErr.message).toBe('Internal Server Error');
      }
    });

    it('throws human-readable ApiError with status 0 on network error', async () => {
      globalThis.fetch = vi.fn().mockRejectedValue(new TypeError('Failed to fetch'));

      try {
        await request('/health');
      } catch (err) {
        expect(err).toBeInstanceOf(ApiError);
        const apiErr = err as ApiError;
        expect(apiErr.status).toBe(0);
        expect(apiErr.message).toBe('网络请求失败，请检查后端服务是否启动');
      }
    });
  });

  describe('getCandidateDates', () => {
    it('requests /snapshot-dates with kind=CANDIDATE and returns dates response', async () => {
      const mockResponse: SnapshotDatesResponse = {
        kind: 'CANDIDATE',
        dates: ['2026-09-17', '2026-09-19'],
        latest: '2026-09-19',
      };
      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockResponse,
      } as Response);

      const result = await getCandidateDates();
      expect(result).toEqual(mockResponse);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:8000/snapshot-dates?kind=CANDIDATE'
      );
    });
  });

  describe('getToday', () => {
    it('requests /today with as_of and top params and returns TodayOverview', async () => {
      const mockCandidate: Candidate = {
        symbol: '601336.SH',
        primary_strategy_id: 'value',
        primary_score: 95,
        rank_percentile: 0.98,
        qualified_strategies: ['value'],
        market_validation: 'NEUTRAL',
        signal: 'VALUE_CONTRARIAN',
        next_action: 'WATCH',
        confidence: 0.9,
        reasons: ['qualified for value'],
        risks: [],
        rank: 1,
      };
      const mockOverview: TodayOverview = {
        as_of: '2026-09-04',
        market_regime: 'BULL',
        candidate_count: 1,
        confirmed_count: 0,
        neutral_count: 1,
        strategy_distribution: { value: 1 },
        validation_distribution: { NEUTRAL: 1 },
        signal_distribution: { VALUE_CONTRARIAN: 1 },
        top_candidates: [mockCandidate],
      };

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockOverview,
      } as Response);

      const result = await getToday('2026-09-04', 10);
      expect(result).toEqual(mockOverview);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:8000/today?as_of=2026-09-04&top=10'
      );
    });

    it('normalizes raw FastAPI response counts into TodayOverview distributions', async () => {
      const rawBackendToday = {
        as_of: '2026-09-04T15:00:00+08:00',
        candidate_count: 2,
        market_regime: 'BULL',
        counts_by_primary_strategy: { value: 1, growth: 1 },
        counts_by_market_validation: { CONFIRMED: 1, NEUTRAL: 1 },
        counts_by_signal: { BREAKOUT: 1, VALUE_CONTRARIAN: 1 },
        top_candidates: [
          {
            rank: 1,
            symbol: '601336.SH',
            primary_strategy_id: 'value',
            qualified_strategy_ids: ['value'],
            best_rank_percentile: 0.98,
            market_validation: 'NEUTRAL',
            signal: 'VALUE_CONTRARIAN',
            next_action: 'WATCH',
            reasons: ['qualified for value'],
            risks: [],
          },
        ],
      };

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => rawBackendToday,
      } as Response);

      const result = await getToday('2026-09-04');
      expect(result.confirmed_count).toBe(1);
      expect(result.neutral_count).toBe(1);
      expect(result.strategy_distribution).toEqual({ value: 1, growth: 1 });
      expect(result.validation_distribution).toEqual({ CONFIRMED: 1, NEUTRAL: 1 });
      expect(result.signal_distribution).toEqual({ BREAKOUT: 1, VALUE_CONTRARIAN: 1 });
      expect(result.top_candidates[0]?.symbol).toBe('601336.SH');
      expect(result.top_candidates[0]?.rank_percentile).toBe(0.98);
      expect(result.top_candidates[0]?.qualified_strategies).toEqual(['value']);
    });
  });

  describe('getCandidates', () => {
    it('requests /candidates with as_of param and returns CandidatesResponse', async () => {
      const mockCandidate: Candidate = {
        symbol: '600000.SH',
        primary_strategy_id: 'growth',
        primary_score: 90,
        rank_percentile: 0.98,
        qualified_strategies: ['growth'],
        market_validation: 'CONFIRMED',
        signal: 'BREAKOUT',
        next_action: 'TRACK_SIGNAL',
        confidence: 1.0,
        reasons: ['strong growth'],
        risks: [],
        rank: 1,
      };
      const mockResponse: CandidatesResponse = {
        as_of: '2026-09-04',
        records: [mockCandidate],
      };

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockResponse,
      } as Response);

      const result = await getCandidates('2026-09-04');
      expect(result).toEqual(mockResponse);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:8000/candidates?as_of=2026-09-04'
      );
    });
  });

  describe('getStock', () => {
    it('requests /stocks/:symbol with as_of param and returns StockProfileResponse', async () => {
      const mockProfile: StockProfileResponse = {
        symbol: '600519.SH',
        as_of: '2026-09-04',
        universe: {
          included: true,
          rules_passed: ['liquidity'],
          exclusion_rules: [],
        },
        factors: [
          {
            factor: 'pe_ttm',
            status: 'VALUE',
            raw_value: 28.5,
            unit: 'x',
            as_of: '2026-09-04',
          },
        ],
        strategies: [
          {
            strategy_id: 'quality',
            score: 92,
            eligible: true,
            rank_percentile: 0.99,
            reasons: ['high roe'],
            risks: [],
          },
        ],
        candidate_status: 'published_selected',
        candidate: {
          symbol: '600519.SH',
          primary_strategy_id: 'quality',
          primary_score: 92,
          rank_percentile: 0.99,
          qualified_strategies: ['quality'],
          market_validation: 'CONFIRMED',
          signal: 'TREND_FOLLOWING',
          next_action: 'TRACK_SIGNAL',
          confidence: 0.95,
          reasons: ['high roe'],
          risks: [],
          rank: 1,
        },
        watchlist_status: 'DISCOVERED',
      };

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockProfile,
      } as Response);

      const result = await getStock('600519.SH', '2026-09-04');
      expect(result).toEqual(mockProfile);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:8000/stocks/600519.SH?as_of=2026-09-04'
      );
    });

    it('normalizes published candidate status to published_selected and extracts watchlist state', async () => {
      const rawBackendProfile = {
        symbol: '600000.SH',
        as_of: '2026-09-04',
        universe: { included: true, exclusion_rules: [] },
        factors: [],
        strategies: [],
        candidate_status: 'published',
        candidate: {
          symbol: '600000.SH',
          primary_strategy_id: 'growth',
          next_action: 'TRACK_SIGNAL',
          strategy_results: [{ score: 90, rank_percentile: 0.95 }],
          strategy_qualifications: [{ strategy_id: 'growth' }],
          reasons: ['strong'],
          risks: [],
        },
        watchlist: { symbol: '600000.SH', state: 'DISCOVERED' },
      };

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => rawBackendProfile,
      } as Response);

      const result = await getStock('600000.SH', '2026-09-04');
      expect(result.candidate_status).toBe('published_selected');
      expect(result.watchlist_status).toBe('DISCOVERED');
      expect(result.candidate?.primary_score).toBe(90);
      expect(result.candidate?.qualified_strategies).toEqual(['growth']);
    });
  });

  describe('getStrategyResults', () => {
    it('requests /strategies/:strategyId/results with as_of and limit params', async () => {
      const mockResult: StrategyScreenResult = {
        query: {
          strategy_id: 'growth',
          as_of: '2026-09-04',
          limit: 20,
        },
        coverage: {
          covered_count: 50,
          total_count: 100,
          coverage_ratio: 0.5,
        },
        results: [
          {
            symbol: '600000.SH',
            score: 88,
            rank_percentile: 0.95,
            confidence: 0.9,
            reasons: ['strong momentum'],
            risks: [],
          },
        ],
      };

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockResult,
      } as Response);

      const result = await getStrategyResults('growth', '2026-09-04', 20);
      expect(result).toEqual(mockResult);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:8000/strategies/growth/results?as_of=2026-09-04&limit=20'
      );
    });

    it('normalizes raw FastAPI strategy screen response', async () => {
      const rawBackendStrategy = {
        strategy_id: 'growth',
        coverage: {
          strategy_id: 'growth',
          total_count: 10,
          eligible_count: 5,
          scored_count: 5,
          ranked_count: 5,
        },
        items: [
          {
            rank: 1,
            symbol: '600000.SH',
            strategy_id: 'growth',
            strategy_version: 'v1',
            score: 90.0,
            rank_percentile: 0.98,
            confidence: 1.0,
            eligible: true,
            reasons: ['strong growth'],
            risks: [],
          },
        ],
      };

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => rawBackendStrategy,
      } as Response);

      const result = await getStrategyResults('growth', '2026-09-04', 20);
      expect(result.coverage.total_count).toBe(10);
      expect(result.coverage.covered_count).toBe(5);
      expect(result.coverage.coverage_ratio).toBe(0.5);
      expect(result.results[0]?.symbol).toBe('600000.SH');
      expect(result.results[0]?.score).toBe(90.0);
    });
  });

  describe('getQualifiedResults', () => {
    it('requests /qualifications/:strategyId/results with as_of and limit params', async () => {
      const mockResult: QualifiedScreenResult = {
        strategy_id: 'growth',
        as_of: '2026-09-04',
        qualified_count: 10,
        coverage_count: 40,
        items: [
          {
            symbol: '600000.SH',
            qualified: true,
            percentile_pass: true,
            absolute_pass: true,
            rank_percentile: 0.95,
            failure_reasons: [],
          },
        ],
      };

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => mockResult,
      } as Response);

      const result = await getQualifiedResults('growth', '2026-09-04', 20);
      expect(result).toEqual(mockResult);
      expect(globalThis.fetch).toHaveBeenCalledWith(
        'http://127.0.0.1:8000/qualifications/growth/results?as_of=2026-09-04&limit=20'
      );
    });

    it('normalizes raw FastAPI qualification screen response', async () => {
      const rawBackendQualified = {
        strategy_id: 'growth',
        coverage: {
          strategy_id: 'growth',
          strategy_eligible_count: 20,
          ranked_count: 18,
          percentile_pass_count: 8,
          absolute_pass_count: 6,
          qualified_count: 5,
        },
        items: [
          {
            rank: 1,
            symbol: '600000.SH',
            strategy_id: 'growth',
            strategy_version: 'v1',
            qualification_version: 'v1',
            score: 90.0,
            rank_percentile: 0.98,
            reasons: ['strong growth'],
            risks: [],
          },
        ],
      };

      globalThis.fetch = vi.fn().mockResolvedValue({
        ok: true,
        status: 200,
        json: async () => rawBackendQualified,
      } as Response);

      const result = await getQualifiedResults('growth', '2026-09-04', 20);
      expect(result.qualified_count).toBe(5);
      expect(result.coverage_count).toBe(20);
      expect(result.items[0]?.symbol).toBe('600000.SH');
      expect(result.items[0]?.qualified).toBe(true);
      expect(result.items[0]?.rank_percentile).toBe(0.98);
    });
  });
});
