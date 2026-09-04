// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * KpiCard — hero KPI: animated value, optional sparkline, click-through.
 * - `to` makes the whole card a button that navigates to that path.
 * - `tone` colors the value and icon (ok / warn / danger / default).
 * - `accent` sets the top stripe color via CSS var.
 * - Animation is driven by useCountUp; we expose the real value to AT
 *   via sr-only to avoid mid-animation misreads.
 */
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { FiArrowRight, FiArrowUpRight } from 'react-icons/fi';
import { useCountUp } from '../../hooks/useCountUp';
import Sparkline from './Sparkline';

const TONE_SR = { ok: 'normal', warn: 'warning', danger: 'critical' };

export default function KpiCard({ icon: Icon, label, sub, value, animate, format, tone, spark, accent, to }) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const anim = useCountUp(Number(animate ?? 0));
  const animated = animate !== null && animate !== undefined;
  const display = animated ? (format ? format(anim) : Math.round(anim).toLocaleString()) : value;
  const srValue = animated ? (format ? format(animate) : value) : value;

  const style = accent ? { '--ds-accent': accent } : undefined;
  const className = `ds-kpi ds-kpi--${tone || 'default'}`;

  const inner = (
    <>
      <div className="ds-kpi-top">
        <span className="ds-kpi-icon" aria-hidden="true">{Icon && <Icon />}</span>
        <span className="ds-kpi-arrow" aria-hidden="true">
          {to ? <FiArrowUpRight size={14} /> : <FiArrowRight size={14} />}
        </span>
      </div>
      <span className="ds-kpi-label">{label}</span>
      <strong className="ds-kpi-value" aria-hidden={animated}>{display}</strong>
      {animated && <span className="sr-only">{srValue}</span>}
      {tone && TONE_SR[tone] && <span className="sr-only"> ({t(TONE_SR[tone], tone)})</span>}
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
        style={style}
        onClick={() => navigate(to)}
        aria-label={sub ? `${label}: ${srValue}. ${sub}` : `${label}: ${srValue}`}
      >
        {inner}
      </button>
    );
  }
  return <div className={className} style={style}>{inner}</div>;
}
