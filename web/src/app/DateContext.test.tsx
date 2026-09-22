import { describe, it, expect, vi, beforeEach } from 'vitest';
import { render, screen, waitFor, fireEvent } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import * as clientModule from '../api/client';
import { ApiError } from '../api/client';
import { DateProvider, useDateContext } from './DateContext';
import { routes } from './router';

// Test consumer helper component
function TestConsumer() {
  const { dates, asOf, setAsOf, loading, error, refreshDates } = useDateContext();
  return (
    <div data-testid="test-consumer">
      <div data-testid="loading-val">{String(loading)}</div>
      <div data-testid="error-val">{error ?? 'none'}</div>
      <div data-testid="as-of-val">{asOf ?? 'null'}</div>
      <div data-testid="dates-val">{dates.join(',')}</div>
      <button onClick={() => setAsOf('2026-09-17')}>选择0917</button>
      <button onClick={() => void refreshDates()}>刷新日期</button>
    </div>
  );
}

describe('DateContext & AppShell Date Integration', () => {
  beforeEach(() => {
    vi.restoreAllMocks();
  });

  describe('DateContext Unit Behavior', () => {
    it('selects latest date by default when dates are available', async () => {
      vi.spyOn(clientModule, 'getCandidateDates').mockResolvedValueOnce({
        kind: 'CANDIDATE',
        dates: ['2026-09-17', '2026-09-19'],
        latest: '2026-09-19',
      });

      render(
        <DateProvider>
          <TestConsumer />
        </DateProvider>
      );

      // Initially loading
      expect(screen.getByTestId('loading-val')).toHaveTextContent('true');

      // Resolved
      await waitFor(() => {
        expect(screen.getByTestId('loading-val')).toHaveTextContent('false');
      });

      expect(screen.getByTestId('as-of-val')).toHaveTextContent('2026-09-19');
      expect(screen.getByTestId('dates-val')).toHaveTextContent('2026-09-17,2026-09-19');
      expect(screen.getByTestId('error-val')).toHaveTextContent('none');
    });

    it('defaults asOf to last date if latest field is missing', async () => {
      vi.spyOn(clientModule, 'getCandidateDates').mockResolvedValueOnce({
        kind: 'CANDIDATE',
        dates: ['2026-09-15', '2026-09-18'],
        latest: null,
      });

      render(
        <DateProvider>
          <TestConsumer />
        </DateProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('loading-val')).toHaveTextContent('false');
      });

      expect(screen.getByTestId('as-of-val')).toHaveTextContent('2026-09-18');
    });

    it('sets asOf to null when dates are empty', async () => {
      vi.spyOn(clientModule, 'getCandidateDates').mockResolvedValueOnce({
        kind: 'CANDIDATE',
        dates: [],
        latest: null,
      });

      render(
        <DateProvider>
          <TestConsumer />
        </DateProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('loading-val')).toHaveTextContent('false');
      });

      expect(screen.getByTestId('as-of-val')).toHaveTextContent('null');
      expect(screen.getByTestId('dates-val')).toHaveTextContent('');
    });

    it('updates asOf when setAsOf is invoked', async () => {
      vi.spyOn(clientModule, 'getCandidateDates').mockResolvedValueOnce({
        kind: 'CANDIDATE',
        dates: ['2026-09-17', '2026-09-19'],
        latest: '2026-09-19',
      });

      render(
        <DateProvider>
          <TestConsumer />
        </DateProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('as-of-val')).toHaveTextContent('2026-09-19');
      });

      fireEvent.click(screen.getByText('选择0917'));
      expect(screen.getByTestId('as-of-val')).toHaveTextContent('2026-09-17');
    });

    it('sets error message when getCandidateDates fails with ApiError', async () => {
      vi.spyOn(clientModule, 'getCandidateDates').mockRejectedValueOnce(
        new ApiError(500, '后端服务不可用')
      );

      render(
        <DateProvider>
          <TestConsumer />
        </DateProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('loading-val')).toHaveTextContent('false');
      });

      expect(screen.getByTestId('error-val')).toHaveTextContent('后端服务不可用');
      expect(screen.getByTestId('as-of-val')).toHaveTextContent('null');
    });

    it('refreshDates refetches dates and updates context', async () => {
      vi.spyOn(clientModule, 'getCandidateDates')
        .mockResolvedValueOnce({
          kind: 'CANDIDATE',
          dates: ['2026-09-17'],
          latest: '2026-09-17',
        })
        .mockResolvedValueOnce({
          kind: 'CANDIDATE',
          dates: ['2026-09-17', '2026-09-20'],
          latest: '2026-09-20',
        });

      render(
        <DateProvider>
          <TestConsumer />
        </DateProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('as-of-val')).toHaveTextContent('2026-09-17');
      });

      fireEvent.click(screen.getByText('刷新日期'));

      await waitFor(() => {
        expect(screen.getByTestId('as-of-val')).toHaveTextContent('2026-09-20');
        expect(screen.getByTestId('dates-val')).toHaveTextContent('2026-09-17,2026-09-20');
      });
    });
  });

  describe('AppShell Date Picker Integration', () => {
    it('renders date picker with latest date selected by default', async () => {
      vi.spyOn(clientModule, 'getCandidateDates').mockResolvedValueOnce({
        kind: 'CANDIDATE',
        dates: ['2026-09-17', '2026-09-19'],
        latest: '2026-09-19',
      });

      const router = createMemoryRouter(routes, { initialEntries: ['/'] });

      render(
        <DateProvider>
          <RouterProvider router={router} />
        </DateProvider>
      );

      await waitFor(() => {
        const select = screen.getByRole('combobox', { name: '快照日期' }) as HTMLSelectElement;
        expect(select).toBeInTheDocument();
        expect(select.value).toBe('2026-09-19');
      });

      const options = screen.getAllByRole('option');
      expect(options).toHaveLength(2);
      expect(options[0]).toHaveTextContent('2026-09-17');
      expect(options[1]).toHaveTextContent('2026-09-19');
    });

    it('shows exact empty notice when no candidate snapshots exist', async () => {
      vi.spyOn(clientModule, 'getCandidateDates').mockResolvedValueOnce({
        kind: 'CANDIDATE',
        dates: [],
        latest: null,
      });

      const router = createMemoryRouter(routes, { initialEntries: ['/'] });

      render(
        <DateProvider>
          <RouterProvider router={router} />
        </DateProvider>
      );

      await waitFor(() => {
        expect(screen.getByTestId('date-empty-notice')).toHaveTextContent(
          '尚无正式 Candidate 快照。先运行标准 astock daily。'
        );
      });

      expect(screen.queryByRole('combobox', { name: '快照日期' })).not.toBeInTheDocument();
    });

    it('preserves navigation route when date is changed in AppShell', async () => {
      vi.spyOn(clientModule, 'getCandidateDates').mockResolvedValueOnce({
        kind: 'CANDIDATE',
        dates: ['2026-09-17', '2026-09-19'],
        latest: '2026-09-19',
      });

      const router = createMemoryRouter(routes, { initialEntries: ['/candidates'] });

      render(
        <DateProvider>
          <RouterProvider router={router} />
        </DateProvider>
      );

      // Verify on /candidates
      expect(screen.getByTestId('candidates-page')).toBeInTheDocument();

      await waitFor(() => {
        expect(screen.getByRole('combobox', { name: '快照日期' })).toBeInTheDocument();
      });

      const select = screen.getByRole('combobox', { name: '快照日期' }) as HTMLSelectElement;
      expect(select.value).toBe('2026-09-19');

      // Change date to 2026-09-17
      fireEvent.change(select, { target: { value: '2026-09-17' } });

      expect(select.value).toBe('2026-09-17');
      // Navigation route is preserved: still on candidates page
      expect(screen.getByTestId('candidates-page')).toBeInTheDocument();
    });
  });
});
