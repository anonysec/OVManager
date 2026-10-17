// Copyright (c) 2026 anonysec
// SPDX-License-Identifier: MIT

import './Badge.css';
import type { ReactNode } from 'react';
import { FiCheckCircle, FiXCircle, FiAlertTriangle, FiCircle, FiHelpCircle } from 'react-icons/fi';
import type { IconType } from 'react-icons';

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

const ICONS: Record<string, IconType> = {
  online: FiCheckCircle,
  offline: FiXCircle,
  warning: FiAlertTriangle,
  danger: FiAlertTriangle,
  idle: FiCircle,
};

const TONES: Record<string, string> = {
  online: 'success',
  offline: 'danger',
  warning: 'warning',
  danger: 'danger',
  idle: 'neutral',
};

export const StatusBadge = ({ status = 'idle', label }: { status?: string; label?: ReactNode }) => {
  const Icon: IconType = ICONS[status] || FiHelpCircle;
  return (
    <Badge tone={TONES[status] || 'neutral'} dot className={`status-badge status-${status}`}>
      <Icon size={13} className="status-badge-icon" aria-hidden="true" />
      <span>{label}</span>
    </Badge>
  );
};
