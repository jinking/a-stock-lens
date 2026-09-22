import { useCallback, useEffect, useRef, useState } from 'react';
import { Link, useParams } from 'react-router-dom';
import { ApiError, getStock } from '../api/client';
import type { SnapshotLineage, StockProfileResponse } from '../api/types';
import { useDateContext } from '../app/DateContext';
import { StatusBadge } from '../components/StatusBadge';

const lineageLabels: Array<[keyof SnapshotLineage, string]> = [
  ['universe_snapshot', 'Universe 快照'],
  ['factor_version', '因子版本'],
  ['strategy_version', '策略版本'],
  ['qualification_version', '合格规则版本'],
  ['regime_version', '市场环境版本'],
  ['market_validation_version', '市场验证版本'],
  ['signal_version', '信号版本'],
  ['candidate_policy_version', '候选政策版本'],
];

function displayValue(value: unknown): string {
  return value === null || value === undefined || value === '' ? '—' : String(value);
}

export function StockProfilePage() {
  const { symbol = '' } = useParams<{ symbol: string }>();
  const { asOf, loading: dateLoading } = useDateContext();
  const [profile, setProfile] = useState<StockProfileResponse | null>(null);
  const [loading, setLoading] = useState(false);
  const [error, setError] = useState<string | null>(null);
  const requestSequence = useRef(0);

  const fetchProfile = useCallback(async () => {
    const requestId = ++requestSequence.current;
    if (!asOf || !symbol) {
      setProfile(null);
      setLoading(false);
      setError(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const nextProfile = await getStock(symbol, asOf);
      if (requestId === requestSequence.current) setProfile(nextProfile);
    } catch (err) {
      if (requestId === requestSequence.current) {
        setProfile(null);
        setError(err instanceof ApiError || err instanceof Error ? err.message : '获取股票画像失败');
      }
    } finally {
      if (requestId === requestSequence.current) setLoading(false);
    }
  }, [asOf, symbol]);

  useEffect(() => {
    void fetchProfile();
    return () => { requestSequence.current += 1; };
  }, [fetchProfile]);

  const lineage = profile?.candidate?.lineage ?? {};
  const candidateStatusText = profile?.candidate_status === 'published_selected'
    ? '已发布候选池，该股票已入选'
    : profile?.candidate_status === 'not_selected'
      ? '已发布候选池，但该股票未入选'
      : '该日期未发布 Candidate Snapshot';

  return (
    <div className="page-container" data-testid="stock-profile-page">
      <header className="page-header">
        <h1 className="page-title">股票画像：<span className="font-mono">{symbol || '未指定'}</span></h1>
        <p className="page-description">{asOf ? `研究基准日期：${asOf}` : '展示候选资格、策略契合度、因子证据与数据血缘。'}</p>
      </header>

      {dateLoading || loading ? <div className="loading-card" role="status">正在加载股票画像…</div> : null}
      {error ? (
        <div className="error-card" role="alert">
          <p>{error}</p>
          <button type="button" className="button-secondary" onClick={() => void fetchProfile()}>重试</button>
        </div>
      ) : null}
      {!dateLoading && !asOf ? <div className="empty-state-card">尚无正式 Candidate 快照日期。</div> : null}

      {profile && !loading ? <>
        <section className="profile-section" aria-labelledby="profile-overview-title">
          <h2 id="profile-overview-title" className="section-title">概览</h2>
          <div className="profile-summary-grid">
            <div className="stat-card"><span className="stat-label">Universe</span><strong>{profile.universe.included ? '已纳入' : '未纳入'}</strong></div>
            <div className="stat-card"><span className="stat-label">候选状态</span><strong>{candidateStatusText}</strong></div>
            <div className="stat-card"><span className="stat-label">Watchlist</span><strong>{displayValue(profile.watchlist_status)}</strong></div>
          </div>
          {profile.universe.exclusion_rules.length > 0 ? <p>未纳入规则：{profile.universe.exclusion_rules.join('、')}</p> : null}
        </section>

        <section className="profile-section" aria-labelledby="profile-candidate-title">
          <h2 id="profile-candidate-title" className="section-title">Candidate 研究记录</h2>
          <p>{candidateStatusText}</p>
          {profile.candidate ? <div className="profile-card">
            <dl className="profile-details">
              <dt>主策略</dt><dd>{displayValue(profile.candidate.primary_strategy_id)}</dd>
              <dt>候选排名</dt><dd>{displayValue(profile.candidate.rank)}</dd>
              <dt>合格策略</dt><dd>{profile.candidate.qualified_strategies.join('、') || '—'}</dd>
              <dt>市场验证</dt><dd><StatusBadge value={profile.candidate.market_validation} /></dd>
              <dt>信号</dt><dd><StatusBadge value={profile.candidate.signal} /></dd>
              <dt>后续研究状态</dt><dd><StatusBadge value={profile.candidate.next_action} /></dd>
              <dt>入选理由</dt><dd>{profile.candidate.reasons.join('；') || '—'}</dd>
              <dt>风险提示</dt><dd>{profile.candidate.risks.length ? profile.candidate.risks.map((risk) => <StatusBadge key={risk} value={risk} highlight={risk === 'TREND_WEAKEN'} />) : '—'}</dd>
            </dl>
          </div> : null}
        </section>

        <section className="profile-section" aria-labelledby="profile-strategies-title">
          <h2 id="profile-strategies-title" className="section-title">策略表现</h2>
          {profile.strategies.length === 0 ? <p className="empty-inline">该日期没有此标的的策略记录。</p> : (
            <div className="table-responsive"><table className="data-table">
              <thead><tr><th scope="col">策略</th><th scope="col">分数</th><th scope="col">百分位</th><th scope="col">资格</th><th scope="col">理由</th><th scope="col">风险</th></tr></thead>
              <tbody>{profile.strategies.map((strategy) => <tr key={strategy.strategy_id}>
                <td><Link to={`/strategies/${strategy.strategy_id}`}>{strategy.strategy_id}</Link></td>
                <td className="font-mono">{displayValue(strategy.score)}</td>
                <td className="font-mono">{strategy.rank_percentile == null ? '—' : `${(strategy.rank_percentile * 100).toFixed(1)}%`}</td>
                <td>{strategy.eligible ? '符合' : '未符合'}</td>
                <td>{strategy.reasons.join('；') || '—'}</td><td>{strategy.risks.join('；') || '—'}</td>
              </tr>)}</tbody>
            </table></div>
          )}
        </section>

        <section className="profile-section" aria-labelledby="profile-factors-title">
          <h2 id="profile-factors-title" className="section-title">因子证据</h2>
          {profile.factors.length === 0 ? <p className="empty-inline">该日期没有因子记录。</p> : (
            <div className="table-responsive"><table className="data-table">
              <thead><tr><th scope="col">因子</th><th scope="col">状态</th><th scope="col">数值</th><th scope="col">单位</th><th scope="col">日期</th></tr></thead>
              <tbody>{profile.factors.map((factor) => <tr key={factor.factor}>
                <td>{factor.factor}</td><td><StatusBadge value={factor.status} /></td>
                <td className="font-mono">{factor.status === 'VALUE' ? displayValue(factor.raw_value) : '—'}</td>
                <td>{displayValue(factor.unit)}</td><td className="font-mono">{factor.as_of}</td>
              </tr>)}</tbody>
            </table></div>
          )}
        </section>

        <section className="profile-section" aria-labelledby="profile-lineage-title">
          <h2 id="profile-lineage-title" className="section-title">数据血缘</h2>
          <dl className="lineage-grid">{lineageLabels.map(([field, label]) => (
            <div key={field}><dt>{label}</dt><dd className="font-mono">{displayValue(lineage[field])}</dd></div>
          ))}</dl>
        </section>
      </> : null}
    </div>
  );
}
