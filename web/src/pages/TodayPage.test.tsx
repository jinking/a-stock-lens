import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import * as clientModule from '../api/client';
import { ApiError } from '../api/client';
import { DateContext, DateContextValue } from '../app/DateContext';
import { TodayPage } from './TodayPage';
import type { TodayOverview } from '../api/types';

const mockOverview: TodayOverview = {
  as_of: '2026-09-19',
  market_regime: 'BULL',
  candidate_count: 42,
  confirmed_count: 28,
  neutral_count: 14,
  strategy_distribution: {
    low_pe: 20,
    dividend: 15,
    growth: 7,
  },
  validation_distribution: {
    CONFIRMED: 28,
    NEUTRAL: 14,
  },
  signal_distribution: {
    BREAKOUT: 18,
    MOMENTUM_ACCELERATION: 10,
    NEUTRAL: 14,
  },
  top_candidates: [
    {
      symbol: '600519.SH',
      primary_strategy_id: 'low_pe',
      primary_score: 95.5,
      rank_percentile: 0.98,
      qualified_strategies: ['low_pe', 'dividend'],
      market_validation: 'CONFIRMED',
      signal: 'BREAKOUT',
      next_action: 'TRACK_SIGNAL',
      reasons: ['低估值稳定分红', '突破半年线'],
      risks: ['行业周期见顶', 'TREND_WEAKEN'],
      rank: 1,
    },
    {
      symbol: '000001.SZ',
      primary_strategy_id: 'dividend',
      primary_score: 88.0,
      rank_percentile: 0.85,
      qualified_strategies: ['dividend'],
      market_validation: 'NEUTRAL',
      signal: 'NEUTRAL',
      next_action: 'WATCH',
      reasons: ['股息率处于高位'],
      risks: ['息差收窄'],
      rank: 2,
    },
  ],
};

function renderTodayPage(contextOverride?: Partial<DateContextValue>) {
  const defaultContext: DateContextValue = {
    dates: ['2026-09-17', '2026-09-19'],
    asOf: '2026-09-19',
    setAsOf: vi.fn(),
    loading: false,
    error: null,
    refreshDates: vi.fn().mockResolvedValue(undefined),
    ...contextOverride,
  };

  return render(
    <DateContext.Provider value={defaultContext}>
      <MemoryRouter initialEntries={['/']}>
        <Routes>
          <Route path="/" element={<TodayPage />} />
          <Route path="/stocks/:symbol" element={<div data-testid="stock-detail-page">标的详情页</div>} />
        </Routes>
      </MemoryRouter>
    </DateContext.Provider>
  );
}

describe('TodayPage (Web MVP)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // Step 1: exact card counts
  it('renders exact overview card counts and header with as_of date', async () => {
    vi.spyOn(clientModule, 'getToday').mockResolvedValueOnce(mockOverview);

    renderTodayPage();

    // Verify header
    expect(screen.getByRole('heading', { level: 1, name: '今日盘后研究概览' })).toBeInTheDocument();
    expect(screen.getByText(/2026-09-19/)).toBeInTheDocument();

    // Wait for data load
    await waitFor(() => {
      expect(screen.getByTestId('stat-candidate-count')).toHaveTextContent('42');
    });

    expect(screen.getByTestId('stat-confirmed-count')).toHaveTextContent('28');
    expect(screen.getByTestId('stat-neutral-count')).toHaveTextContent('14');
  });

  // Step 2: regime badge preserves domain value and adds Chinese explanatory label without trading advice
  it('displays regime badge preserving domain value with Chinese explanation and strictly no trading advice', async () => {
    vi.spyOn(clientModule, 'getToday').mockResolvedValueOnce(mockOverview);

    renderTodayPage();

    await waitFor(() => {
      const regimeCard = screen.getByTestId('stat-market-regime');
      expect(regimeCard).toHaveTextContent('BULL (多头市场)');
      // Strictly NO buying/selling or trading advice
      expect(regimeCard.textContent).not.toMatch(/买入|卖出|做多|做空|建议/);
    });

    // Test other regimes (BEAR, SHOCK, null)
    vi.spyOn(clientModule, 'getToday').mockResolvedValueOnce({
      ...mockOverview,
      market_regime: 'BEAR',
    });
    const { unmount: unmountBear } = renderTodayPage();
    await waitFor(() => {
      expect(screen.getAllByTestId('stat-market-regime')[1]).toHaveTextContent('BEAR (空头市场)');
    });
    unmountBear();

    vi.spyOn(clientModule, 'getToday').mockResolvedValueOnce({
      ...mockOverview,
      market_regime: 'SHOCK',
    });
    const { unmount: unmountShock } = renderTodayPage();
    await waitFor(() => {
      expect(screen.getAllByTestId('stat-market-regime')[1]).toHaveTextContent('SHOCK (震荡市场)');
    });
    unmountShock();

    vi.spyOn(clientModule, 'getToday').mockResolvedValueOnce({
      ...mockOverview,
      market_regime: null,
    });
    const { unmount: unmountNull } = renderTodayPage();
    await waitFor(() => {
      expect(screen.getAllByTestId('stat-market-regime')[1]).toHaveTextContent('未知');
    });
    unmountNull();
  });

  // Step 3: clicking candidate symbol routes to /stocks/<symbol> and badges TREND_WEAKEN
  it('renders top 10 candidates table, links symbol to /stocks/:symbol, and visibly badges TREND_WEAKEN', async () => {
    vi.spyOn(clientModule, 'getToday').mockResolvedValueOnce(mockOverview);

    renderTodayPage();

    await waitFor(() => {
      expect(screen.getByTestId('candidates-table')).toBeInTheDocument();
    });

    const table = screen.getByTestId('candidates-table');
    expect(within(table).getByText('600519.SH')).toBeInTheDocument();
    expect(within(table).getByText('000001.SZ')).toBeInTheDocument();

    // Check ranks
    expect(within(table).getByText('1')).toBeInTheDocument();
    expect(within(table).getByText('2')).toBeInTheDocument();

    // Check validation badges
    expect(within(table).getByText('CONFIRMED')).toBeInTheDocument();
    expect(within(table).getAllByText('NEUTRAL').length).toBeGreaterThanOrEqual(1);

    // Check signals
    expect(within(table).getByText('BREAKOUT')).toBeInTheDocument();

    // Check actions
    expect(within(table).getByText('TRACK_SIGNAL')).toBeInTheDocument();
    expect(within(table).getByText('WATCH')).toBeInTheDocument();

    // Check TREND_WEAKEN highlight badge
    const trendWeakenBadge = screen.getByTestId('risk-badge-TREND_WEAKEN');
    expect(trendWeakenBadge).toBeInTheDocument();
    expect(trendWeakenBadge).toHaveClass('risk-badge-highlight');

    // Click candidate symbol link
    const symbolLink = within(table).getByRole('link', { name: '600519.SH' });
    expect(symbolLink).toHaveAttribute('href', '/stocks/600519.SH');

    fireEvent.click(symbolLink);

    // Verify routed to /stocks/600519.SH
    await waitFor(() => {
      expect(screen.getByTestId('stock-detail-page')).toBeInTheDocument();
    });
  });

  // Step 4: CSS count bars display distribution keys and counts
  it('displays pure CSS count bars for strategy and signal distributions', async () => {
    vi.spyOn(clientModule, 'getToday').mockResolvedValueOnce(mockOverview);

    renderTodayPage();

    await waitFor(() => {
      expect(screen.getByTestId('strategy-distribution-bars')).toBeInTheDocument();
      expect(screen.getByTestId('signal-distribution-bars')).toBeInTheDocument();
    });

    const strategyBars = screen.getByTestId('strategy-distribution-bars');
    expect(within(strategyBars).getByText('low_pe')).toBeInTheDocument();
    expect(within(strategyBars).getByText('20')).toBeInTheDocument();
    expect(within(strategyBars).getByText('dividend')).toBeInTheDocument();
    expect(within(strategyBars).getByText('15')).toBeInTheDocument();
    expect(within(strategyBars).getByText('growth')).toBeInTheDocument();
    expect(within(strategyBars).getByText('7')).toBeInTheDocument();

    const signalBars = screen.getByTestId('signal-distribution-bars');
    expect(within(signalBars).getByText('BREAKOUT')).toBeInTheDocument();
    expect(within(signalBars).getByText('18')).toBeInTheDocument();
    expect(within(signalBars).getByText('MOMENTUM_ACCELERATION')).toBeInTheDocument();
    expect(within(signalBars).getByText('10')).toBeInTheDocument();
  });

  // Step 5: loading, error with retry, and empty date state
  it('handles empty date state with exact required message', async () => {
    renderTodayPage({ asOf: null, loading: false });

    expect(
      screen.getByText('尚无正式 Candidate 快照。先运行标准 astock daily。')
    ).toBeInTheDocument();
    expect(screen.queryByTestId('candidates-table')).not.toBeInTheDocument();
  });

  it('displays loading state when data or dates are loading', async () => {
    let resolvePromise: (val: TodayOverview) => void;
    const pendingPromise = new Promise<TodayOverview>((resolve) => {
      resolvePromise = resolve;
    });
    vi.spyOn(clientModule, 'getToday').mockReturnValueOnce(pendingPromise);

    renderTodayPage();

    expect(screen.getByTestId('today-loading')).toBeInTheDocument();

    resolvePromise!(mockOverview);
    await waitFor(() => {
      expect(screen.queryByTestId('today-loading')).not.toBeInTheDocument();
    });
  });

  it('handles error state and allows retry with "重试" button', async () => {
    vi.spyOn(clientModule, 'getToday')
      .mockRejectedValueOnce(new ApiError(500, '网络连接中断或服务异常'))
      .mockResolvedValueOnce(mockOverview);

    renderTodayPage();

    await waitFor(() => {
      expect(screen.getByTestId('today-error')).toHaveTextContent('网络连接中断或服务异常');
    });

    const retryBtn = screen.getByRole('button', { name: '重试' });
    expect(retryBtn).toBeInTheDocument();

    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(screen.queryByTestId('today-error')).not.toBeInTheDocument();
      expect(screen.getByTestId('stat-candidate-count')).toHaveTextContent('42');
    });
  });
});
