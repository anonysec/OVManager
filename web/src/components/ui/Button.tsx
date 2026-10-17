// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import './Button.css';
import type { ButtonHTMLAttributes, ReactNode } from 'react';

type ButtonProps = {
  variant?: any;
  size?: any;
  icon?: any;
  iconRight?: any;
  loading?: any;
  disabled?: boolean;
  block?: any;
  type?: ButtonHTMLAttributes<HTMLButtonElement>['type'];
  className?: string;
  children?: ReactNode;
  [key: string]: any;
};


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
}: ButtonProps) => (
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
