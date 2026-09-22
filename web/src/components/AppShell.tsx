import { NavLink, Outlet } from 'react-router-dom';

export function AppShell() {
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
