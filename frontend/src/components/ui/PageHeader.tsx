// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import './PageHeader.css';

/**
 * PageHeader — the title block every redesigned page opens with.
 * Owns the page's single <h1>; `meta` is a slot for badges/timestamps and
 * `actions` for buttons. On phones the actions wrap below the title.
 */
const PageHeader = ({
  title,
  subtitle,
  icon,
  meta,
  actions,
  className = '',
}) => (
  <header className={['ui-page-header', className].filter(Boolean).join(' ')}>
    {icon && <span className="ui-page-header-icon" aria-hidden="true">{icon}</span>}
    <div className="ui-page-header-text">
      <h1 className="ui-page-header-title">{title}</h1>
      {subtitle && <p className="ui-page-header-subtitle">{subtitle}</p>}
      {meta && <div className="ui-page-header-meta">{meta}</div>}
    </div>
    {actions && <div className="ui-page-header-actions">{actions}</div>}
  </header>
);

export default PageHeader;
