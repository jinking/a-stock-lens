export function TodayPage() {
  return (
    <div className="page-container" data-testid="today-page">
      <header className="page-header">
        <h1 className="page-title">今日研究概览</h1>
        <p className="page-description">
          展示当日市场状态 (Market Regime)、候选池规模、策略分布与 Top 10 候选股票。
        </p>
      </header>
      <div className="placeholder-card">
        <p>今日概览数据加载中或占位展示。</p>
      </div>
    </div>
  );
}
