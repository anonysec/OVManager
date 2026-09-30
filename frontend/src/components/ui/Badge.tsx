// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import './Badge.css';

// The dot takes the FILL token (--success/--warning/--danger) while the label
// uses the *-text tone, so the pill stays readable in both themes.
const Badge = ({ tone = 'neutral', dot = false, className = '', children, ...rest }: { tone?: any; dot?: any; className?: string; children?: any; [key: string]: any }) => (
  <span
    className={['ui-badge', `ui-badge--${tone}`, className].filter(Boolean).join(' ')}
    {...rest}
  >
    {dot && <span className="ui-badge-dot" aria-hidden="true" />}
    {children}
  </span>
);

export default Badge;
