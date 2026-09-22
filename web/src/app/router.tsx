import { createBrowserRouter, Navigate, RouteObject } from 'react-router-dom';
import { AppShell } from '../components/AppShell';
import { TodayPage } from '../pages/TodayPage';
import { CandidatesPage } from '../pages/CandidatesPage';
import { StockProfilePage } from '../pages/StockProfilePage';
import { StrategyPage } from '../pages/StrategyPage';

export const routes: RouteObject[] = [
  {
    path: '/',
    element: <AppShell />,
    children: [
      {
        index: true,
        element: <TodayPage />,
      },
      {
        path: 'candidates',
        element: <CandidatesPage />,
      },
      {
        path: 'stocks/:symbol',
        element: <StockProfilePage />,
      },
      {
        path: 'strategies/:strategyId',
        element: <StrategyPage />,
      },
      {
        path: 'strategies',
        element: <Navigate to="/strategies/value" replace />,
      },
    ],
  },
];

export const router = createBrowserRouter(routes);
