import { useCallback, useEffect, useState } from 'react';
import { Link } from 'react-router-dom';
import { ApiError, getToday } from '../api/client';
import type { TodayOverview } from '../api/types';
import { useDateContext } from '../app/DateContext';
import { DistributionBars } from '../components/DistributionBars';
import { formatMarketRegime, StatusBadge } from '../components/StatusBadge';

export function TodayPage() {
  const { asOf, loading: dateLoading, error: dateError } = useDateContext();

  const [data, setData] = useState<TodayOverview | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  const fetchData = useCallback(async () => {
    if (!asOf) {
      setData(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const overview = await getToday(asOf, 10);
      setData(overview);
    } catch (err) {
      if (err instanceof ApiError || err instanceof Error) {
        setError(err.message);
      } else {
        setError('获取今日概览数据失败');
      }
      setData(null);
    } finally {
      setLoading(false);
    }
  }, [asOf]);

  useEffect(() => {
    if (asOf) {
      void fetchData();
    } else {
      setData(null);
    }
  }, [asOf, fetchData]);

  // 当没有可用日期且日期加载完毕时
  if (!dateLoading && asOf == null) {
    return (
      <div className="page-container" data-testid="today-page">
        <header className="page-header">
          <h1 className="page-title">今日盘后研究概览</h1>
          <p className="page-description">展示当日市场状态、候选池规模、策略分布与 Top 10 候选股票。</p>
        </header>
        <div className="empty-state-card" data-testid="today-empty">
          <p className="empty-notice">尚无正式 Candidate 快照。先运行标准 astock daily。</p>
        </div>
      </div>
    );
  }

  // 加载状态：日期正在加载或页面数据正在加载
  if (dateLoading || loading) {
    return (
      <div className="page-container" data-testid="today-page">
        <header className="page-header">
          <h1 className="page-title">今日盘后研究概览</h1>
          <p className="page-description">快照基准日期：{asOf ?? '加载中...'}</p>
        </header>
        <div className="loading-card" data-testid="today-loading">
          <div className="loading-spinner" />
          <p>正在加载今日盘后研究概览...</p>
        </div>
      </div>
    );
  }

  // 错误状态
  if (error || dateError) {
    const displayError = error ?? dateError ?? '加载失败';
    return (
      <div className="page-container" data-testid="today-page">
        <header className="page-header">
          <h1 className="page-title">今日盘后研究概览</h1>
          <p className="page-description">快照基准日期：{asOf ?? '未知'}</p>
        </header>
        <div className="error-card" data-testid="today-error">
          <p className="error-message">{displayError}</p>
          <button type="button" className="retry-button" onClick={() => void fetchData()}>
            重试
          </button>
        </div>
      </div>
    );
  }

  // 数据已就绪
  return (
    <div className="page-container" data-testid="today-page">
      <header className="page-header">
        <h1 className="page-title">今日盘后研究概览</h1>
        <p className="page-description">
          快照基准日期：<span className="font-mono text-accent">{data?.as_of ?? asOf}</span> ·
          客观量化候选池统计与排序
        </p>
      </header>

      {/* 四个总览指标卡片 */}
      <section className="stats-grid" aria-label="核心指标统计">
        <div className="stat-card">
          <span className="stat-label">市场环境</span>
          <div className="stat-value-container" data-testid="stat-market-regime">
            <StatusBadge
              type="regime"
              value={formatMarketRegime(data?.market_regime)}
              className="regime-badge"
            />
          </div>
          <span className="stat-hint">宏观与大盘技术状态界定</span>
        </div>

        <div className="stat-card">
          <span className="stat-label">研究候选总数</span>
          <div className="stat-value font-mono" data-testid="stat-candidate-count">
            {data?.candidate_count ?? 0}
          </div>
          <span className="stat-hint">通过双门槛初筛的正式候选标的</span>
        </div>

        <div className="stat-card">
          <span className="stat-label">市场确认</span>
          <div className="stat-value font-mono text-confirmed" data-testid="stat-confirmed-count">
            {data?.confirmed_count ?? 0}
          </div>
          <span className="stat-hint">均线与量价结构多头共振</span>
        </div>

        <div className="stat-card">
          <span className="stat-label">市场中性</span>
          <div className="stat-value font-mono text-neutral" data-testid="stat-neutral-count">
            {data?.neutral_count ?? 0}
          </div>
          <span className="stat-hint">走势待确认或未达加速条件</span>
        </div>
      </section>

      {/* 策略分布与信号分布条形图 */}
      <section className="distribution-section" aria-label="分布统计">
        <DistributionBars
          strategyDistribution={data?.strategy_distribution ?? {}}
          signalDistribution={data?.signal_distribution ?? {}}
        />
      </section>

      {/* Top 10 候选股票池表格 */}
      <section className="candidates-section" aria-label="Top 10 候选股票">
        <div className="section-header">
          <h2 className="section-title">Top 10 盘后研究候选股票</h2>
          <span className="section-subtitle">按策略评分与百分位优选排序，供深度研报分析</span>
        </div>

        {(!data?.top_candidates || data.top_candidates.length === 0) ? (
          <div className="empty-table-card">
            <p>暂无符合条件的 Top 候选股票。</p>
          </div>
        ) : (
          <div className="table-responsive">
            <table className="candidates-table" data-testid="candidates-table">
              <thead>
                <tr>
                  <th scope="col" className="col-rank">排名</th>
                  <th scope="col" className="col-symbol">标的代码</th>
                  <th scope="col" className="col-strategy">主策略</th>
                  <th scope="col" className="col-validation">市场验证</th>
                  <th scope="col" className="col-signal">信号</th>
                  <th scope="col" className="col-action">行动建议</th>
                  <th scope="col" className="col-reasons">入选理由</th>
                  <th scope="col" className="col-risks">风险提示</th>
                </tr>
              </thead>
              <tbody>
                {data.top_candidates.map((cand, index) => {
                  const rankDisplay = cand.rank ?? (index + 1);
                  return (
                    <tr key={cand.symbol} className="candidate-row">
                      <td className="col-rank font-mono">{rankDisplay}</td>
                      <td className="col-symbol">
                        <Link
                          to={`/stocks/${cand.symbol}`}
                          className="symbol-link font-mono"
                          title={`查看 ${cand.symbol} 完整画像`}
                        >
                          {cand.symbol}
                        </Link>
                      </td>
                      <td className="col-strategy">
                        <span className="strategy-tag font-mono">
                          {cand.primary_strategy_id}
                        </span>
                      </td>
                      <td className="col-validation">
                        <StatusBadge value={cand.market_validation} />
                      </td>
                      <td className="col-signal">
                        <StatusBadge value={cand.signal} />
                      </td>
                      <td className="col-action">
                        <StatusBadge value={cand.next_action} />
                      </td>
                      <td className="col-reasons">
                        <div className="tags-container">
                          {cand.reasons.length > 0 ? (
                            cand.reasons.map((r, i) => (
                              <span key={i} className="reason-tag">
                                {r}
                              </span>
                            ))
                          ) : (
                            <span className="text-dim">-</span>
                          )}
                        </div>
                      </td>
                      <td className="col-risks">
                        <div className="tags-container">
                          {cand.risks.length > 0 ? (
                            cand.risks.map((risk, i) => (
                              <StatusBadge
                                key={i}
                                value={risk}
                                highlight={risk === 'TREND_WEAKEN'}
                              />
                            ))
                          ) : (
                            <span className="text-dim">-</span>
                          )}
                        </div>
                      </td>
                    </tr>
                  );
                })}
              </tbody>
            </table>
          </div>
        )}
      </section>
    </div>
  );
}
