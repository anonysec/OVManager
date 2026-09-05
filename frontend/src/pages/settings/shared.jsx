// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import { useTranslation } from 'react-i18next';

/* ─────────────────────────────────────────────
   Section header with anchor
───────────────────────────────────────────── */
const SectionHeader = ({ headingId, icon: Icon, label, description }) => (
  <div className="sp-section-header">
    <span className="sp-section-icon">{Icon ? <Icon aria-hidden="true" /> : null}</span>
    <div>
      <h2 id={headingId}>{label}</h2>
      {description && <p>{description}</p>}
    </div>
  </div>
);

/* ─────────────────────────────────────────────
   Card wrapper
───────────────────────────────────────────── */
const Card = ({ title, icon: Icon, children, className = '' }) => (
  <div className={`sp-card ${className}`}>
    {title && (
      <div className="sp-card-head">
        {Icon && <Icon size={15} aria-hidden="true" />}
        <span>{title}</span>
      </div>
    )}
    <div className="sp-card-body">{children}</div>
  </div>
);

/* ─────────────────────────────────────────────
   Field helpers
───────────────────────────────────────────── */
const Field = ({ label, hint, children, horizontal, inputId }) => (
  <div className={`sp-field${horizontal ? ' sp-field--h' : ''}`}>
    <label className="sp-label" htmlFor={inputId}>{label}</label>
    {children}
    {hint && <p className="sp-hint">{hint}</p>}
  </div>
);

const TONE_SR_KEY = { danger: 'critical', warn: 'warning', ok: 'allSystemsClear', muted: 'noNotif' };

const Stat = ({ label, value, tone }) => {
  const { t } = useTranslation();
  return (
    <div className={`sp-stat${tone ? ` sp-stat--${tone}` : ''}`}>
      <span>{label}</span>
      <strong>
        {value}
        {tone && <span className="sr-only"> ({t(TONE_SR_KEY[tone] || 'warning', tone)})</span>}
      </strong>
    </div>
  );
};

export { SectionHeader, Card, Field, Stat };
