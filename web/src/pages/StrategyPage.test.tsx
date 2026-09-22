import { beforeEach, describe, expect, it, vi } from 'vitest';
import { act, fireEvent, render, screen, waitFor } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { MemoryRouter, Route, Routes, useLocation } from 'react-router-dom';
import * as client from '../api/client';
import { DateContext, type DateContextValue } from '../app/DateContext';
import { StrategyPage } from './StrategyPage';

const context: DateContextValue = {
  dates: ['2026-09-21'], asOf: '2026-09-21', setAsOf: vi.fn(), loading: false,
  error: null, refreshDates: vi.fn(),
};

function renderStrategy() {
  return render(
    <DateContext.Provider value={context}>
      <MemoryRouter initialEntries={['/strategies/growth']}>
        <Routes>
          <Route path="/strategies/:strategyId" element={<StrategyPage />} />
        </Routes>
        <CurrentPath />
      </MemoryRouter>
    </DateContext.Provider>
  );
}

function CurrentPath() {
  return <output data-testid="current-path">{useLocation().pathname}</output>;
}

describe('StrategyPage', () => {
  beforeEach(() => vi.restoreAllMocks());

  it('shows ranking and qualified tabs using their respective API results', async () => {
    vi.spyOn(client, 'getStrategyResults').mockResolvedValue({
      query: { strategy_id: 'growth', as_of: '2026-09-21', limit: 50 },
      coverage: { covered_count: 8, total_count: 10, coverage_ratio: 0.8 },
      results: [{ symbol: '600000.SH', score: 90, rank_percentile: 0.98, confidence: 0.9, reasons: ['成长稳定'], risks: ['波动'] }],
    });
    vi.spyOn(client, 'getQualifiedResults').mockResolvedValue({
      strategy_id: 'growth', as_of: '2026-09-21', qualified_count: 1, coverage_count: 8,
      items: [{ symbol: '600000.SH', qualified: true, percentile_pass: true, absolute_pass: true, rank_percentile: 0.98, failure_reasons: [] }],
      warnings: [],
    });
    renderStrategy();
    expect(await screen.findByText('600000.SH')).toBeInTheDocument();
    expect(screen.getByText('90')).toBeInTheDocument();
    expect(screen.getByText('98.0%')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: '合格池' }));
    expect(await screen.findByText('双门槛合格池')).toBeInTheDocument();
    expect(screen.queryByText('分位门槛')).not.toBeInTheDocument();
    expect(screen.queryByText('绝对质量门槛')).not.toBeInTheDocument();
    expect(client.getQualifiedResults).toHaveBeenCalledWith('growth', '2026-09-21', 50);
  });

  it('surfaces degraded coverage and server qualification warnings', async () => {
    vi.spyOn(client, 'getStrategyResults').mockResolvedValue({
      query: { strategy_id: 'growth', as_of: '2026-09-21', limit: 50 },
      coverage: { covered_count: 0, total_count: 10, coverage_ratio: 0 }, results: [],
    });
    vi.spyOn(client, 'getQualifiedResults').mockResolvedValue({
      strategy_id: 'growth', as_of: '2026-09-21', qualified_count: 0, coverage_count: 0,
      items: [], warnings: ['当前无可用于合格判定的完整覆盖数据'],
    });
    renderStrategy();
    expect(await screen.findByText(/覆盖不足/)).toBeInTheDocument();
    fireEvent.click(screen.getByRole('tab', { name: '合格池' }));
    expect(await screen.findByText('当前无可用于合格判定的完整覆盖数据')).toBeInTheDocument();
  });

  it('offers retry after API failure', async () => {
    vi.spyOn(client, 'getStrategyResults').mockRejectedValueOnce(new Error('strategy unavailable'))
      .mockResolvedValueOnce({
        query: { strategy_id: 'growth', as_of: '2026-09-21', limit: 50 },
        coverage: { covered_count: 0, total_count: 0, coverage_ratio: 0 }, results: [],
      });
    renderStrategy();
    expect(await screen.findByText('strategy unavailable')).toBeInTheDocument();
    fireEvent.click(screen.getByRole('button', { name: '重试' }));
    await waitFor(() => expect(screen.getByText('暂无排名数据')).toBeInTheDocument());
  });

  it('updates the route when a different strategy is selected', async () => {
    vi.spyOn(client, 'getStrategyResults').mockResolvedValue({
      query: { strategy_id: 'growth', as_of: '2026-09-21', limit: 50 },
      coverage: { covered_count: 0, total_count: 0, coverage_ratio: 0 }, results: [],
    });
    renderStrategy();
    fireEvent.change(screen.getByRole('combobox', { name: '选择策略' }), { target: { value: 'quality' } });
    await waitFor(() => expect(screen.getByTestId('current-path')).toHaveTextContent('/strategies/quality'));
  });

  it('does not let an older strategy request overwrite the newly selected strategy', async () => {
    let resolveGrowth!: (value: Awaited<ReturnType<typeof client.getStrategyResults>>) => void;
    const growthRequest = new Promise<Awaited<ReturnType<typeof client.getStrategyResults>>>(resolve => { resolveGrowth = resolve; });
    const qualityResult = {
      query: { strategy_id: 'quality', as_of: '2026-09-21', limit: 50 },
      coverage: { covered_count: 1, total_count: 1, coverage_ratio: 1 },
      results: [{ symbol: '600001.SH', score: 91, rank_percentile: 0.99, confidence: 0.9, reasons: [], risks: [] }],
    };
    const resultQueue = [growthRequest, Promise.resolve(qualityResult)];
    const getStrategyResults = vi.spyOn(client, 'getStrategyResults').mockImplementation(() => resultQueue.shift()!);
    renderStrategy();
    await waitFor(() => expect(getStrategyResults).toHaveBeenCalledTimes(1));
    fireEvent.change(screen.getByRole('combobox', { name: '选择策略' }), { target: { value: 'quality' } });
    await waitFor(() => expect(getStrategyResults).toHaveBeenCalledTimes(2));
    expect(await screen.findByText('600001.SH')).toBeInTheDocument();
    await act(async () => {
      resolveGrowth({
        query: { strategy_id: 'growth', as_of: '2026-09-21', limit: 50 },
        coverage: { covered_count: 1, total_count: 1, coverage_ratio: 1 },
        results: [{ symbol: '600002.SH', score: 70, rank_percentile: 0.7, confidence: 0.5, reasons: [], risks: [] }],
      });
      await growthRequest;
    });
    expect(screen.queryByText('600002.SH')).not.toBeInTheDocument();
    expect(screen.getByText('600001.SH')).toBeInTheDocument();
  });
});
