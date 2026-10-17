// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import './PageHeader.css';


const PageHeader = ({
  title,
  subtitle,
  icon,
  meta,
  actions,
  className = '',
}: { title?: any; subtitle?: any; icon?: any; meta?: any; actions?: any; className?: string }) => (
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
