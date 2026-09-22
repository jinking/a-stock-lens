import { Link } from 'react-router-dom';
import type { Candidate } from '../api/types';
import { StatusBadge } from './StatusBadge';

export interface CandidateTableProps {
  candidates: Candidate[];
}

export function CandidateTable({ candidates }: CandidateTableProps) {
  if (candidates.length === 0) {
    return (
      <div className="empty-table-card">
        <p>暂无候选股票数据。</p>
      </div>
    );
  }

  return (
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
          {candidates.map((cand, index) => {
            // 保留不可篡改的原始权威排名，严禁筛选后重排为 1, 2, 3...
            const rankDisplay = cand.rank ?? (index + 1);
            const isBreakdown = cand.signal === 'BREAKDOWN';

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
                  <div className="signal-cell-container">
                    <StatusBadge
                      value={cand.signal}
                      variant={isBreakdown ? 'contradicted' : undefined}
                    />
                    {isBreakdown && (
                      <span
                        className="signal-warning-breakdown"
                        data-testid="signal-warning-breakdown"
                        title="破位异常：候选标的出现BREAKDOWN信号，需排查数据一致性与策略逻辑"
                      >
                        破位告警
                      </span>
                    )}
                  </div>
                </td>
                <td className="col-action">
                  <StatusBadge value={cand.next_action} />
                </td>
                <td className="col-reasons">
                  <div className="tags-container">
                    {cand.reasons && cand.reasons.length > 0 ? (
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
                    {cand.risks && cand.risks.length > 0 ? (
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
  );
}
