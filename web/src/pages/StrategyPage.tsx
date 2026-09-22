import { useParams } from 'react-router-dom';

export function StrategyPage() {
  const { strategyId } = useParams<{ strategyId: string }>();

  return (
    <div className="page-container" data-testid="strategy-page">
      <header className="page-header">
        <h1 className="page-title">策略筛选: {strategyId ?? '未指定'}</h1>
        <p className="page-description">
          展示单策略全市场排名与双门槛合格池。
        </p>
      </header>
      <div className="placeholder-card">
        <p>策略 {strategyId ?? '未指定'} 筛选结果占位展示。</p>
      </div>
    </div>
  );
}
