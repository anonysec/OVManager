// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * KpiCard — compact stat card (panel-style): small accent icon box +
 * muted label in the head, an optional Ring top-right, the big bold
 * value bottom-left, and an optional small chip bottom-right.
 * - `ring` renders a circular progress for `ringPct`.
 * - `chip` renders a quiet badge at the value row's end (e.g. "4 cores").
 * - `to` makes the whole card a button that navigates to that path.
 * - `tone` colors value + icon + ring (ok / warn / danger).
 */
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { useCountUp } from '../../hooks/useCountUp';
import Sparkline from './Sparkline';
import Ring from './Ring';

const TONE_SR: Record<string, string> = { ok: 'normal', warn: 'warning', danger: 'critical' };

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
        {ringPct !== undefined && ringPct !== null ? (
          <Ring value={ringPct} tone={tone || 'default'} label={`${label}: ${Math.round(Number(ringPct))}%`} />
        ) : null}
      </div>
      <div className="ds-kpi-value-row">
        <strong className="ds-kpi-value" aria-hidden={animated}>{display}</strong>
        {animated && <span className="sr-only">{srValue}</span>}
        {chip && <span className="ds-kpi-chip">{chip}</span>}
      </div>
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
