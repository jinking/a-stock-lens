interface DistributionSectionProps {
  title: string;
  data: Record<string, number>;
  testId: string;
}

function DistributionSection({ title, data, testId }: DistributionSectionProps) {
  const entries = Object.entries(data).sort((a, b) => b[1] - a[1]);
  const maxCount = Math.max(...entries.map(([, count]) => count), 1);

  return (
    <div className="distribution-card" data-testid={testId}>
      <h3 className="distribution-title">{title}</h3>
      {entries.length === 0 ? (
        <p className="distribution-empty">暂无分布数据</p>
      ) : (
        <div className="distribution-list">
          {entries.map(([name, count]) => {
            const percentage = Math.min(100, Math.max(0, (count / maxCount) * 100));
            return (
              <div key={name} className="distribution-row">
                <div className="distribution-info">
                  <span className="distribution-label" title={name}>
                    {name}
                  </span>
                  <span className="distribution-count font-mono">{count}</span>
                </div>
                <div className="distribution-bar-track">
                  <div
                    className="distribution-bar-fill"
                    style={{ width: `${percentage}%` }}
                    role="progressbar"
                    aria-valuenow={count}
                    aria-valuemin={0}
                    aria-valuemax={maxCount}
                  />
                </div>
              </div>
            );
          })}
        </div>
      )}
    </div>
  );
}

export interface DistributionBarsProps {
  strategyDistribution: Record<string, number>;
  signalDistribution: Record<string, number>;
}

export function DistributionBars({
  strategyDistribution,
  signalDistribution,
}: DistributionBarsProps) {
  return (
    <div className="distribution-grid">
      <DistributionSection
        title="主策略分布"
        data={strategyDistribution}
        testId="strategy-distribution-bars"
      />
      <DistributionSection
        title="信号分布"
        data={signalDistribution}
        testId="signal-distribution-bars"
      />
    </div>
  );
}
