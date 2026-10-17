// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import './Card.css';
import type { ElementType, ReactNode } from 'react';

type CardProps = {
  as?: ElementType;
  title?: any;
  subtitle?: any;
  icon?: any;
  actions?: any;
  padded?: boolean;
  tone?: any;
  className?: string;
  children?: ReactNode;
  [key: string]: any;
};


const Card = ({
  as: Tag = 'div',
  title,
  subtitle,
  icon,
  actions,
  padded = true,
  tone = 'neutral',
  className = '',
  children,
  ...rest
}: CardProps) => (
  <Tag
    className={[
      'ui-card',
      `ui-card--${tone}`,
      padded ? 'ui-card--padded' : '',
      className,
    ].filter(Boolean).join(' ')}
    {...rest}
  >
    {(title || subtitle || actions) && (
      <div className="ui-card-head">
        <div className="ui-card-heading">
          {icon && <span className="ui-card-icon" aria-hidden="true">{icon}</span>}
          <div className="ui-card-heading-text">
            {title && <h3 className="ui-card-title">{title}</h3>}
            {subtitle && <p className="ui-card-subtitle">{subtitle}</p>}
          </div>
        </div>
        {actions && <div className="ui-card-actions">{actions}</div>}
      </div>
    )}
    <div className="ui-card-body">{children}</div>
  </Tag>
);

export default Card;
