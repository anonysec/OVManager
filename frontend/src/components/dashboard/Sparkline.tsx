// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * Tiny SVG sparkline. Renders a smooth area + line given a numeric series.
 * - viewBox is always 100x100; the SVG is sized by its CSS container.
 * - `tone` selects the gradient color via a CSS var fallback.
 * - Decorative by default; pass `label` to give screen readers a hint.
 * - `className` is forwarded to the outer svg so the parent can size it.
 */
import { memo, useId } from 'react';

const Sparkline = memo(function Sparkline({ values = [], tone = 'info', label, className = '' }) {
  const id = useId().replace(/:/g, '');
  if (!values || values.length < 2) {
    return <div className="ds-spark-empty" aria-hidden="true" />;
  }

  const series = values.map((v) => Math.max(0, Number(v) || 0));
  const max = Math.max(...series, 1);
  const w = 100;
  const h = 100;
  const pad = 2;

  const points = series.map((v, i) => {
    const x = pad + (i / (series.length - 1)) * (w - pad * 2);
    const y = h - pad - (v / max) * (h - pad * 2);
    return [x, y];
  });

  const linePath = points.map(([x, y], i) => `${i === 0 ? 'M' : 'L'}${x.toFixed(2)},${y.toFixed(2)}`).join(' ');
  const areaPath = `${linePath} L${points[points.length - 1][0].toFixed(2)},${h} L${points[0][0].toFixed(2)},${h} Z`;

  const gradId = `spark-${id}`;
  const stroke = `var(--${tone}, var(--info))`;

  return (
    <svg
      className={`ds-spark ${className}`.trim()}
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      role={label ? 'img' : 'presentation'}
      aria-label={label || undefined}
    >
      <defs>
        <linearGradient id={gradId} x1="0" y1="0" x2="0" y2="1">
          <stop offset="0%" stopColor={stroke} stopOpacity="0.32" />
          <stop offset="100%" stopColor={stroke} stopOpacity="0" />
        </linearGradient>
      </defs>
      <path d={areaPath} fill={`url(#${gradId})`} />
      <path d={linePath} fill="none" stroke={stroke} strokeWidth="2.5" strokeLinecap="round" strokeLinejoin="round" vectorEffect="non-scaling-stroke" />
    </svg>
  );
});

export default Sparkline;
