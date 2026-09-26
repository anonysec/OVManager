// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import './Badge.css';

/**
 * Badge — compact status/count pill.
 *
 * The dot's colour is the FILL token (--success/--warning/--danger) while the
 * label uses the *-text tone, so the pill stays readable in both themes.
 */
const Badge = ({ tone = 'neutral', dot = false, className = '', children, ...rest }) => (
  <span
    className={['ui-badge', `ui-badge--${tone}`, className].filter(Boolean).join(' ')}
    {...rest}
  >
    {dot && <span className="ui-badge-dot" aria-hidden="true" />}
    {children}
  </span>
);

export default Badge;
