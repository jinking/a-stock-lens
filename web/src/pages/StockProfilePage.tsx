import { useParams } from 'react-router-dom';

export function StockProfilePage() {
  const { symbol } = useParams<{ symbol: string }>();

  return (
    <div className="page-container" data-testid="stock-profile-page">
      <header className="page-header">
        <h1 className="page-title">股票画像: {symbol ?? '未指定'}</h1>
        <p className="page-description">
          展示单只股票的候选资格、策略契合度、因子明细与血缘追溯。
        </p>
      </header>
      <div className="placeholder-card">
        <p>股票 {symbol ?? '未指定'} 详细画像占位展示。</p>
      </div>
    </div>
  );
}
