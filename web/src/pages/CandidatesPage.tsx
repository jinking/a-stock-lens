export function CandidatesPage() {
  return (
    <div className="page-container" data-testid="candidates-page">
      <header className="page-header">
        <h1 className="page-title">候选股票池</h1>
        <p className="page-description">
          展示最新发布的正式研究候选（非买入建议）、主选策略、合格策略与市场验证状态。
        </p>
      </header>
      <div className="placeholder-card">
        <p>候选股票池列表占位展示。</p>
      </div>
    </div>
  );
}
