import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent, within } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { MemoryRouter, Route, Routes } from 'react-router-dom';
import * as clientModule from '../api/client';
import { ApiError } from '../api/client';
import { DateContext, DateContextValue } from '../app/DateContext';
import { CandidatesPage } from './CandidatesPage';
import type { Candidate, CandidatesResponse } from '../api/types';

const mockCandidates: Candidate[] = [
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
  {
    symbol: '300750.SZ',
    primary_strategy_id: 'growth',
    primary_score: 82.0,
    rank_percentile: 0.75,
    qualified_strategies: ['growth'],
    market_validation: 'CONTRADICTED',
    signal: 'BREAKDOWN',
    next_action: 'DISCOVERED',
    reasons: ['前期高成长'],
    risks: ['高估值', '行业竞争加剧'],
    rank: 3,
  },
  {
    symbol: '601398.SH',
    primary_strategy_id: 'low_pe',
    primary_score: 79.0,
    rank_percentile: 0.70,
    qualified_strategies: ['low_pe'],
    market_validation: 'CONFIRMED',
    signal: 'MOMENTUM_ACCELERATION',
    next_action: 'DEEP_RESEARCH',
    reasons: ['极低PB'],
    risks: ['成长性弱'],
    rank: 4,
  },
];

const mockCandidatesResponse: CandidatesResponse = {
  as_of: '2026-09-19',
  records: mockCandidates,
};

function renderCandidatesPage(contextOverride?: Partial<DateContextValue>) {
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
      <MemoryRouter initialEntries={['/candidates']}>
        <Routes>
          <Route path="/candidates" element={<CandidatesPage />} />
          <Route path="/stocks/:symbol" element={<div data-testid="stock-profile-page">标的画像页</div>} />
        </Routes>
      </MemoryRouter>
    </DateContext.Provider>
  );
}

describe('CandidatesPage (Web MVP)', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  // Step 1: Filtered rows retain original authoritative rank
  it('filtered rows retain their original authoritative rank (cand.rank)', async () => {
    vi.spyOn(clientModule, 'getCandidates').mockResolvedValueOnce(mockCandidatesResponse);

    renderCandidatesPage();

    await waitFor(() => {
      expect(screen.getByTestId('candidates-table')).toBeInTheDocument();
    });

    // Verify all 4 are present initially
    const table = screen.getByTestId('candidates-table');
    expect(within(table).getByText('600519.SH')).toBeInTheDocument();
    expect(within(table).getByText('000001.SZ')).toBeInTheDocument();
    expect(within(table).getByText('300750.SZ')).toBeInTheDocument();
    expect(within(table).getByText('601398.SH')).toBeInTheDocument();

    // Filter to 000001.SZ by symbol
    const symbolFilter = screen.getByTestId('filter-symbol');
    fireEvent.change(symbolFilter, { target: { value: '000001' } });

    // 000001.SZ was rank 2 originally. It must display 2, NOT 1!
    expect(within(table).getByText('000001.SZ')).toBeInTheDocument();
    expect(within(table).queryByText('600519.SH')).not.toBeInTheDocument();
    const rankCell = within(table).getByText('2');
    expect(rankCell).toBeInTheDocument();
    expect(within(table).queryByText('1')).not.toBeInTheDocument();

    // Filter to 300750.SZ by strategy (growth)
    fireEvent.change(symbolFilter, { target: { value: '' } });
    const strategyFilter = screen.getByTestId('filter-strategy');
    fireEvent.change(strategyFilter, { target: { value: 'growth' } });

    // 300750.SZ was rank 3 originally. It must display 3, NOT 1!
    expect(within(table).getByText('300750.SZ')).toBeInTheDocument();
    expect(within(table).getByText('3')).toBeInTheDocument();
    expect(within(table).queryByText('1')).not.toBeInTheDocument();
  });

  // Step 2: TREND_WEAKEN risk visibly highlighted
  it('visibly badges and highlights TREND_WEAKEN risk', async () => {
    vi.spyOn(clientModule, 'getCandidates').mockResolvedValueOnce(mockCandidatesResponse);

    renderCandidatesPage();

    await waitFor(() => {
      expect(screen.getByTestId('candidates-table')).toBeInTheDocument();
    });

    const trendWeakenBadge = screen.getByTestId('risk-badge-TREND_WEAKEN');
    expect(trendWeakenBadge).toBeInTheDocument();
    expect(trendWeakenBadge).toHaveClass('risk-badge-highlight');
    expect(trendWeakenBadge).toHaveTextContent('TREND_WEAKEN');
  });

  // Step 3: Unexpected BREAKDOWN signal renders data-integrity warning indicator rather than hiding it
  it('renders unexpected BREAKDOWN signal with a visible data-integrity warning indicator rather than hiding the row', async () => {
    vi.spyOn(clientModule, 'getCandidates').mockResolvedValueOnce(mockCandidatesResponse);

    renderCandidatesPage();

    await waitFor(() => {
      expect(screen.getByTestId('candidates-table')).toBeInTheDocument();
    });

    const table = screen.getByTestId('candidates-table');
    // 300750.SZ is NOT hidden
    expect(within(table).getByText('300750.SZ')).toBeInTheDocument();
    expect(within(table).getByText('BREAKDOWN')).toBeInTheDocument();

    // Must have a visible data-integrity / breakdown warning indicator
    const warningIndicator = screen.getByTestId('signal-warning-breakdown');
    expect(warningIndicator).toBeInTheDocument();
    expect(warningIndicator.textContent).toMatch(/异常|破位|告警|BREAKDOWN/);
  });

  // Step 4: Filters work properly and NO sort dropdown exists
  it('supports 4 filters, count summary, reset button, and strictly has NO sort dropdown', async () => {
    vi.spyOn(clientModule, 'getCandidates').mockResolvedValueOnce(mockCandidatesResponse);

    renderCandidatesPage();

    await waitFor(() => {
      expect(screen.getByTestId('candidates-table')).toBeInTheDocument();
    });

    // Verify filter count summary initially
    const summary = screen.getByTestId('candidate-count-summary');
    expect(summary).toHaveTextContent('展示 4 / 总计 4 只候选标的');

    // 1. Filter by symbol (case insensitive match 'sh')
    const symbolFilter = screen.getByTestId('filter-symbol');
    fireEvent.change(symbolFilter, { target: { value: 'sh' } });
    expect(summary).toHaveTextContent('展示 2 / 总计 4 只候选标的');
    const table = screen.getByTestId('candidates-table');
    expect(within(table).getByText('600519.SH')).toBeInTheDocument();
    expect(within(table).getByText('601398.SH')).toBeInTheDocument();
    expect(within(table).queryByText('000001.SZ')).not.toBeInTheDocument();

    // 2. Filter by validation
    fireEvent.change(symbolFilter, { target: { value: '' } });
    const validationFilter = screen.getByTestId('filter-validation');
    fireEvent.change(validationFilter, { target: { value: 'CONFIRMED' } });
    expect(summary).toHaveTextContent('展示 2 / 总计 4 只候选标的');
    expect(within(table).getByText('600519.SH')).toBeInTheDocument();
    expect(within(table).getByText('601398.SH')).toBeInTheDocument();

    // 3. Filter by signal
    const signalFilter = screen.getByTestId('filter-signal');
    fireEvent.change(signalFilter, { target: { value: 'MOMENTUM_ACCELERATION' } });
    expect(summary).toHaveTextContent('展示 1 / 总计 4 只候选标的');
    expect(within(table).getByText('601398.SH')).toBeInTheDocument();
    expect(within(table).queryByText('600519.SH')).not.toBeInTheDocument();

    // 4. Reset button restores all
    const resetBtn = screen.getByTestId('filter-reset');
    fireEvent.click(resetBtn);
    expect(summary).toHaveTextContent('展示 4 / 总计 4 只候选标的');
    expect(within(table).getByText('600519.SH')).toBeInTheDocument();
    expect(within(table).getByText('000001.SZ')).toBeInTheDocument();
    expect(within(table).getByText('300750.SZ')).toBeInTheDocument();
    expect(within(table).getByText('601398.SH')).toBeInTheDocument();

    // Critical Requirement: Strictly NO sort dropdown in MVP!
    expect(screen.queryByTestId('sort-select')).not.toBeInTheDocument();
    expect(screen.queryByLabelText(/排序/)).not.toBeInTheDocument();
    const allSelects = screen.getAllByRole('combobox');
    for (const select of allSelects) {
      expect(select.getAttribute('name') ?? '').not.toMatch(/sort|order/i);
      expect(select.getAttribute('id') ?? '').not.toMatch(/sort|order/i);
    }
  });

  // Step 5: Symbol routes to /stocks/:symbol
  it('links candidate symbol to /stocks/:symbol', async () => {
    vi.spyOn(clientModule, 'getCandidates').mockResolvedValueOnce(mockCandidatesResponse);

    renderCandidatesPage();

    await waitFor(() => {
      expect(screen.getByTestId('candidates-table')).toBeInTheDocument();
    });

    const symbolLink = screen.getByRole('link', { name: '600519.SH' });
    expect(symbolLink).toHaveAttribute('href', '/stocks/600519.SH');

    fireEvent.click(symbolLink);

    await waitFor(() => {
      expect(screen.getByTestId('stock-profile-page')).toBeInTheDocument();
    });
  });

  // Step 6: Empty date, loading, error retry, empty filter match
  it('displays empty date notice when asOf is null', async () => {
    renderCandidatesPage({ asOf: null, loading: false });

    expect(
      screen.getByText('尚无正式 Candidate 快照。先运行标准 astock daily。')
    ).toBeInTheDocument();
    expect(screen.queryByTestId('candidates-table')).not.toBeInTheDocument();
  });

  it('displays loading state while candidates are loading', async () => {
    let resolvePromise: (val: CandidatesResponse) => void;
    const pendingPromise = new Promise<CandidatesResponse>((resolve) => {
      resolvePromise = resolve;
    });
    vi.spyOn(clientModule, 'getCandidates').mockReturnValueOnce(pendingPromise);

    renderCandidatesPage();

    expect(screen.getByTestId('candidates-loading')).toBeInTheDocument();

    resolvePromise!(mockCandidatesResponse);
    await waitFor(() => {
      expect(screen.queryByTestId('candidates-loading')).not.toBeInTheDocument();
    });
  });

  it('handles error state and supports retry with "重试" button', async () => {
    vi.spyOn(clientModule, 'getCandidates')
      .mockRejectedValueOnce(new ApiError(500, '候选池接口服务异常'))
      .mockResolvedValueOnce(mockCandidatesResponse);

    renderCandidatesPage();

    await waitFor(() => {
      expect(screen.getByTestId('candidates-error')).toHaveTextContent('候选池接口服务异常');
    });

    const retryBtn = screen.getByRole('button', { name: '重试' });
    expect(retryBtn).toBeInTheDocument();

    fireEvent.click(retryBtn);

    await waitFor(() => {
      expect(screen.queryByTestId('candidates-error')).not.toBeInTheDocument();
      expect(screen.getByTestId('candidates-table')).toBeInTheDocument();
    });
  });

  it('displays empty filter state when no candidate matches filters and allows reset', async () => {
    vi.spyOn(clientModule, 'getCandidates').mockResolvedValueOnce(mockCandidatesResponse);

    renderCandidatesPage();

    await waitFor(() => {
      expect(screen.getByTestId('candidates-table')).toBeInTheDocument();
    });

    const symbolFilter = screen.getByTestId('filter-symbol');
    fireEvent.change(symbolFilter, { target: { value: 'NONEXISTENT' } });

    expect(screen.getByTestId('candidates-empty-filter')).toHaveTextContent('无符合筛选条件的候选标的');

    // Clicking reset in empty filter state restores candidates
    const resetEmptyBtn = within(screen.getByTestId('candidates-empty-filter')).getByRole('button', { name: '重置筛选' });
    fireEvent.click(resetEmptyBtn);

    await waitFor(() => {
      expect(screen.queryByTestId('candidates-empty-filter')).not.toBeInTheDocument();
      expect(screen.getByTestId('candidates-table')).toBeInTheDocument();
    });
  });
});
