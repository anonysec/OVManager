// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import './Button.css';

/**
 * Button — the single interactive action primitive.
 *
 * Always a real <button>, so keyboard activation, form semantics and the
 * global focus ring come for free. `type` defaults to "button": an untyped
 * button inside a form submits it, which is never what a toolbar wants.
 */
const Button = ({
  variant = 'secondary',
  size = 'md',
  icon = null,
  iconRight = null,
  loading = false,
  disabled = false,
  block = false,
  type = 'button',
  className = '',
  children,
  ...rest
}) => (
  <button
    type={type}
    className={[
      'ui-btn',
      `ui-btn--${variant}`,
      `ui-btn--${size}`,
      block ? 'ui-btn--block' : '',
      className,
    ].filter(Boolean).join(' ')}
    disabled={disabled || loading}
    aria-busy={loading || undefined}
    {...rest}
  >
    {loading ? <span className="ui-btn-spinner" aria-hidden="true" /> : icon}
    {children != null && <span className="ui-btn-label">{children}</span>}
    {iconRight}
  </button>
);

export default Button;
