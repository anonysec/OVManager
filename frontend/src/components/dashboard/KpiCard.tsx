// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT


import { useEffect, useId, useRef, useState } from 'react';
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';

const TONE_SR: Record<string, string> = { ok: 'normal', warn: 'warning', danger: 'critical' };

const useCountUp = (target: any) => {
  const [value, setValue] = useState(0);
  const prevRef = useRef(0);

  useEffect(() => {
    const from = prevRef.current;
    const to = Number(target) || 0;
    // Reduced motion: jump straight to the value instead of easing over it.
    const reduce = window.matchMedia?.('(prefers-reduced-motion: reduce)').matches;
    if (from === to || reduce) {
      setValue(to);
      prevRef.current = to;
      return;
    }
    let raf = 0;
    const start = performance.now();
    const step = (now: number) => {
      const p = Math.min(1, (now - start) / 700);
      const eased = 1 - Math.pow(1 - p, 3);
      setValue(from + (to - from) * eased);
      if (p < 1) {
        raf = requestAnimationFrame(step);
      } else {
        prevRef.current = to;
      }
    };
    raf = requestAnimationFrame(step);
    return () => cancelAnimationFrame(raf);
  }, [target]);

  return value;
};

/* Capacity meter — same 3px rail as the top-users bars. Reads at a glance
   without the ink of a donut, and the number above it stays the hero. */
function Meter({ pct, label }: { pct: number | string; label?: string }) {
  const value = Math.min(100, Math.max(0, Number(pct) || 0));
  return (
    <span
      className="ds-kpi-meter"
      role="img"
      aria-label={label || `${Math.round(value)}%`}
    >
      <span className="ds-kpi-meter-fill" style={{ width: `${value}%` }} />
    </span>
  );
}

function Sparkline({ values = [], tone = 'info' }: { values?: any[]; tone?: any }) {
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
      className="ds-spark"
      viewBox={`0 0 ${w} ${h}`}
      preserveAspectRatio="none"
      role="presentation"
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
}

export default function KpiCard({ icon: Icon, label, sub, value, animate, format, tone, spark, ringPct, chip, to }: { icon?: any; label?: any; sub?: any; value?: any; animate?: any; format?: any; tone?: any; spark?: any; ringPct?: any; chip?: any; to?: any }) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const anim: any = useCountUp(Number(animate ?? 0));
  const animated = animate !== null && animate !== undefined;
  const display: any = animated ? (format ? format(anim) : Math.round(anim).toLocaleString()) : value;
  const srValue: any = animated ? (format ? format(animate) : value) : value;

  const className = `ds-kpi ds-kpi--${tone || 'default'}`;

  const inner = (
    <>
      <div className="ds-kpi-head">
        {Icon && (
          <span className="ds-kpi-icon" aria-hidden="true">
            <Icon size={14} />
          </span>
        )}
        <span className="ds-kpi-label">{label}</span>
      </div>
      <div className="ds-kpi-value-row">
        <strong className="ds-kpi-value" aria-hidden={animated}>{display}</strong>
        {animated && <span className="sr-only">{srValue}</span>}
        {chip && <span className="ds-kpi-chip">{chip}</span>}
      </div>
      {ringPct !== undefined && ringPct !== null ? (
        <Meter pct={ringPct} label={`${label}: ${Math.round(Number(ringPct))}%`} />
      ) : null}
      {animated && !chip && <span className="sr-only"> ({String(t((TONE_SR as any)[tone] || '', tone as any))})</span>}
      {sub && <span className="ds-kpi-sub">{sub}</span>}
      {spark && spark.length > 1 && (
        <div className="ds-kpi-spark">
          <Sparkline values={spark} tone={tone || 'info'} />
        </div>
      )}
    </>
  );

  if (to) {
    return (
      <button
        type="button"
        className={className}
        onClick={() => navigate(to)}
        aria-label={chip ? `${label}: ${srValue}. ${chip}` : `${label}: ${srValue}`}
      >
        {inner}
      </button>
    );
  }
  return <div className={className}>{inner}</div>;
}
