// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

/**
 * Ring — small SVG circular progress indicator for stat cards.
 * Tone colors the arc: ok (success), warn (warning), danger (danger),
 * default (accent). Never animated beyond CSS transitions; disabled
 * under prefers-reduced-motion via the stylesheet.
 */
const TONE_VAR = {
  ok: 'var(--success)',
  warn: 'var(--warning)',
  danger: 'var(--danger)',
  default: 'var(--accent-color, var(--info))',
};

const RING_SIZE = 38;
const STROKE = 4;

export default function Ring({ value, size = RING_SIZE, tone = 'default', label }) {
  const pct = Math.min(100, Math.max(0, Number(value) || 0));
  const r = (RING_SIZE - STROKE) / 2;
  const c = 2 * Math.PI * r;
  const filled = (pct / 100) * c;
  const color = TONE_VAR[tone] || TONE_VAR.default;

  return (
    <svg
      className="ds-ring"
      width={size}
      height={size}
      viewBox={`0 0 ${RING_SIZE} ${RING_SIZE}`}
      role="img"
      aria-label={label || `${Math.round(pct)}%`}
      focusable="false"
    >
      <circle
        className="ds-ring-track"
        cx={RING_SIZE / 2}
        cy={RING_SIZE / 2}
        r={r}
        fill="none"
        strokeWidth={STROKE}
      />
      <circle
        className="ds-ring-fill"
        cx={RING_SIZE / 2}
        cy={RING_SIZE / 2}
        r={r}
        fill="none"
        strokeWidth={STROKE}
        stroke={color}
        strokeLinecap="round"
        strokeDasharray={`${filled} ${c - filled}`}
        transform={`rotate(-90 ${RING_SIZE / 2} ${RING_SIZE / 2})`}
      />
    </svg>
  );
}
