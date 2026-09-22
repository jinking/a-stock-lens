import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { MemoryRouter } from 'react-router-dom';
import { CandidateTable } from './CandidateTable';
import type { Candidate } from '../api/types';

describe('CandidateTable', () => {
  const sampleCandidates: Candidate[] = [
    {
      symbol: '600519.SH',
      primary_strategy_id: 'low_pe',
      primary_score: 95.0,
      rank_percentile: 0.99,
      qualified_strategies: ['low_pe'],
      market_validation: 'CONFIRMED',
      signal: 'BREAKOUT',
      next_action: 'TRACK_SIGNAL',
      reasons: ['突破压力位'],
      risks: ['TREND_WEAKEN'],
      rank: 1,
    },
    {
      symbol: '300750.SZ',
      primary_strategy_id: 'growth',
      primary_score: 80.0,
      rank_percentile: 0.75,
      qualified_strategies: ['growth'],
      market_validation: 'CONTRADICTED',
      signal: 'BREAKDOWN',
      next_action: 'DISCOVERED',
      reasons: [],
      risks: [],
      rank: 5,
    },
  ];

  it('renders empty table notice when candidate list is empty', () => {
    render(
      <MemoryRouter>
        <CandidateTable candidates={[]} />
      </MemoryRouter>
    );

    expect(screen.getByText('暂无候选股票数据。')).toBeInTheDocument();
  });

  it('renders candidates with authoritative rank, links, and breakdown warning', () => {
    render(
      <MemoryRouter>
        <CandidateTable candidates={sampleCandidates} />
      </MemoryRouter>
    );

    const table = screen.getByTestId('candidates-table');

    // Check rank 1 and rank 5 preserved
    expect(within(table).getByText('1')).toBeInTheDocument();
    expect(within(table).getByText('5')).toBeInTheDocument();

    // Check symbol link
    const link = within(table).getByRole('link', { name: '600519.SH' });
    expect(link).toHaveAttribute('href', '/stocks/600519.SH');

    // Check BREAKDOWN warning indicator
    expect(screen.getByTestId('signal-warning-breakdown')).toHaveTextContent('破位告警');

    // Check TREND_WEAKEN highlight
    const riskBadge = screen.getByTestId('risk-badge-TREND_WEAKEN');
    expect(riskBadge).toHaveClass('risk-badge-highlight');

    // Check empty reasons/risks renders '-'
    const dashElements = within(table).getAllByText('-');
    expect(dashElements.length).toBeGreaterThanOrEqual(2);
  });
});
