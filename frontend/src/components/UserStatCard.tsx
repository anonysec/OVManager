import type { ReactNode } from 'react';
import { StatCard } from './ui';

// Thin wrapper over StatCard so every stat in the panel shares one
// label/value/tone treatment.

type UserStatCardProps = {
  icon: ReactNode;
  label: string;
  value: ReactNode;
  tone?: string;
  hint?: ReactNode;
  className?: string;
  [key: string]: any;
};

const UserStatCard = ({ icon, label, value, tone = 'neutral', hint, className = '', ...rest }: UserStatCardProps) => (
  <StatCard
    icon={icon}
    label={label}
    value={value}
    tone={tone}
    hint={hint}
    className={['um-stat', className].filter(Boolean).join(' ')}
    {...rest}
  />
);

export default UserStatCard;
