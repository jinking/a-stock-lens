import { NavLink, Outlet } from 'react-router-dom';
import { useDateContext } from '../app/DateContext';

export function AppShell() {
  const { dates, asOf, setAsOf, loading, error } = useDateContext();

  return (
    <div className="app-layout">
      <header className="app-header">
        <div className="header-inner">
          <div className="header-brand">
            <span className="brand-title">A-Stock Lens</span>
            <span className="brand-tag">研究看板</span>
          </div>

          <nav className="header-nav" aria-label="主要导航">
            <NavLink
              to="/"
              end
              className={({ isActive }) =>
                isActive ? 'nav-link active' : 'nav-link'
              }
            >
              今日概览
            </NavLink>
            <NavLink
              to="/candidates"
              className={({ isActive }) =>
                isActive ? 'nav-link active' : 'nav-link'
              }
            >
              候选股票池
            </NavLink>
            <NavLink
              to="/strategies/value"
              className={({ isActive }) =>
                isActive ? 'nav-link active' : 'nav-link'
              }
            >
              策略筛选
            </NavLink>

            <div className="header-date-picker" data-testid="header-date-picker">
              {loading ? (
                <span className="date-picker-loading" data-testid="date-loading">
                  加载日期中...
                </span>
              ) : error ? (
                <span className="date-picker-error" data-testid="date-error" title={error}>
                  {error}
                </span>
              ) : dates.length === 0 ? (
                <span className="date-empty-notice" data-testid="date-empty-notice">
                  尚无正式 Candidate 快照。先运行标准 astock daily。
                </span>
              ) : (
                <div className="date-picker-control">
                  <label htmlFor="snapshot-date-select" className="date-picker-label">
                    快照日期
                  </label>
                  <select
                    id="snapshot-date-select"
                    aria-label="快照日期"
                    data-testid="snapshot-date-select"
                    className="date-select"
                    value={asOf ?? ''}
                    onChange={(e) => setAsOf(e.target.value)}
                  >
                    {dates.map((date) => (
                      <option key={date} value={date}>
                        {date}
                      </option>
                    ))}
                  </select>
                </div>
              )}
            </div>
          </nav>

          <div className="header-actions">
            <span className="notice-badge">只读研究辅助 · 非投资建议</span>
          </div>
        </div>
      </header>

      <main className="app-main">
        <div className="main-content">
          <Outlet />
        </div>
      </main>

      <footer className="app-footer">
        <div className="footer-inner">
          <span>A-Stock Lens · 严谨量化研究看板 · 仅供学习与学术研究</span>
        </div>
      </footer>
    </div>
  );
}
