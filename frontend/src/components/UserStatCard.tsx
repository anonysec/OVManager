import { StatCard } from './ui';

/**
 * UserStatCard — one user-count tile on the Users page.
 * Thin wrapper over the StatCard primitive so every stat in the panel
 * shares the same label/value/tone treatment.
 */
const UserStatCard = ({ icon, label, value, tone = 'neutral', hint, className = '', ...rest }) => (
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
