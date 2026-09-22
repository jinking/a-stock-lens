import type { MarketRegime } from '../api/types';

export function formatMarketRegime(regime: MarketRegime | null | undefined): string {
  if (regime === 'BULL') return 'BULL (多头市场)';
  if (regime === 'BEAR') return 'BEAR (空头市场)';
  if (regime === 'SHOCK') return 'SHOCK (震荡市场)';
  return '未知';
}

export interface StatusBadgeProps {
  type?: 'regime' | 'validation' | 'signal' | 'action' | 'risk' | 'default';
  value: string;
  variant?: 'confirmed' | 'neutral' | 'contradicted' | 'warning' | 'info' | 'default';
  className?: string;
  highlight?: boolean;
  testId?: string;
}

export function StatusBadge({
  value,
  variant,
  className = '',
  highlight = false,
  testId,
}: StatusBadgeProps) {
  let resolvedVariant = variant;
  if (!resolvedVariant) {
    if (value === 'CONFIRMED' || value === 'TRACK_SIGNAL' || value === 'BULL') {
      resolvedVariant = 'confirmed';
    } else if (value === 'CONTRADICTED' || value === 'BEAR') {
      resolvedVariant = 'contradicted';
    } else if (value === 'SHOCK' || value === 'TREND_WEAKEN' || highlight) {
      resolvedVariant = 'warning';
    } else if (value === 'NEUTRAL' || value === 'WATCH') {
      resolvedVariant = 'neutral';
    } else {
      resolvedVariant = 'default';
    }
  }

  const isHighlighted = highlight || value === 'TREND_WEAKEN';

  const classes = [
    'status-badge',
    `badge-${resolvedVariant}`,
    isHighlighted ? 'risk-badge-highlight' : '',
    className,
  ]
    .filter(Boolean)
    .join(' ');

  const defaultTestId = testId ?? (value === 'TREND_WEAKEN' ? 'risk-badge-TREND_WEAKEN' : undefined);

  return (
    <span className={classes} data-testid={defaultTestId}>
      {value}
    </span>
  );
}
