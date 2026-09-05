// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * KpiCard — hero stat cell inside the dashboard strip. Calm ops-console
 * look: small inline icon + label, tabular value, optional sparkline.
 * - `to` makes the whole cell a button that navigates to that path.
 * - `tone` colors the value and icon (ok / warn / danger / default).
 * - Animation is driven by useCountUp; we expose the real value to AT
 *   via sr-only to avoid mid-animation misreads.
 */
import { useNavigate } from 'react-router-dom';
import { useTranslation } from 'react-i18next';
import { FiArrowUpRight } from 'react-icons/fi';
import { useCountUp } from '../../hooks/useCountUp';
import Sparkline from './Sparkline';

const TONE_SR = { ok: 'normal', warn: 'warning', danger: 'critical' };

export default function KpiCard({ icon: Icon, label, sub, value, animate, format, tone, spark, to }) {
  const navigate = useNavigate();
  const { t } = useTranslation();
  const anim = useCountUp(Number(animate ?? 0));
  const animated = animate !== null && animate !== undefined;
  const display = animated ? (format ? format(anim) : Math.round(anim).toLocaleString()) : value;
  const srValue = animated ? (format ? format(animate) : value) : value;

  const className = `ds-kpi ds-kpi--${tone || 'default'}`;

  const inner = (
    <>
      <div className="ds-kpi-head">
        {Icon && <span className="ds-kpi-icon" aria-hidden="true"><Icon /></span>}
        <span className="ds-kpi-label">{label}</span>
        {to && (
          <span className="ds-kpi-arrow" aria-hidden="true">
            <FiArrowUpRight size={14} />
          </span>
        )}
      </div>
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
        onClick={() => navigate(to)}
        aria-label={sub ? `${label}: ${srValue}. ${sub}` : `${label}: ${srValue}`}
      >
        {inner}
      </button>
    );
  }
  return <div className={className}>{inner}</div>;
}
