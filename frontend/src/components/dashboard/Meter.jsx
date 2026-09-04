// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/** Horizontal resource meter: label, value, proportional bar with tone. */
import Sparkline from './Sparkline';

export default function Meter({ label, value, pct = 0, tone = 'ok', spark, ariaSuffix }) {
  const clamped = Math.min(100, Math.max(0, Number(pct) || 0));
  const labelText = ariaSuffix ? `${label}: ${value} (${ariaSuffix})` : `${label}: ${value}`;
  return (
    <div className={`ds-meter ds-meter--${tone}`}>
      <div className="ds-meter-label">
        <span>{label}</span>
        <span className="ds-meter-value">{value}</span>
      </div>
      <div
        className="ds-meter-bar"
        role="meter"
        aria-label={labelText}
        aria-valuenow={clamped}
        aria-valuemin={0}
        aria-valuemax={100}
      >
        <span className="ds-meter-fill" style={{ width: `${clamped}%` }} />
      </div>
      {spark && spark.length > 1 && <Sparkline values={spark} tone={tone} className="ds-meter-spark" />}
    </div>
  );
}
