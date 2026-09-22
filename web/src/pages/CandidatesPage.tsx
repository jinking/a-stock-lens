import { useCallback, useEffect, useMemo, useState } from 'react';
import { ApiError, getCandidates } from '../api/client';
import type { Candidate, MarketValidation, Signal } from '../api/types';
import { useDateContext } from '../app/DateContext';
import { CandidateTable } from '../components/CandidateTable';

export function CandidatesPage() {
  const { asOf, loading: dateLoading, error: dateError } = useDateContext();

  const [candidates, setCandidates] = useState<Candidate[] | null>(null);
  const [loading, setLoading] = useState<boolean>(false);
  const [error, setError] = useState<string | null>(null);

  // 四项客户端视图筛选状态（绝不引入服务端或额外重排）
  const [symbolFilter, setSymbolFilter] = useState<string>('');
  const [strategyFilter, setStrategyFilter] = useState<string>('');
  const [validationFilter, setValidationFilter] = useState<string>('');
  const [signalFilter, setSignalFilter] = useState<string>('');

  const fetchData = useCallback(async () => {
    if (!asOf) {
      setCandidates(null);
      return;
    }
    setLoading(true);
    setError(null);
    try {
      const resp = await getCandidates(asOf);
      // 固化权威排名：如果记录未显式携带 rank，以初始快照序号 + 1 固化，防止筛选时被篡改重新排序
      const recordsWithRank: Candidate[] = (resp.records ?? []).map((cand, idx) => ({
        ...cand,
        rank: cand.rank ?? (idx + 1),
      }));
      setCandidates(recordsWithRank);
    } catch (err) {
      if (err instanceof ApiError || err instanceof Error) {
        setError(err.message);
      } else {
        setError('获取候选股票池失败');
      }
      setCandidates(null);
    } finally {
      setLoading(false);
    }
  }, [asOf]);

  useEffect(() => {
    if (asOf) {
      void fetchData();
    } else {
      setCandidates(null);
    }
  }, [asOf, fetchData]);

  const handleResetFilters = useCallback(() => {
    setSymbolFilter('');
    setStrategyFilter('');
    setValidationFilter('');
    setSignalFilter('');
  }, []);

  // 动态收集可用的策略与信号选项
  const strategyOptions = useMemo(() => {
    if (!candidates) return [];
    const set = new Set<string>();
    for (const c of candidates) {
      if (c.primary_strategy_id) {
        set.add(c.primary_strategy_id);
      }
    }
    return Array.from(set).sort();
  }, [candidates]);

  const validationOptions: MarketValidation[] = ['CONFIRMED', 'NEUTRAL', 'CONTRADICTED'];

  const signalOptions = useMemo(() => {
    const defaultSignals: Signal[] = [
      'BREAKOUT',
      'MOMENTUM_ACCELERATION',
      'BREAKDOWN',
      'NEUTRAL',
      'OVERSOLD_BOUNCE',
      'VALUE_CONTRARIAN',
      'DIVIDEND_DEFENSIVE',
      'TREND_FOLLOWING',
    ];
    const set = new Set<string>(defaultSignals);
    if (candidates) {
      for (const c of candidates) {
        if (c.signal) {
          set.add(c.signal);
        }
      }
    }
    return Array.from(set);
  }, [candidates]);

  // 纯客户端过滤逻辑，严格保留各行原有 authoritative rank
  const filteredCandidates = useMemo(() => {
    if (!candidates) return [];
    return candidates.filter((cand) => {
      if (symbolFilter.trim()) {
        const query = symbolFilter.trim().toLowerCase();
        if (!cand.symbol.toLowerCase().includes(query)) {
          return false;
        }
      }
      if (strategyFilter && cand.primary_strategy_id !== strategyFilter) {
        return false;
      }
      if (validationFilter && cand.market_validation !== validationFilter) {
        return false;
      }
      if (signalFilter && cand.signal !== signalFilter) {
        return false;
      }
      return true;
    });
  }, [candidates, symbolFilter, strategyFilter, validationFilter, signalFilter]);

  // 无可用日期状态
  if (!dateLoading && asOf == null) {
    return (
      <div className="page-container" data-testid="candidates-page">
        <header className="page-header">
          <h1 className="page-title">候选股票池</h1>
          <p className="page-description">
            展示最新发布的正式研究候选（非买入建议）、主选策略、合格策略与市场验证状态。
          </p>
        </header>
        <div className="empty-state-card" data-testid="candidates-empty-date">
          <p className="empty-notice">尚无正式 Candidate 快照。先运行标准 astock daily。</p>
        </div>
      </div>
    );
  }

  // 加载中状态
  if (dateLoading || loading) {
    return (
      <div className="page-container" data-testid="candidates-page">
        <header className="page-header">
          <h1 className="page-title">候选股票池</h1>
          <p className="page-description">快照基准日期：{asOf ?? '加载中...'}</p>
        </header>
        <div className="loading-card" data-testid="candidates-loading">
          <div className="loading-spinner" />
          <p>正在加载候选股票池...</p>
        </div>
      </div>
    );
  }

  // 错误状态
  if (error || dateError) {
    const displayError = error ?? dateError ?? '获取候选股票池失败';
    return (
      <div className="page-container" data-testid="candidates-page">
        <header className="page-header">
          <h1 className="page-title">候选股票池</h1>
          <p className="page-description">快照基准日期：{asOf ?? '未知'}</p>
        </header>
        <div className="error-card" data-testid="candidates-error">
          <p className="error-message">{displayError}</p>
          <button type="button" className="retry-button" onClick={() => void fetchData()}>
            重试
          </button>
        </div>
      </div>
    );
  }

  const totalCount = candidates?.length ?? 0;
  const filteredCount = filteredCandidates.length;

  return (
    <div className="page-container" data-testid="candidates-page">
      <header className="page-header">
        <h1 className="page-title">候选股票池</h1>
        <p className="page-description">
          快照基准日期：<span className="font-mono text-accent">{asOf}</span> ·
          客观量化候选池统计与分析（非投资买卖建议）
        </p>
      </header>

      {/* 4 项客户端多维筛选栏与统计摘要，严格禁止添加客户端重排下拉框 */}
      <section className="filter-panel" aria-label="候选池筛选">
        <div className="filter-controls">
          <div className="filter-field">
            <label htmlFor="filter-symbol-input" className="filter-label">
              代码搜索
            </label>
            <input
              id="filter-symbol-input"
              type="text"
              className="filter-input font-mono"
              placeholder="搜索代码 (如 600519)..."
              value={symbolFilter}
              onChange={(e) => setSymbolFilter(e.target.value)}
              data-testid="filter-symbol"
            />
          </div>

          <div className="filter-field">
            <label htmlFor="filter-strategy-select" className="filter-label">
              主策略
            </label>
            <select
              id="filter-strategy-select"
              className="filter-select font-mono"
              value={strategyFilter}
              onChange={(e) => setStrategyFilter(e.target.value)}
              data-testid="filter-strategy"
            >
              <option value="">全部策略</option>
              {strategyOptions.map((strat) => (
                <option key={strat} value={strat}>
                  {strat}
                </option>
              ))}
            </select>
          </div>

          <div className="filter-field">
            <label htmlFor="filter-validation-select" className="filter-label">
              市场验证
            </label>
            <select
              id="filter-validation-select"
              className="filter-select"
              value={validationFilter}
              onChange={(e) => setValidationFilter(e.target.value)}
              data-testid="filter-validation"
            >
              <option value="">全部验证状态</option>
              {validationOptions.map((v) => (
                <option key={v} value={v}>
                  {v}
                </option>
              ))}
            </select>
          </div>

          <div className="filter-field">
            <label htmlFor="filter-signal-select" className="filter-label">
              信号
            </label>
            <select
              id="filter-signal-select"
              className="filter-select"
              value={signalFilter}
              onChange={(e) => setSignalFilter(e.target.value)}
              data-testid="filter-signal"
            >
              <option value="">全部信号</option>
              {signalOptions.map((s) => (
                <option key={s} value={s}>
                  {s}
                </option>
              ))}
            </select>
          </div>

          <div className="filter-actions">
            <button
              type="button"
              className="filter-reset-button"
              onClick={handleResetFilters}
              data-testid="filter-reset"
            >
              重置筛选
            </button>
          </div>
        </div>

        <div className="filter-summary-row">
          <span className="filter-summary-text" data-testid="candidate-count-summary">
            展示 <span className="font-mono text-accent">{filteredCount}</span> / 总计{' '}
            <span className="font-mono text-accent">{totalCount}</span> 只候选标的
          </span>
        </div>
      </section>

      {/* 候选表格或空筛选提示 */}
      <section className="candidates-content-section" aria-label="候选股票列表">
        {totalCount > 0 && filteredCount === 0 ? (
          <div className="empty-state-card" data-testid="candidates-empty-filter">
            <p className="empty-notice">无符合筛选条件的候选标的</p>
            <button
              type="button"
              className="retry-button"
              onClick={handleResetFilters}
            >
              重置筛选
            </button>
          </div>
        ) : (
          <CandidateTable candidates={filteredCandidates} />
        )}
      </section>
    </div>
  );
}
