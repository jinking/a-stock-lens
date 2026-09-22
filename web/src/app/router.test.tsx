import { describe, it, expect } from 'vitest';
import { render, screen, within } from '@testing-library/react';
import '@testing-library/jest-dom/vitest';
import { createMemoryRouter, RouterProvider } from 'react-router-dom';
import { routes } from './router';

describe('Router & AppShell Smoke Tests', () => {
  it('renders TodayPage within AppShell at route "/"', () => {
    const router = createMemoryRouter(routes, { initialEntries: ['/'] });
    render(<RouterProvider router={router} />);

    // Verify AppShell header navigation
    const nav = screen.getByRole('navigation', { name: '主要导航' });
    expect(nav).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: '今日概览' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: '候选股票池' })).toBeInTheDocument();
    expect(within(nav).getByRole('link', { name: '策略筛选' })).toBeInTheDocument();

    // Verify TodayPage content
    const page = screen.getByTestId('today-page');
    expect(page).toBeInTheDocument();
    expect(within(page).getByRole('heading', { level: 1, name: '今日研究概览' })).toBeInTheDocument();
  });

  it('renders CandidatesPage within AppShell at route "/candidates"', () => {
    const router = createMemoryRouter(routes, { initialEntries: ['/candidates'] });
    render(<RouterProvider router={router} />);

    const nav = screen.getByRole('navigation', { name: '主要导航' });
    expect(nav).toBeInTheDocument();

    const page = screen.getByTestId('candidates-page');
    expect(page).toBeInTheDocument();
    expect(within(page).getByRole('heading', { level: 1, name: '候选股票池' })).toBeInTheDocument();
  });

  it('renders StockProfilePage within AppShell at route "/stocks/:symbol"', () => {
    const router = createMemoryRouter(routes, { initialEntries: ['/stocks/600519.SH'] });
    render(<RouterProvider router={router} />);

    const nav = screen.getByRole('navigation', { name: '主要导航' });
    expect(nav).toBeInTheDocument();

    const page = screen.getByTestId('stock-profile-page');
    expect(page).toBeInTheDocument();
    expect(within(page).getByRole('heading', { level: 1, name: /600519\.SH/ })).toBeInTheDocument();
  });

  it('renders StrategyPage within AppShell at route "/strategies/:strategyId"', () => {
    const router = createMemoryRouter(routes, { initialEntries: ['/strategies/value'] });
    render(<RouterProvider router={router} />);

    const nav = screen.getByRole('navigation', { name: '主要导航' });
    expect(nav).toBeInTheDocument();

    const page = screen.getByTestId('strategy-page');
    expect(page).toBeInTheDocument();
    expect(within(page).getByRole('heading', { level: 1, name: /value/ })).toBeInTheDocument();
  });
});
