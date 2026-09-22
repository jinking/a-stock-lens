import { beforeEach, describe, expect, it, vi } from 'vitest';
import { render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import * as client from '../api/client';
import { DateContext, type DateContextValue } from '../app/DateContext';
import type { StockProfileResponse } from '../api/types';
import { StockProfilePage } from './StockProfilePage';

const context: DateContextValue = {
  dates: ['2026-09-21'],
  asOf: '2026-09-21',
  setAsOf: vi.fn(),
  loading: false,
  error: null,
  refreshDates: vi.fn(),
};

const profile: StockProfileResponse = {
  symbol: '600519.SH',
  as_of: '2026-09-21',
  universe: { included: true, rules_passed: ['liquidity'], exclusion_rules: [] },
  factors: [
    { factor: 'roe', status: 'NULL', raw_value: null, unit: '%', as_of: '2026-09-21' },
    { factor: 'pe_ttm', status: 'VALUE', raw_value: 28, unit: 'x', as_of: '2026-09-21' },
    { factor: 'revenue_growth', status: 'STALE', raw_value: null, unit: '%', as_of: '2026-09-21' },
    { factor: 'dividend', status: 'NOT_APPLICABLE', raw_value: null, unit: null, as_of: '2026-09-21' },
  ],
  strategies: [
    {
      strategy_id: 'quality', score: 90, eligible: true, rank_percentile: 0.98,
      reasons: ['质量稳定'], risks: [],
    },
  ],
  candidate_status: 'published_selected',
  candidate: {
    symbol: '600519.SH', primary_strategy_id: 'quality', primary_score: 90,
    rank_percentile: 0.98, qualified_strategies: ['quality'], market_validation: 'CONFIRMED',
    signal: 'TREND_FOLLOWING', next_action: 'DEEP_RESEARCH', reasons: ['质量稳定'],
    risks: ['TREND_WEAKEN'], rank: 1,
    lineage: {
      universe_snapshot: 'UNIVERSE:2026-09-21', factor_version: 'factor-v2',
      strategy_version: 'strategy-v3', qualification_version: 'qualification-v1',
      regime_version: 'regime-v1', market_validation_version: 'validation-v2',
      signal_version: 'signal-v1', candidate_policy_version: 'policy-v2',
    },
  },
  watchlist_status: 'WATCH',
};

function renderProfile(dateContext: DateContextValue = context) {
  return render(
    <DateContext.Provider value={dateContext}>
      <MemoryRouter initialEntries={['/stocks/600519.SH']}>
        <Routes><Route path="/stocks/:symbol" element={<StockProfilePage />} /></Routes>
      </MemoryRouter>
    </DateContext.Provider>
  );
}

describe('StockProfilePage', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('shows candidate thesis, status, reasons, risks, factors, lineage, and watchlist state', async () => {
    vi.spyOn(client, 'getStock').mockResolvedValue(profile);
    renderProfile();
    expect(await screen.findByText('600519.SH')).toBeInTheDocument();
    expect(screen.getByText('DEEP_RESEARCH')).toBeInTheDocument();
    expect(screen.getAllByText('质量稳定')).toHaveLength(2);
    expect(screen.getByText('TREND_WEAKEN')).toBeInTheDocument();
    expect(screen.getByText('WATCH')).toBeInTheDocument();
    expect(screen.getByText('factor-v2')).toBeInTheDocument();
    expect(screen.getByText('policy-v2')).toBeInTheDocument();
  });

  it('preserves missing factor statuses without rendering them as zero', async () => {
    vi.spyOn(client, 'getStock').mockResolvedValue(profile);
    renderProfile();
    await screen.findByText('roe');
    expect(screen.getByText('NULL')).toBeInTheDocument();
    expect(screen.getByText('STALE')).toBeInTheDocument();
    expect(screen.getByText('NOT_APPLICABLE')).toBeInTheDocument();
    expect(screen.getAllByText('—').length).toBeGreaterThan(0);
    expect(screen.queryByText('0')).not.toBeInTheDocument();
  });

  it('distinguishes a published date where the stock was not selected', async () => {
    vi.spyOn(client, 'getStock').mockResolvedValue({ ...profile, candidate: null, candidate_status: 'not_selected' });
    renderProfile();
    expect(await screen.findAllByText('已发布候选池，但该股票未入选')).toHaveLength(2);
  });

  it('distinguishes a date without a published candidate snapshot', async () => {
    vi.spyOn(client, 'getStock').mockResolvedValue({ ...profile, candidate: null, candidate_status: 'not_published' });
    renderProfile();
    expect(await screen.findAllByText('该日期未发布 Candidate Snapshot')).toHaveLength(2);
  });

  it('offers retry when the profile API fails', async () => {
    vi.spyOn(client, 'getStock').mockRejectedValueOnce(new Error('service unavailable'))
      .mockResolvedValueOnce(profile);
    renderProfile();
    expect(await screen.findByText('service unavailable')).toBeInTheDocument();
    screen.getByRole('button', { name: '重试' }).click();
    await waitFor(() => expect(screen.getByText('WATCH')).toBeInTheDocument());
  });

  it('does not let an older date request overwrite the currently selected date', async () => {
    let resolveOldRequest!: (value: StockProfileResponse) => void;
    const oldRequest = new Promise<StockProfileResponse>((resolve) => { resolveOldRequest = resolve; });
    const newProfile = { ...profile, as_of: '2026-09-22', watchlist_status: 'DISCOVERED' };
    vi.spyOn(client, 'getStock').mockImplementationOnce(() => oldRequest).mockResolvedValueOnce(newProfile);
    const view = renderProfile();
    view.rerender(
      <DateContext.Provider value={{ ...context, asOf: '2026-09-22' }}>
        <MemoryRouter initialEntries={['/stocks/600519.SH']}>
          <Routes><Route path="/stocks/:symbol" element={<StockProfilePage />} /></Routes>
        </MemoryRouter>
      </DateContext.Provider>
    );
    expect(await screen.findByText('DISCOVERED')).toBeInTheDocument();
    resolveOldRequest(profile);
    await waitFor(() => expect(screen.getByText('DISCOVERED')).toBeInTheDocument());
    expect(screen.queryByText('WATCH')).not.toBeInTheDocument();
  });
});
