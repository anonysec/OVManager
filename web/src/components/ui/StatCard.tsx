// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import './StatCard.css';
import type { ElementType, ReactNode } from 'react';

type StatCardProps = {
  as?: ElementType;
  label?: any;
  value?: any;
  icon?: any;
  hint?: any;
  tone?: any;
  className?: string;
  children?: ReactNode;
  [key: string]: any;
};


const StatCard = ({
  as: Tag = 'div',
  label,
  value,
  icon,
  hint,
  tone = 'neutral',
  className = '',
  ...rest
}: StatCardProps) => (
  <Tag
    className={[
      'ui-stat-card',
      `ui-stat-card--${tone}`,
      Tag === 'button' ? 'ui-stat-card--interactive' : '',
      className,
    ].filter(Boolean).join(' ')}
    {...rest}
  >
    <span className="ui-stat-card-top">
      <span className="ui-stat-card-label">{label}</span>
      {icon && <span className="ui-stat-card-icon" aria-hidden="true">{icon}</span>}
    </span>
    <span className="ui-stat-card-value">{value}</span>
    {hint && <span className="ui-stat-card-hint">{hint}</span>}
  </Tag>
);

export default StatCard;
