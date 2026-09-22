import { describe, expect, it } from 'vitest';
import { render, screen } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { MemoryRouter, Outlet, Route, Routes } from 'react-router-dom';
import { AppShell } from './AppShell';
import { StatusBadge } from './StatusBadge';
import { DateContext, type DateContextValue } from '../app/DateContext';

const dateContext: DateContextValue = {
  dates: ['2026-09-21'], asOf: '2026-09-21', setAsOf: () => {}, loading: false,
  error: null, refreshDates: async () => {},
};

describe('accessible research controls', () => {
  it('provides a named navigation landmark and readable navigation links', () => {
    render(
      <DateContext.Provider value={dateContext}>
        <MemoryRouter>
          <Routes><Route element={<AppShell />}><Route index element={<Outlet />} /></Route></Routes>
        </MemoryRouter>
      </DateContext.Provider>
    );
    expect(screen.getByRole('navigation', { name: '主要导航' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '今日概览' })).toBeInTheDocument();
    expect(screen.getByRole('link', { name: '候选股票池' })).toBeInTheDocument();
  });

  it('communicates risk meaning in text rather than relying on badge color', () => {
    render(<StatusBadge value="TREND_WEAKEN" highlight />);
    expect(screen.getByText('TREND_WEAKEN')).toBeVisible();
  });
});
