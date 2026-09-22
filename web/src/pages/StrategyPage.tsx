import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useNavigate, useParams } from 'react-router-dom';
import { ApiError, getQualifiedResults, getStrategyResults } from '../api/client';
import type { QualifiedScreenResult, StrategyScreenResult } from '../api/types';
import { useDateContext } from '../app/DateContext';
import { StatusBadge } from '../components/StatusBadge';

const strategies = [
  ['value', '价值'],
  ['growth', '成长'],
  ['garp', 'GARP'],
  ['quality', '质量'],
  ['dividend', '股息'],
  ['momentum', '动量'],
] as const;

type ResultTab = 'ranking' | 'qualified';

function percent(value: number | null | undefined): string {
  return value == null ? '—' : `${(value * 100).toFixed(1)}%`;
}

export function StrategyPage() {
  const { strategyId = 'value' } = useParams<{ strategyId: string }>();
  const navigate = useNavigate();
  const { asOf, loading: dateLoading } = useDateContext();
  const [tab, setTab] = useState<ResultTab>('ranking');
  const [ranking, setRanking] = useState<StrategyScreenResult | null>(null);
  const [qualified, setQualified] = useState<QualifiedScreenResult | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestSequence = useRef(0);

  const fetchResults = useCallback(async () => {
    const requestId = ++requestSequence.current;
    if (!asOf) {
      setRanking(null);
      setQualified(null);
      setLoading(false);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      if (tab === 'ranking') {
        const result = await getStrategyResults(strategyId, asOf, 50);
        if (requestId === requestSequence.current) setRanking(result);
      } else {
        const result = await getQualifiedResults(strategyId, asOf, 50);
        if (requestId === requestSequence.current) setQualified(result);
      }
    } catch (err) {
      if (requestId === requestSequence.current) {
        setError(err instanceof ApiError || err instanceof Error ? err.message : '获取策略结果失败');
        if (tab === 'ranking') setRanking(null);
        else setQualified(null);
      }
    } finally {
      if (requestId === requestSequence.current) setLoading(false);
    }
  }, [asOf, strategyId, tab]);

  useEffect(() => {
    void fetchResults();
    return () => { requestSequence.current += 1; };
  }, [fetchResults]);

  const selectedName = strategies.find(([id]) => id === strategyId)?.[1] ?? strategyId;
  const coverage = ranking?.coverage;
  const degraded = Boolean(coverage && (coverage.covered_count === 0 || coverage.covered_count < coverage.total_count));

  return (
    <div className="page-container" data-testid="strategy-page">
      <header className="page-header">
        <h1 className="page-title">策略研究：{selectedName}（{strategyId}）</h1>
        <p className="page-description">只读展示已发布策略快照的全市场排名与双门槛合格结果。基准日期：{asOf ?? '—'}</p>
      </header>

      <div className="strategy-toolbar">
        <label htmlFor="strategy-select">策略</label>
        <select id="strategy-select" aria-label="选择策略" value={strategyId}
          onChange={(event) => navigate(`/strategies/${event.target.value}`)}>
          {strategies.map(([id, name]) => <option key={id} value={id}>{name}（{id}）</option>)}
        </select>
      </div>

      <div className="strategy-tabs" role="tablist" aria-label="策略结果类型">
        <button type="button" role="tab" aria-selected={tab === 'ranking'} onClick={() => setTab('ranking')}>策略排名</button>
        <button type="button" role="tab" aria-selected={tab === 'qualified'} onClick={() => setTab('qualified')}>合格池</button>
      </div>

      {dateLoading || loading ? <div className="loading-card" role="status">正在加载策略结果…</div> : null}
      {error ? <div className="error-card" role="alert"><p>{error}</p><button type="button" className="retry-button" onClick={() => void fetchResults()}>重试</button></div> : null}
      {!dateLoading && !asOf ? <div className="empty-state-card">尚无正式 Candidate 快照日期。</div> : null}

      {tab === 'ranking' && ranking && !loading ? <section className="profile-section" aria-label="策略排名结果">
        <div className="coverage-summary" data-testid="strategy-coverage">
          覆盖 {coverage?.covered_count ?? 0} / {coverage?.total_count ?? 0} 条策略记录（{percent(coverage?.coverage_ratio)}）
        </div>
        {degraded ? <p className="coverage-warning" role="status">覆盖不足：排名快照中仅有部分记录完成评分或排名。</p> : null}
        {ranking.results.length === 0 ? <div className="empty-table-card">暂无排名数据</div> : (
          <div className="table-responsive"><table className="data-table">
            <thead><tr><th scope="col">排名</th><th scope="col">标的</th><th scope="col">分数</th><th scope="col">百分位</th><th scope="col">置信度</th><th scope="col">入选理由</th><th scope="col">风险</th></tr></thead>
            <tbody>{ranking.results.map((item, index) => <tr key={item.symbol}>
              <td className="font-mono">{item.rank ?? index + 1}</td>
              <td className="font-mono"><Link to={`/stocks/${item.symbol}`}>{item.symbol}</Link></td>
              <td className="font-mono">{item.score ?? '—'}</td><td className="font-mono">{percent(item.rank_percentile)}</td><td className="font-mono">{percent(item.confidence)}</td>
              <td>{item.reasons.join('；') || '—'}</td><td>{item.risks.length ? item.risks.map((risk) => <StatusBadge key={risk} value={risk} highlight={risk === 'TREND_WEAKEN'} />) : '—'}</td>
            </tr>)}</tbody>
          </table></div>
        )}
      </section> : null}

      {tab === 'qualified' && qualified && !loading ? <section className="profile-section" aria-label="双门槛合格结果">
        <h2 className="section-title">双门槛合格池</h2>
        <div className="coverage-summary">合格 {qualified.qualified_count} 只 / 覆盖 {qualified.coverage_count} 条策略记录</div>
        {qualified.warnings?.map((warning) => <p className="coverage-warning" role="status" key={warning}>{warning}</p>)}
        {qualified.items.length === 0 ? <div className="empty-table-card">暂无双门槛合格标的。</div> : (
          <div className="table-responsive"><table className="data-table">
            <thead><tr><th scope="col">标的</th><th scope="col">百分位</th></tr></thead>
            <tbody>{qualified.items.map((item) => <tr key={item.symbol}>
              <td className="font-mono"><Link to={`/stocks/${item.symbol}`}>{item.symbol}</Link></td>
              <td className="font-mono">{percent(item.rank_percentile)}</td>
            </tr>)}</tbody>
          </table></div>
        )}
      </section> : null}
    </div>
  );
}
